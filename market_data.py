"""market_data.py · 个股与同业数据采集层

职责
    把 Yahoo Finance（yfinance）与东方财富（akshare）的原始接口封装成三个纯函数，
    不依赖 Streamlit，可被网页、快照构建脚本和评测脚本共同调用。

对外函数
    sf(val)                       安全转 float：None / NaN / inf / 非数值一律返回 None
    fetch_all_data(ticker)        单只股票的全量数据包：基本信息、1 年 K 线、新闻、
                                  分析师评级与目标价、财报三表、业绩预期、机构持仓等
    fetch_industry_benchmark(...) 同行业估值基准：A 股取东财行业成分股中位数，
                                  美股/港股取 yfinance 同行业头部公司 PE/PB/PS 中位数

失败约定
    任何子接口失败都返回空 DataFrame / 空 dict / None，绝不抛异常给页面。
    云端部署时 Yahoo 会对共享 IP 限流（YFRateLimitError），此时返回的数据包会大面积为空，
    由 snapshot.py 判断并换用仓库内的数据快照。
"""
import math
import time

import numpy as np
import pandas as pd
import yfinance as yf


# ===========================================================================
# 通用安全工具：一切数值提取都必须经过这里，杜绝 NaN / None / 类型异常穿透
# ===========================================================================
def sf(val):
    """Safe float：任何不可转换 / NaN / inf 一律返回 None。"""
    if val is None:
        return None
    try:
        if isinstance(val, (list, tuple, np.ndarray, pd.Series)):
            if len(val) == 0:
                return None
            val = val[0] if not isinstance(val, pd.Series) else val.iloc[0]
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def fetch_industry_benchmark(ticker: str, industry_key: str = "", industry_name: str = "",
                             is_a_share: bool = False, pure_code: str = "") -> dict | None:
    """动态计算同行业估值基准（成分股中位数 + 均值）。

    A 股   → akshare 东财行业板块成分股（含动态市盈率/市净率）
    美/港股 → yfinance Industry.top_companies 成分股逐一取 PE/PB/PS

    返回 dict:
      {'pe','pb','ps','pe_mean','pb_mean','ps_mean','peer_count','source','peers'}
    无法获取真实同业数据时返回 None（调用方必须 st.warning 明示缺失，禁止兜底常量）。
    """
    if is_a_share:
        # 主路径：东财申万行业板块全部成分股实时动态 PE/PB
        res = _benchmark_a_share(industry_name, pure_code)
        if res:
            return res
        # 备用路径：akshare 限流/行业名不匹配时，改用 yfinance 同行业可比公司实时倍数。
        # 依旧是真实市场数据（仅数据源不同），并在 source 中明确标注供用户判别口径。
        res = _benchmark_global(ticker, industry_key, industry_name)
        if res:
            res["source"] = "备用源 · " + str(res.get("source", "")) + "（东财行业接口不可用）"
            return res
        return None

    res = _benchmark_global(ticker, industry_key, industry_name)
    return res or None



def _median_mean(series):
    s = pd.to_numeric(pd.Series(series), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    s = s[(s > 0) & (s < 500)]          # 剔除亏损/异常离群值
    if s.empty:
        return None, None
    return sf(s.median()), sf(s.mean())


def _benchmark_a_share(industry_name: str, pure_code: str) -> dict | None:
    """A 股：东财行业板块成分股实时市盈率/市净率中位数。"""
    try:
        import akshare as ak
    except Exception:
        return None

    board = (industry_name or "").strip()
    cons = None

    # 1) 直接用 info 里的行业名取成分股
    for name in [board, board.replace("行业", ""), board.replace("Ⅱ", "")]:
        if not name:
            continue
        try:
            cons = ak.stock_board_industry_cons_em(symbol=name)
            if cons is not None and not cons.empty:
                board = name
                break
        except Exception:
            cons = None

    # 2) 行业名不匹配东财口径时，模糊匹配板块列表
    if cons is None or cons.empty:
        try:
            names = ak.stock_board_industry_name_em()
            col = next((c for c in names.columns if "名称" in str(c)), names.columns[0])
            cand = [str(x) for x in names[col].tolist()]
            hit = next((c for c in cand if board and (c in board or board in c)), None)
            if hit:
                cons = ak.stock_board_industry_cons_em(symbol=hit)
                board = hit
        except Exception:
            cons = None

    if cons is None or cons.empty:
        return None

    try:
        pe_col = next((c for c in cons.columns if "市盈率" in str(c)), None)
        pb_col = next((c for c in cons.columns if "市净率" in str(c)), None)
        mcap_col = next((c for c in cons.columns if "总市值" in str(c)), None)
        pe_med, pe_mean = _median_mean(cons[pe_col]) if pe_col else (None, None)
        pb_med, pb_mean = _median_mean(cons[pb_col]) if pb_col else (None, None)

        # PS 无直接字段：用 总市值 / 营业总收入(TTM) 近似需逐股拉财报，成本过高，
        # 因此这里明确置 None，由 UI 展示"该口径数据缺失"，不做编造。
        if pe_med is None and pb_med is None:
            return None
        return {
            "pe": pe_med, "pb": pb_med, "ps": None,
            "pe_mean": pe_mean, "pb_mean": pb_mean, "ps_mean": None,
            "peer_count": int(len(cons)),
            "source": f"akshare 东财行业板块「{board}」全部 {len(cons)} 只成分股实时中位数",
            "peers": cons.head(30),
        }
    except Exception:
        return None


def _benchmark_global(ticker: str, industry_key: str, industry_name: str) -> dict | None:
    """美股/港股：yfinance Industry 成分股逐一取真实 PE/PB/PS 后求中位数。"""
    try:
        import yfinance as yf
    except Exception:
        return None

    keys = []
    if industry_key:
        keys.append(industry_key)
    if industry_name:
        keys.append(str(industry_name).lower().replace(" ", "-").replace("—", "-").replace("&", "and"))

    peers_df = None
    used_key = ""
    for k in keys:
        try:
            ind = yf.Industry(k)
            tc = ind.top_companies
            if tc is not None and not tc.empty:
                peers_df = tc
                used_key = k
                break
        except Exception:
            continue

    if peers_df is None or peers_df.empty:
        return None

    symbols = [s for s in list(peers_df.index)[:14] if str(s).upper() != str(ticker).upper()][:10]
    rows = []
    for sym in symbols:
        try:
            pi = yf.Ticker(sym).info or {}
            rows.append({
                "symbol": sym,
                "name": pi.get("shortName", sym),
                "PE": sf(pi.get("trailingPE")) or sf(pi.get("forwardPE")),
                "PB": sf(pi.get("priceToBook")),
                "PS": sf(pi.get("priceToSalesTrailing12Months")),
            })
        except Exception:
            continue

    if not rows:
        return None
    pdf = pd.DataFrame(rows)
    pe_med, pe_mean = _median_mean(pdf["PE"])
    pb_med, pb_mean = _median_mean(pdf["PB"])
    ps_med, ps_mean = _median_mean(pdf["PS"])
    if pe_med is None and pb_med is None and ps_med is None:
        return None
    return {
        "pe": pe_med, "pb": pb_med, "ps": ps_med,
        "pe_mean": pe_mean, "pb_mean": pb_mean, "ps_mean": ps_mean,
        "peer_count": int(len(pdf)),
        "source": f"yfinance 行业「{used_key}」头部 {len(pdf)} 家可比公司实时倍数中位数",
        "peers": pdf,
    }


def fetch_all_data(ticker_input):
    """全量数据采集引擎：yfinance + akshare 双源汇聚与自动降级补全"""
    data = {}
    stock = yf.Ticker(ticker_input)
    # ⚠️ 稳定性修复：stock.info 在接口限流(Too Many Requests)时会直接抛异常，
    # 之前未做 try/except 会导致整页崩溃。这里加入重试 + 兜底，绝不让异常向上传播。
    data['info'] = {}
    for attempt in range(3):
        try:
            data['info'] = stock.info or {}
            if data['info'].get('shortName') or data['info'].get('currentPrice'):
                break
        except Exception:
            if attempt < 2:
                time.sleep(1.5)
            else:
                data['info'] = {}

    # ⚠️ 关键修复：当 stock.info 被限流返回空字典时，使用 fast_info 填充核心指标
    if not data['info'].get('currentPrice') and not data['info'].get('trailingPE'):
        try:
            fi = stock.fast_info
            if fi is not None:
                if not data['info'].get('currentPrice'):
                    data['info']['currentPrice'] = getattr(fi, 'last_price', None)
                    data['info']['regularMarketPrice'] = getattr(fi, 'last_price', None)
                if not data['info'].get('previousClose'):
                    data['info']['previousClose'] = getattr(fi, 'previous_close', None)
                if not data['info'].get('marketCap'):
                    data['info']['marketCap'] = getattr(fi, 'market_cap', None)
                if not data['info'].get('fiftyTwoWeekHigh'):
                    data['info']['fiftyTwoWeekHigh'] = getattr(fi, 'year_high', None)
                if not data['info'].get('fiftyTwoWeekLow'):
                    data['info']['fiftyTwoWeekLow'] = getattr(fi, 'year_low', None)
                if not data['info'].get('currency'):
                    data['info']['currency'] = getattr(fi, 'currency', 'USD')
        except Exception:
            pass

    try:
        data['hist_1y'] = stock.history(period="1y").dropna(subset=['Close'])
    except Exception:
        data['hist_1y'] = pd.DataFrame()

    try:
        data['news'] = stock.news or []
    except Exception:
        data['news'] = []

    try:
        data['recommendations'] = stock.recommendations
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['recommendations'] = pd.DataFrame()
    try:
        data['analyst_targets'] = stock.analyst_price_targets
    except Exception:
        data['analyst_targets'] = {}
    try:
        data['earnings_dates'] = stock.earnings_dates
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['earnings_dates'] = pd.DataFrame()
    try:
        data['institutional_holders'] = stock.institutional_holders
        # P6 Fallback strategies
        if data['institutional_holders'] is None or data['institutional_holders'].empty:
            data['institutional_holders'] = stock.major_holders
        if data['institutional_holders'] is None or data['institutional_holders'].empty:
            data['institutional_holders'] = stock.mutualfund_holders
    except Exception:
        data['institutional_holders'] = pd.DataFrame()
    try:
        data['quarterly_financials'] = stock.quarterly_financials
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['quarterly_financials'] = pd.DataFrame()

    # 获取季度利润表（用于美股/港股业务分部收入展示）
    try:
        data['quarterly_income_stmt'] = stock.quarterly_income_stmt
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['quarterly_income_stmt'] = pd.DataFrame()

    # 获取年度利润表（同上，更完整的收入分部数据）
    try:
        data['income_stmt'] = stock.income_stmt
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['income_stmt'] = pd.DataFrame()

    # P7: 获取季度与年度现金流量表
    try:
        data['quarterly_cashflow'] = stock.quarterly_cashflow
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['quarterly_cashflow'] = pd.DataFrame()
    try:
        data['cashflow'] = stock.cashflow
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['cashflow'] = pd.DataFrame()

    # P7: 获取季度与年度资产负债表
    try:
        data['quarterly_balance_sheet'] = stock.quarterly_balance_sheet
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['quarterly_balance_sheet'] = pd.DataFrame()
    try:
        data['balance_sheet'] = stock.balance_sheet
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['balance_sheet'] = pd.DataFrame()

    # V7 战役二：PEG 所需的「未来 EPS 一致预期增速」真实数据源（绝不使用假设增速）
    try:
        data['growth_estimates'] = stock.growth_estimates
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['growth_estimates'] = pd.DataFrame()
    try:
        data['earnings_estimate'] = stock.earnings_estimate
    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['earnings_estimate'] = pd.DataFrame()

    # 获取公司业务概要（longBusinessSummary）
    if not data['info'].get('longBusinessSummary'):
        try:
            # 单独再试一次获取 info 中的业务描述
            bs = stock.info.get('longBusinessSummary', '')
            if bs:
                data['info']['longBusinessSummary'] = bs
        except Exception:
            pass

    pure_code = ticker_input.replace('.SS', '').replace('.SZ', '')
    is_a_share = ticker_input.endswith('.SS') or ticker_input.endswith('.SZ') or pure_code.isdigit()
    data['is_a_share'] = is_a_share
    data['pure_code'] = pure_code

    # 当 yfinance 缺失 A 股关键行情或报错时，自动使用 akshare / 东方财富双源补全
    if is_a_share or not data['info'].get('currentPrice'):
        try:
            import akshare as ak
            df_info = ak.stock_individual_info_em(symbol=pure_code)
            if df_info is not None and not df_info.empty:
                info_dict = dict(zip(df_info['item'], df_info['value']))
                name = info_dict.get('股票简称') or info_dict.get('股票名称')
                if name and not data['info'].get('shortName'):
                    data['info']['shortName'] = name
                ind = info_dict.get('行业')
                if ind and not data['info'].get('industry'):
                    data['info']['industry'] = ind
                    data['info']['sector'] = ind
                mcap = info_dict.get('总市值')
                if mcap:
                    try: data['info']['marketCap'] = float(mcap)
                    except: pass
                pe_val = info_dict.get('市盈率(动)') or info_dict.get('市盈率(静)')
                if pe_val:
                    try: data['info']['trailingPE'] = float(pe_val)
                    except: pass
        except Exception:
            pass

        # 补全 K 线与最新收盘价
        if data['hist_1y'].empty:
            try:
                import akshare as ak
                df_k = ak.stock_zh_a_hist(symbol=pure_code, period="daily", adjust="qfq")
                if df_k is not None and not df_k.empty:
                    df_k['Date'] = pd.to_datetime(df_k['日期'])
                    df_k.set_index('Date', inplace=True)
                    df_k.rename(columns={'开盘': 'Open', '最高': 'High', '最低': 'Low', '收盘': 'Close', '成交量': 'Volume'}, inplace=True)
                    data['hist_1y'] = df_k[['Open', 'High', 'Low', 'Close', 'Volume']].tail(250)
            except Exception:
                pass

        if not data['hist_1y'].empty and not data['info'].get('currentPrice'):
            last_p = round(float(data['hist_1y']['Close'].iloc[-1]), 2)
            data['info']['currentPrice'] = last_p
            data['info']['regularMarketPrice'] = last_p
            data['info']['currency'] = 'CNY'

    # A股主营业务构成（akshare 真实数据）：用于地区/产品线客观展示，无数据则留空不编造
    data['main_composition'] = None
    if is_a_share:
        try:
            import akshare as ak
            data['ak_news'] = ak.stock_news_em(symbol=pure_code)
        except Exception:
            data['ak_news'] = None
        try:
            import akshare as ak
            data['ak_forecast'] = ak.stock_profit_forecast_em(symbol=pure_code)
        except Exception:
            data['ak_forecast'] = None
        try:
            import akshare as ak
            data['ak_info'] = ak.stock_individual_info_em(symbol=pure_code)
        except Exception:
            data['ak_info'] = None
        try:
            import akshare as ak
            data['main_composition'] = ak.stock_zygc_em(symbol=pure_code)
        except Exception:
            data['main_composition'] = None
    else:
        data['ak_news'] = pd.DataFrame()
        data['ak_forecast'] = pd.DataFrame()
        data['ak_info'] = pd.DataFrame()

    # ⚠️ 关键修复：当 stock.info 缺少 PE 等指标时，从 hist_1y 和 quarterly_financials 计算补全
    if not data['info'].get('trailingPE') and not data['hist_1y'].empty:
        try:
            qf = data.get('quarterly_financials')
            if qf is not None and not qf.empty:
                # 尝试从最近4个季度的净利润计算 TTM EPS
                for eps_key in ['Basic EPS', 'Diluted EPS']:
                    if eps_key in qf.index:
                        eps_vals = qf.loc[eps_key].dropna().head(4)
                        if len(eps_vals) >= 1:
                            eps_ttm = float(eps_vals.sum()) if len(eps_vals) == 4 else float(eps_vals.iloc[0]) * 4
                            if eps_ttm > 0:
                                cur_p = data['info'].get('currentPrice') or float(data['hist_1y']['Close'].iloc[-1])
                                data['info']['trailingPE'] = round(cur_p / eps_ttm, 2)
                                data['info']['trailingEps'] = round(eps_ttm, 2)
                            break
        except Exception:
            pass

    return data
