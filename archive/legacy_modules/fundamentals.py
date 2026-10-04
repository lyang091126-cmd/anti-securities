"""
fundamentals.py — V7 数据净化与深度基本面穿透引擎
================================================================================
本模块承担两大职责（战役一 + 战役二）：

战役一 · 数据源绝对净化
  - fetch_industry_benchmark(): 同行业 PE/PB/PS 基准**动态实时拉取**
    （美股/港股走 yfinance Industry 成分股；A 股走东财行业板块成分股），
    绝不返回 PE=20x 这类静态写死常量。拉取失败 → 返回 None，由 UI 层
    用 st.warning 明示"真实数据缺失"，禁止编造。
  - fetch_institutional_holdings(): 机构持仓多接口级联降级
    （东财十大流通股东 → 十大股东 → 股东持股明细 → yfinance 机构持仓），
    全部失败 → 返回空结果 + 失败原因，绝不生成"张三/李四"占位数据。
  - fetch_institution_surveys(): 机构调研记录多接口级联降级。

战役二 · 深度量化指标穿透
  - compute_advanced_metrics(): EBITDA 利润率、经营性现金流 vs 净利润
    含金量、杜邦三因子拆解、研发费用率、PEG 倍数。
    全部指标带 try/except + NaN 处理，任何一项失败不影响其它指标。

所有对外函数均为纯数据函数（不含 st 渲染），仅用 st.cache_data 做缓存。
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# 语义化色彩规范（全局唯一定义，UI 层统一引用，禁止各处散落硬编码色值）
# ---------------------------------------------------------------------------
C_UP = "#00E676"        # 上涨 / 资金流入 / 低估
C_UP_DIM = "#00b865"
C_DOWN = "#FF4B4B"      # 下跌 / 资金流出 / 高估
C_DOWN_DIM = "#ef4444"
C_NEUTRAL = "#8B93A7"   # 中性 / 标签 / 说明
C_NEUTRAL_DIM = "#64748B"
C_ACCENT = "#00F2FE"    # 强调（终端青）
C_WARN = "#FBBF24"
C_TEXT = "#F0F4F8"
C_BG_CARD = "rgba(19, 23, 34, 0.92)"
C_BORDER = "rgba(255, 255, 255, 0.07)"


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


def _row(df, keys, col_idx=0):
    """从财报 DataFrame 中按多个可能的行名取指定列的值。"""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for k in keys:
        if k in df.index:
            try:
                series = df.loc[k].dropna()
                if len(series) > col_idx:
                    return sf(series.iloc[col_idx])
            except Exception:
                continue
    return None


def _row_ttm(qdf, adf, keys):
    """优先用最近 4 个季度求和得到 TTM；季报不足时回退到最新年报。"""
    if qdf is not None and isinstance(qdf, pd.DataFrame) and not qdf.empty:
        for k in keys:
            if k in qdf.index:
                try:
                    vals = qdf.loc[k].dropna()
                    if len(vals) >= 4:
                        return sf(vals.iloc[:4].sum()), "TTM(近4季度合计)"
                    if len(vals) >= 1:
                        return sf(vals.iloc[0]), "最新单季度"
                except Exception:
                    continue
    v = _row(adf, keys)
    if v is not None:
        return v, "最新年报"
    return None, None


def _avg_two(df, keys):
    """资产/权益类科目取期初期末均值（周转率口径更严谨）；仅一期则用当期。"""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for k in keys:
        if k in df.index:
            try:
                vals = df.loc[k].dropna()
                if len(vals) >= 2:
                    return sf((float(vals.iloc[0]) + float(vals.iloc[1])) / 2.0)
                if len(vals) == 1:
                    return sf(vals.iloc[0])
            except Exception:
                continue
    return None


# ===========================================================================
# 战役二 · 深度基本面穿透指标计算
# ===========================================================================
REV_KEYS = ["Total Revenue", "TotalRevenue", "Operating Revenue", "Revenue"]
NI_KEYS = ["Net Income", "Net Income Common Stockholders",
           "NetIncomeCommonStockholders", "Net Income Continuous Operations"]
OCF_KEYS = ["Operating Cash Flow", "OperatingCashFlow",
            "Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities"]
EBITDA_KEYS = ["EBITDA", "Normalized EBITDA", "NormalizedEBITDA"]
OPINC_KEYS = ["Operating Income", "OperatingIncome", "Total Operating Income As Reported"]
DA_KEYS = ["Depreciation And Amortization", "DepreciationAndAmortization",
           "Depreciation Amortization Depletion", "Reconciled Depreciation",
           "Depreciation And Amortization In Income Statement"]
RD_KEYS = ["Research And Development", "ResearchAndDevelopment"]
ASSET_KEYS = ["Total Assets", "TotalAssets"]
EQUITY_KEYS = ["Stockholders Equity", "StockholdersEquity",
               "Total Equity Gross Minority Interest", "Common Stock Equity"]


def compute_advanced_metrics(all_data: dict) -> dict:
    """盈利质量 / 杜邦 / 研发 / PEG 全量深度指标。

    返回结构（每项均可能为 None，UI 层必须按 None 显示 "数据缺失"）：
        {
          'ebitda', 'ebitda_margin', 'ebitda_note',
          'ocf', 'net_income', 'ocf_to_ni', 'earnings_quality_label',
          'net_margin', 'asset_turnover', 'equity_multiplier',
          'roe_dupont', 'roe_reported',
          'rd', 'rd_to_revenue',
          'pe', 'eps_growth_3y', 'peg', 'peg_source',
          'revenue', 'period_note', 'warnings': [...]
        }
    """
    out = {k: None for k in [
        "ebitda", "ebitda_margin", "ebitda_note", "ocf", "net_income", "ocf_to_ni",
        "earnings_quality_label", "net_margin", "asset_turnover", "equity_multiplier",
        "roe_dupont", "roe_reported", "rd", "rd_to_revenue", "pe", "eps_growth_3y",
        "peg", "peg_source", "revenue", "period_note",
    ]}
    out["warnings"] = []

    info = (all_data or {}).get("info") or {}
    qis = (all_data or {}).get("quarterly_income_stmt")
    if qis is None or (isinstance(qis, pd.DataFrame) and qis.empty):
        qis = (all_data or {}).get("quarterly_financials")
    ais = (all_data or {}).get("income_stmt")
    qcf = (all_data or {}).get("quarterly_cashflow")
    acf = (all_data or {}).get("cashflow")
    qbs = (all_data or {}).get("quarterly_balance_sheet")
    abs_ = (all_data or {}).get("balance_sheet")

    # ---------- 营收（TTM 口径） ----------
    try:
        rev, period_note = _row_ttm(qis, ais, REV_KEYS)
        if rev is None:
            rev = sf(info.get("totalRevenue"))
            period_note = "yfinance info.totalRevenue (TTM)"
        out["revenue"], out["period_note"] = rev, period_note
    except Exception:
        out["warnings"].append("营收口径解析失败")

    # ---------- EBITDA 与 EBITDA 利润率 ----------
    try:
        ebitda, _ = _row_ttm(qis, ais, EBITDA_KEYS)
        note = "报表直接披露 EBITDA"
        if ebitda is None:
            op_inc, _ = _row_ttm(qis, ais, OPINC_KEYS)
            da, _ = _row_ttm(qis, ais, DA_KEYS)
            if da is None:
                da, _ = _row_ttm(qcf, acf, DA_KEYS)
            if op_inc is not None and da is not None:
                ebitda = op_inc + abs(da)
                note = "推算：营业利润 + 折旧摊销"
        if ebitda is None:
            ebitda = sf(info.get("ebitda"))
            note = "yfinance info.ebitda (TTM)" if ebitda is not None else None
        out["ebitda"], out["ebitda_note"] = ebitda, note
        if ebitda is not None and out["revenue"]:
            out["ebitda_margin"] = ebitda / out["revenue"]
    except Exception:
        out["warnings"].append("EBITDA 计算失败")

    # ---------- 经营性现金流 vs 净利润（利润含金量） ----------
    try:
        ocf, _ = _row_ttm(qcf, acf, OCF_KEYS)
        if ocf is None:
            ocf = sf(info.get("operatingCashflow"))
        ni, _ = _row_ttm(qis, ais, NI_KEYS)
        if ni is None:
            ni = sf(info.get("netIncomeToCommon"))
        out["ocf"], out["net_income"] = ocf, ni
        if ocf is not None and ni not in (None, 0):
            ratio = ocf / abs(ni)
            out["ocf_to_ni"] = ratio
            if ni < 0:
                out["earnings_quality_label"] = "账面亏损，现金流对比仅供参考"
            elif ratio >= 1.2:
                out["earnings_quality_label"] = "现金流显著高于账面利润，利润含金量高"
            elif ratio >= 0.9:
                out["earnings_quality_label"] = "现金流与账面利润基本匹配"
            elif ratio >= 0.5:
                out["earnings_quality_label"] = "现金流低于账面利润，需关注应收/存货占用"
            else:
                out["earnings_quality_label"] = "现金流大幅低于账面利润，利润含金量偏弱"
        if ocf is not None and ni is not None and out["revenue"]:
            out["net_margin"] = ni / out["revenue"]
    except Exception:
        out["warnings"].append("现金流/净利润对比失败")

    # ---------- 杜邦三因子拆解 ROE = 净利率 × 总资产周转率 × 权益乘数 ----------
    try:
        ni = out["net_income"]
        rev = out["revenue"]
        bs_q = qbs if (qbs is not None and isinstance(qbs, pd.DataFrame) and not qbs.empty) else abs_
        assets_avg = _avg_two(bs_q, ASSET_KEYS)
        if assets_avg is None:
            assets_avg = _row(abs_, ASSET_KEYS)
        equity = _row(bs_q, EQUITY_KEYS) or _row(abs_, EQUITY_KEYS)

        if out["net_margin"] is None and ni is not None and rev:
            out["net_margin"] = ni / rev
        if rev and assets_avg:
            out["asset_turnover"] = rev / assets_avg
        if assets_avg and equity:
            out["equity_multiplier"] = assets_avg / equity
        if all(out[k] is not None for k in ("net_margin", "asset_turnover", "equity_multiplier")):
            out["roe_dupont"] = out["net_margin"] * out["asset_turnover"] * out["equity_multiplier"]
        out["roe_reported"] = sf(info.get("returnOnEquity"))
    except Exception:
        out["warnings"].append("杜邦拆解失败")

    # ---------- 研发费用率 ----------
    try:
        rd, _ = _row_ttm(qis, ais, RD_KEYS)
        out["rd"] = rd
        if rd is not None and out["revenue"]:
            out["rd_to_revenue"] = abs(rd) / out["revenue"]
    except Exception:
        out["warnings"].append("研发费用率计算失败")

    # ---------- PEG = PE / 未来 EPS 一致预期增速 ----------
    try:
        pe = sf(info.get("trailingPE")) or sf(info.get("forwardPE"))
        out["pe"] = pe
        growth, src = _resolve_forward_growth(all_data)
        out["eps_growth_3y"] = growth
        out["peg_source"] = src
        if pe and growth and growth > 0:
            out["peg"] = pe / (growth * 100.0)
        elif sf(info.get("trailingPegRatio")):
            out["peg"] = sf(info.get("trailingPegRatio"))
            out["peg_source"] = out["peg_source"] or "yfinance trailingPegRatio"
    except Exception:
        out["warnings"].append("PEG 计算失败")

    return out


def _resolve_forward_growth(all_data: dict):
    """解析未来 EPS 一致预期年化增速（小数，如 0.25 = 25%）。

    优先级：yfinance growth_estimates (+1y / +5y) → earnings_estimate 同比
            → akshare 东财盈利预测 EPS 序列推算 CAGR → info.earningsGrowth。
    全部失败返回 (None, None)，UI 层展示"一致预期缺失"。
    """
    ge = (all_data or {}).get("growth_estimates")
    try:
        if ge is not None and isinstance(ge, pd.DataFrame) and not ge.empty:
            col = next((c for c in ge.columns if "stock" in str(c).lower()), ge.columns[0])
            for idx in ["+5y", "+1y", "0y"]:
                if idx in ge.index:
                    g = sf(ge.loc[idx, col])
                    if g is not None and g != 0:
                        return (g if abs(g) < 3 else g / 100.0), f"yfinance 分析师一致预期增速 ({idx})"
    except Exception:
        pass

    ee = (all_data or {}).get("earnings_estimate")
    try:
        if ee is not None and isinstance(ee, pd.DataFrame) and not ee.empty and "growth" in ee.columns:
            for idx in ["+1y", "0y"]:
                if idx in ee.index:
                    g = sf(ee.loc[idx, "growth"])
                    if g:
                        return (g if abs(g) < 3 else g / 100.0), f"yfinance EPS 预期同比 ({idx})"
    except Exception:
        pass

    fc = (all_data or {}).get("ak_forecast")
    try:
        if fc is not None and isinstance(fc, pd.DataFrame) and not fc.empty:
            eps_cols = [c for c in fc.columns if "收益" in str(c) or "EPS" in str(c).upper()]
            vals = []
            for c in eps_cols:
                v = sf(pd.to_numeric(fc[c], errors="coerce").dropna().mean())
                if v is not None:
                    vals.append(v)
            if len(vals) >= 2 and vals[0] > 0:
                years = len(vals) - 1
                cagr = (vals[-1] / vals[0]) ** (1.0 / years) - 1.0 if vals[-1] > 0 else None
                if cagr is not None and -0.9 < cagr < 5:
                    return cagr, "akshare 东财一致预期 EPS 复合增速"
    except Exception:
        pass

    g = sf(((all_data or {}).get("info") or {}).get("earningsGrowth"))
    if g:
        return g, "yfinance info.earningsGrowth（历史同比，非前瞻）"
    return None, None


# ===========================================================================
# 战役一 · 同行业估值基准动态拉取（绝不写死 PE=20x）
# ===========================================================================
@st.cache_data(ttl=3600, show_spinner=False)
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
        # 因此这里明确置 None，由 UI 展示"该口径真实数据缺失"，不做编造。
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


# ===========================================================================
# 战役一 · 机构持仓 / 机构调研：多接口级联，失败即明示缺失
# ===========================================================================
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_institutional_holdings(ticker: str, is_a_share: bool, pure_code: str,
                                 shares_outstanding=None) -> dict:
    """机构/大股东持仓真实数据抓取。

    返回 {'names': [...], 'shares': [...], 'source': str, 'error': str|None}
    任何情况下都不会返回虚构股东名，names 为空即代表真实数据缺失。
    """
    result = {"names": [], "shares": [], "source": "", "error": None}
    errors = []

    if is_a_share:
        try:
            import akshare as ak
        except Exception as e:
            result["error"] = f"akshare 不可用: {e}"
            return result

        attempts = [
            ("东财十大流通股东 (stock_gdfx_free_top_10_em)",
             lambda: ak.stock_gdfx_free_top_10_em(symbol=_em_symbol(pure_code)),
             ("股东名称",), ("占总流通股本持股比例", "占总流通股本比例", "持股比例")),
            ("东财十大股东 (stock_gdfx_top_10_em)",
             lambda: ak.stock_gdfx_top_10_em(symbol=_em_symbol(pure_code)),
             ("股东名称",), ("占总股本持股比例", "持股比例")),
            ("流通股东明细 (stock_circulate_stock_holder)",
             lambda: ak.stock_circulate_stock_holder(symbol=pure_code),
             ("股东名称",), ("占总流通股本比例", "持股比例")),
        ]
        for label, fn, name_keys, pct_keys in attempts:
            try:
                df = fn()
                if df is None or df.empty:
                    errors.append(f"{label}: 空返回")
                    continue
                names, shares = _parse_holder_df(df, name_keys, pct_keys)
                if names:
                    result.update({"names": names, "shares": shares,
                                   "source": f"akshare {label}（真实披露数据）"})
                    return result
                errors.append(f"{label}: 字段无法解析")
            except Exception as e:
                errors.append(f"{label}: {type(e).__name__}")
        result["error"] = " | ".join(errors) or "全部 A 股股东接口无有效返回"
        return result

    # 美股 / 港股
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        for label, getter in [
            ("institutional_holders", lambda: tk.institutional_holders),
            ("mutualfund_holders", lambda: tk.mutualfund_holders),
            ("insider_roster_holders", lambda: tk.insider_roster_holders),
        ]:
            try:
                df = getter()
            except Exception as e:
                errors.append(f"{label}: {type(e).__name__}")
                continue
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                errors.append(f"{label}: 空返回")
                continue
            names, shares = _parse_yf_holder_df(df, shares_outstanding)
            if names:
                result.update({"names": names, "shares": shares,
                               "source": f"yfinance {label}（13F/公开披露）"})
                return result
            errors.append(f"{label}: 字段无法解析")
    except Exception as e:
        errors.append(f"yfinance: {type(e).__name__}")

    result["error"] = " | ".join(errors) or "全部机构持仓接口无有效返回"
    return result


def _em_symbol(pure_code: str) -> str:
    """东财接口部分需要带市场前缀（sh/sz/bj）。"""
    code = str(pure_code).zfill(6)
    if code.startswith(("6", "9", "5")):
        return f"sh{code}"
    if code.startswith(("0", "3", "2", "1")):
        return f"sz{code}"
    return f"bj{code}"


def _parse_holder_df(df, name_keys, pct_keys):
    name_col = next((c for c in df.columns if any(k in str(c) for k in name_keys)), None)
    pct_col = next((c for c in df.columns if any(k in str(c) for k in pct_keys)), None)
    if name_col is None:
        return [], []
    names, shares = [], []
    for _, row in df.head(20).iterrows():
        raw = str(row[name_col]).strip()
        if not raw or raw.lower() == "nan":
            continue
        pct = sf(row[pct_col]) if pct_col else None
        if pct is None:
            continue
        names.append(raw[:18] + ".." if len(raw) > 18 else raw)
        shares.append(round(pct, 2))
        if len(names) >= 10:
            break
    return names, shares


def _parse_yf_holder_df(df, shares_outstanding=None):
    cols = list(df.columns)
    name_col = next((c for c in cols if "holder" in str(c).lower() or "name" in str(c).lower()), cols[0])
    pct_col = next((c for c in cols if "% out" in str(c).lower() or "pctheld" in str(c).lower().replace(" ", "")), None)
    sh_col = next((c for c in cols if "shares" in str(c).lower()), None)
    names, shares = [], []
    for _, row in df.head(12).iterrows():
        raw = str(row[name_col]).strip()
        if not raw or raw.lower() == "nan":
            continue
        pct = None
        if pct_col is not None:
            v = sf(row[pct_col])
            if v is not None:
                pct = v * 100.0 if v <= 1.0 else v
        if pct is None and sh_col is not None and shares_outstanding:
            v = sf(row[sh_col])
            so = sf(shares_outstanding)
            if v is not None and so:
                pct = v / so * 100.0
        if pct is None:
            continue
        names.append(raw[:18] + ".." if len(raw) > 18 else raw)
        shares.append(round(pct, 2))
        if len(names) >= 10:
            break
    return names, shares


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_institution_surveys(pure_code: str, days: int = 120) -> dict:
    """机构调研记录多接口级联抓取（仅 A 股有强制披露）。"""
    import datetime as _dt
    out = {"df": None, "source": "", "error": None}
    errors = []
    try:
        import akshare as ak
    except Exception as e:
        out["error"] = f"akshare 不可用: {e}"
        return out

    try:
        df = ak.stock_jgdy_detail_em(symbol=pure_code)
        if df is not None and not df.empty:
            out.update({"df": df, "source": "akshare stock_jgdy_detail_em（东财机构调研明细）"})
            return out
        errors.append("stock_jgdy_detail_em: 空返回")
    except Exception as e:
        errors.append(f"stock_jgdy_detail_em: {type(e).__name__}")

    try:
        start = (_dt.datetime.now() - _dt.timedelta(days=days)).strftime("%Y%m%d")
        df_all = ak.stock_jgdy_tj_em(date=start)
        if df_all is not None and not df_all.empty:
            code_col = next((c for c in df_all.columns if "代码" in str(c)), None)
            if code_col:
                sub = df_all[df_all[code_col].astype(str).str.zfill(6) == str(pure_code).zfill(6)]
                if not sub.empty:
                    out.update({"df": sub, "source": "akshare stock_jgdy_tj_em（东财调研统计过滤）"})
                    return out
            errors.append("stock_jgdy_tj_em: 该标的近期无记录")
        else:
            errors.append("stock_jgdy_tj_em: 空返回")
    except Exception as e:
        errors.append(f"stock_jgdy_tj_em: {type(e).__name__}")

    out["error"] = " | ".join(errors)
    return out


# ===========================================================================
# 估值分位：股价 / PE 双口径（PE 分位仅在能拿到真实历史 EPS 时才计算）
# ===========================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def compute_valuation_percentile(ticker: str, years: int = 3) -> dict:
    """近 N 年股价分位（真实收盘序列统计），失败返回 error。"""
    out = {"price_pct": None, "low": None, "high": None, "cur": None, "error": None}
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period=f"{years}y")
        if h is None or h.empty or "Close" not in h:
            out["error"] = "历史行情接口无返回"
            return out
        closes = h["Close"].dropna()
        if len(closes) < 30:
            out["error"] = "历史样本不足 30 个交易日"
            return out
        cur = sf(closes.iloc[-1])
        out.update({
            "price_pct": sf((closes < cur).mean() * 100.0),
            "low": sf(closes.min()), "high": sf(closes.max()), "cur": cur,
        })
        return out
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
