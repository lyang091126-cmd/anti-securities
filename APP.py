from __future__ import annotations
import os
import time
import datetime
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import math
from plotly.subplots import make_subplots
from openai import OpenAI

import importlib

st.set_page_config(
    page_title="Anti Stock Report - 智能投研终端",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================================
# ▼▼▼ 内联模块：fundamentals.py  （原独立文件，V7 单文件版已合并至此）
# ============================================================================

# [V8 修复] 此处原为模块级裸 docstring，会被 Streamlit magic 当作
# st.write() 渲染到页面顶部（用户可见）；已改为注释，文档语义不变。
# fundamentals.py — V7 数据净化与深度基本面穿透引擎
# ================================================================================
# 本模块承担两大职责（战役一 + 战役二）：
#
# 战役一 · 数据源绝对净化
#   - fetch_industry_benchmark(): 同行业 PE/PB/PS 基准**动态实时拉取**
#     （美股/港股走 yfinance Industry 成分股；A 股走东财行业板块成分股），
#     绝不返回 PE=20x 这类静态写死常量。拉取失败 → 返回 None，由 UI 层
#     用 st.warning 明示"真实数据缺失"，禁止编造。
#   - fetch_institutional_holdings(): 机构持仓多接口级联降级
#     （东财十大流通股东 → 十大股东 → 股东持股明细 → yfinance 机构持仓），
#     全部失败 → 返回空结果 + 失败原因，绝不生成"张三/李四"占位数据。
#   - fetch_institution_surveys(): 机构调研记录多接口级联降级。
#
# 战役二 · 深度量化指标穿透
#   - compute_advanced_metrics(): EBITDA 利润率、经营性现金流 vs 净利润
#     含金量、杜邦三因子拆解、研发费用率、PEG 倍数。
#     全部指标带 try/except + NaN 处理，任何一项失败不影响其它指标。
#
# 所有对外函数均为纯数据函数（不含 st 渲染），仅用 st.cache_data 做缓存。

# [已内联] from __future__ import annotations

import math
import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# 语义化色彩规范（全局唯一定义，UI 层统一引用，禁止各处散落硬编码色值）
# ---------------------------------------------------------------------------
# V8 视觉规范：对齐 TradingView 深海蓝灰质感，废弃纯黑底与刺眼纯红纯绿
C_UP = "#26A69A"        # 上涨 / 资金流入 / 低估（专业沉稳绿）
C_UP_DIM = "#1E8E82"
C_DOWN = "#EF5350"      # 下跌 / 资金流出 / 高估（专业警示红）
C_DOWN_DIM = "#C0392B"
C_NEUTRAL = "#8B93A7"   # 中性 / 标签 / 说明（石板灰）
C_NEUTRAL_DIM = "#64748B"
C_ACCENT = "#2962FF"    # 强调（TradingView 品牌蓝）
C_ACCENT_SOFT = "#4B9FFF"
C_WARN = "#FF9800"
C_TEXT = "#D1D4DC"      # 正文（TradingView 文字灰白）
C_TEXT_STRONG = "#F0F3FA"
# V12 Bloomberg Edition 色彩重构：对齐彭博终端/彭博社的高对比暗黑分层。
# 关键变化：卡片底由半透明改为实色——半透明叠在深色背景上会让相邻模块
# 边界糊成一片，失去"面板"的体块感，这正是原版显得松散的主因。
C_BG_APP = "#0A0E17"    # 全局背景（深邃钛灰）
C_BG_PANEL = "#0E1420"
C_BG_CARD = "#121824"   # 卡片面板（实色，建立清晰体块边界）
C_BG_CARD_HI = "#161D2B"  # 卡片悬停/次级层
C_BORDER = "rgba(255, 255, 255, 0.08)"  # 超细边框
C_BB_ORANGE = "#FF5E00"   # 彭博标志性暖橙：重点聚焦区顶边 / 微型大写标签
C_BB_ORANGE_DIM = "rgba(255, 94, 0, 0.14)"

# ---------------------------------------------------------------------------
# V10 五·涨跌语义切换：默认 A 股口径（红涨绿跌），可切国际口径（绿涨红跌）。
# 切换控件在首屏搜索栏右侧（intl_color_mode）；此处仅重绑定常量，
# 全站所有引用 C_UP/C_DOWN 的 Plotly 图表与 HTML 渲染自动跟随，无散落硬编码。
# ---------------------------------------------------------------------------
if not st.session_state.get("intl_color_mode", False):
    C_UP, C_UP_DIM = "#EF5350", "#C0392B"      # A 股：红 = 上涨/流入/低估修复
    C_DOWN, C_DOWN_DIM = "#26A69A", "#1E8E82"  # A 股：绿 = 下跌/流出/高估回落


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


CAPEX_KEYS = ["Capital Expenditure", "CapitalExpenditure", "Capital Expenditures",
              "Purchase Of PPE", "Net PPE Purchase And Sale"]
FCF_KEYS = ["Free Cash Flow", "FreeCashFlow"]


def compute_capex_fcf(all_data: dict) -> dict:
    """V8 战役三：CAPEX / 自由现金流 / 经营性现金流（全部报表真实科目，缺失即 None）。"""
    out = {"capex": None, "fcf": None, "ocf": None, "fcf_note": None, "capex_to_ocf": None}
    try:
        qcf = (all_data or {}).get("quarterly_cashflow")
        acf = (all_data or {}).get("cashflow")
        info = (all_data or {}).get("info") or {}

        ocf, _ = _row_ttm(qcf, acf, OCF_KEYS)
        if ocf is None:
            ocf = sf(info.get("operatingCashflow"))
        out["ocf"] = ocf

        capex, _ = _row_ttm(qcf, acf, CAPEX_KEYS)
        out["capex"] = capex

        fcf, _ = _row_ttm(qcf, acf, FCF_KEYS)
        if fcf is not None:
            out["fcf"], out["fcf_note"] = fcf, "现金流量表直接披露 Free Cash Flow"
        elif ocf is not None and capex is not None:
            out["fcf"] = ocf - abs(capex)
            out["fcf_note"] = "推算：经营性现金流 - |资本支出|"
        else:
            fcf_i = sf(info.get("freeCashflow"))
            if fcf_i is not None:
                out["fcf"], out["fcf_note"] = fcf_i, "yfinance info.freeCashflow (TTM)"

        if capex is not None and ocf:
            out["capex_to_ocf"] = abs(capex) / abs(ocf)
    except Exception:
        pass
    return out


def compute_earnings_surprises(all_data: dict, n: int = 4) -> list:
    """V8 战役三：过往 N 期 EPS 预期 vs 实际（Beat/Miss），全部来自 yfinance earnings_dates。"""
    rows = []
    df = (all_data or {}).get("earnings_dates")
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return rows
    try:
        est_c = next((c for c in df.columns if "estimate" in str(c).lower()), None)
        rep_c = next((c for c in df.columns if "reported" in str(c).lower()), None)
        sur_c = next((c for c in df.columns if "surprise" in str(c).lower()), None)
        if rep_c is None:
            return rows
        d = df.dropna(subset=[rep_c]).head(n)
        for idx, r in d.iterrows():
            rep = sf(r[rep_c])
            if rep is None:
                continue
            est = sf(r[est_c]) if est_c else None
            sur = sf(r[sur_c]) if sur_c else None
            if sur is None and est not in (None, 0):
                sur = (rep - est) / abs(est) * 100.0
            elif sur is not None and abs(sur) <= 1.5 and est not in (None, 0):
                sur = sur * 100.0          # 部分口径给的是小数
            try:
                period = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            except Exception:
                period = str(idx)[:10]
            rows.append({"period": period, "est": est, "rep": rep,
                         "surprise_pct": sur,
                         "beat": (rep >= est) if est is not None else None})
    except Exception:
        return rows
    return rows


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


# ============================================================================
# ▼▼▼ 内联模块：terminal_ui.py  （原独立文件，V7 单文件版已合并至此）
# ============================================================================

# [V8 修复] 同上：裸 docstring 改注释，避免被 Streamlit magic 渲染。
# terminal_ui.py — V7 「彭博化」终端 UI 引擎
# ================================================================================
# 战役三专用模块：高密度 Grid 布局 + 暗黑专业质感 + 语义化色彩规范。
#
# 对外能力：
#   inject_terminal_css()          全局极窄边距 + 卡片化视觉系统（一次性注入）
#   render_command_center()        顶部 4×N 数据仪表盘矩阵（含估值分位迷你进度条）
#   render_kpi_grid()             通用高密度 KPI 卡片矩阵
#   build_pro_kline_chart()        专业级 K 线：多均线(含 MA120/MA250 牛熊线)+量+MACD+RSI
#   build_dupont_chart()           杜邦三因子驱动引擎瀑布/矩阵图
#   build_scenario_chart()         估值推演多情景（悲观/中性/乐观）靶心区间图
#   build_quality_bridge_chart()   经营性现金流 vs 净利润 利润含金量对比图
#
# 色彩语义（严格执行，全站唯一来源 fundamentals 常量）：
#   上涨/流入/低估 → C_UP   下跌/流出/高估 → C_DOWN   中性/标签 → C_NEUTRAL

# [已内联] from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# [已内联] from fundamentals import ( C_UP, C_UP_DIM, C_DOWN, C_DOWN_DIM, C_NEUTRAL, C_NEUTRAL_DIM, C

PLOT_BG = "rgba(0,0,0,0)"


# ===========================================================================
# 1. 全局 CSS：极窄边距 + 高密度卡片
# ===========================================================================
def inject_terminal_css():
    if st.session_state.get("_v7_css_injected"):
        return
    st.session_state["_v7_css_injected"] = True
    st.html(f"""
<style>
/* ---------- V8 全局底色：深海军蓝，彻底废弃纯黑 ---------- */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
    background: {C_BG_APP} !important;
}}
[data-testid="stHeader"] {{ background: {C_BG_APP} !important; }}
body, p, span, div, li {{ color: {C_TEXT}; }}

/* ---------- 全局空间感：极窄边距，最大化数据密度 ---------- */
.block-container {{
    padding-top: 0.85rem !important;
    padding-bottom: 1.2rem !important;
    padding-left: 1.1rem !important;
    padding-right: 1.1rem !important;
    max-width: 100% !important;
}}
header[data-testid="stHeader"] {{ height: 0; visibility: hidden; }}
footer {{ visibility: hidden; }}

/* 元素间距整体收紧，杜绝原生瀑布流松散排版 */
div[data-testid="stVerticalBlock"] {{ gap: 0.5rem !important; }}
div[data-testid="stHorizontalBlock"] {{ gap: 0.55rem !important; }}
div[data-testid="stMetric"] {{
    background: {C_BG_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 10px;
    padding: 0.6rem 0.75rem;
}}
h1, h2, h3, h4 {{ letter-spacing: -0.3px; }}
h3 {{ font-size: 1.05rem !important; margin: 0.5rem 0 0.35rem 0 !important; }}
h4 {{ font-size: 0.95rem !important; margin: 0.4rem 0 0.3rem 0 !important; }}
hr {{ margin: 0.5rem 0 !important; opacity: 0.12; }}

/* ---------- 终端卡片体系 ---------- */
.tg {{
    display: grid;
    gap: 8px;
    margin: 6px 0 10px 0;
}}
.tg-2 {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
.tg-3 {{ grid-template-columns: repeat(3, minmax(0,1fr)); }}
.tg-4 {{ grid-template-columns: repeat(4, minmax(0,1fr)); }}
.tg-auto {{ grid-template-columns: repeat(auto-fit, minmax(180px,1fr)); }}
@media (max-width: 1100px) {{
    .tg-4, .tg-3 {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
}}

.tcard {{
    background: {C_BG_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 10px;
    padding: 0.62rem 0.8rem;
    box-shadow: 0 2px 10px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.03);
    display: flex; flex-direction: column; justify-content: space-between;
    min-height: 82px;
}}
.tcard:hover {{ border-color: {C_ACCENT}; box-shadow: 0 2px 14px rgba(41,98,255,0.18); }}
.tcard-label {{
    font-size: 0.7rem; font-weight: 600; letter-spacing: 0.4px;
    color: {C_NEUTRAL}; text-transform: uppercase; margin-bottom: 4px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.tcard-value {{
    font-size: 1.22rem; font-weight: 800; color: {C_TEXT_STRONG};
    font-variant-numeric: tabular-nums; line-height: 1.15;
}}
.tcard-sub {{ font-size: 0.7rem; font-weight: 600; margin-top: 3px; color: {C_NEUTRAL}; }}
.v-up {{ color: {C_UP} !important; }}
.v-down {{ color: {C_DOWN} !important; }}
.v-neutral {{ color: {C_NEUTRAL} !important; }}
.v-accent {{ color: {C_ACCENT} !important; }}
.v-warn {{ color: {C_WARN} !important; }}

/* 迷你分位进度条 */
.mini-track {{
    position: relative; width: 100%; height: 6px; border-radius: 4px; margin-top: 8px;
    background: linear-gradient(90deg, {C_UP} 0%, {C_WARN} 55%, {C_DOWN} 100%);
    opacity: 0.85;
}}
.mini-marker {{
    position: absolute; top: -3px; width: 2px; height: 12px; background: #fff;
    box-shadow: 0 0 6px rgba(255,255,255,0.9); transform: translateX(-50%);
}}

/* 终端标题条 */
.term-bar {{
    display: flex; align-items: center; justify-content: space-between;
    background: linear-gradient(90deg, rgba(0,242,254,0.10) 0%, rgba(0,0,0,0) 70%);
    border-left: 3px solid {C_ACCENT};
    padding: 0.35rem 0.7rem; margin: 0.55rem 0 0.45rem 0; border-radius: 4px;
}}
.term-bar-title {{ font-size: 0.92rem; font-weight: 800; color: {C_TEXT}; letter-spacing: 0.3px; }}
.term-bar-note {{ font-size: 0.7rem; color: {C_NEUTRAL}; }}

.tag {{
    display: inline-block; font-size: 0.66rem; font-weight: 700; padding: 1px 7px;
    border-radius: 4px; margin-left: 5px; vertical-align: middle;
}}
.tag-real {{ background: rgba(0,230,118,0.14); color: {C_UP}; border: 1px solid rgba(0,230,118,0.35); }}
.tag-miss {{ background: rgba(139,147,167,0.14); color: {C_NEUTRAL}; border: 1px dashed rgba(139,147,167,0.45); }}

/* 表格紧凑化 */
div[data-testid="stMarkdownContainer"] table {{ width:100% !important; border-collapse: collapse !important; }}
div[data-testid="stMarkdownContainer"] th {{
    background: rgba(0,242,254,0.10) !important; color: {C_ACCENT} !important;
    font-size: 0.78rem !important; padding: 0.4rem 0.6rem !important;
}}
div[data-testid="stMarkdownContainer"] td {{ font-size: 0.8rem !important; padding: 0.35rem 0.6rem !important; }}
div[data-baseweb="tab-panel"] {{ padding-top: 0.6rem; }}

/* =====================================================================
   V11: 机构级通用数据表格 — 借鉴日报规范
   首列左对齐 / 数字列右对齐 / 等宽数字字体 / hover 高亮
====================================================================== */
.inst-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
    background: rgba(10, 15, 30, 0.5);
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.06);
    margin: 8px 0 14px 0;
}}
.inst-table th {{
    background: rgba(255,255,255,0.06);
    padding: 7px 12px;
    text-align: left;
    color: #94a3b8;
    font-weight: 600;
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}}
.inst-table th.num, .inst-table td.num {{
    text-align: right;
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
}}
.inst-table td {{
    padding: 6px 12px;
    border-bottom: 1px solid rgba(255,255,255,0.03);
    color: {C_TEXT};
    transition: background 0.15s;
}}
.inst-table tr:hover td {{
    background: rgba(0,242,254,0.04);
}}
.inst-table .rate-up {{ color: #ef4444; font-weight: 700; font-family: 'JetBrains Mono', monospace; }}
.inst-table .rate-dn {{ color: #00b865; font-weight: 700; font-family: 'JetBrains Mono', monospace; }}
.inst-table .rate-neu {{ color: #94a3b8; font-family: 'JetBrains Mono', monospace; }}
.inst-table .rate-val {{ font-family: 'JetBrains Mono', 'Consolas', monospace; font-weight: 600; color: {C_TEXT_STRONG}; }}

/* =====================================================================
   V11: 图文联动分析段落卡片 (.chart-ana)
====================================================================== */
.chart-ana {{
    background: rgba(15, 23, 42, 0.7);
    border-left: 3px solid {C_ACCENT};
    border-radius: 0 8px 8px 0;
    padding: 0.75rem 1rem;
    margin: 4px 0 12px 0;
    font-size: 0.82rem;
    line-height: 1.65;
    color: {C_TEXT};
    backdrop-filter: blur(4px);
}}
.chart-ana .ana-fact {{ color: {C_TEXT_STRONG}; font-weight: 600; }}
.chart-ana .ana-chg {{ color: {C_WARN}; font-weight: 600; }}
.chart-ana .ana-attr {{ color: {C_NEUTRAL}; }}
.chart-ana .ana-outlook {{ color: {C_ACCENT_SOFT}; font-style: italic; }}

/* =====================================================================
   V11: Shibor 利率徽章
====================================================================== */
.shibor-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin: 8px 0 14px 0;
}}
.shibor-cell {{
    background: rgba(15, 23, 42, 0.7);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 8px;
    padding: 10px 12px;
    text-align: center;
}}
.shibor-cell:hover {{ border-color: {C_ACCENT}; }}
.shibor-term {{ font-size: 0.72rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
.shibor-rate {{ font-size: 1.2rem; font-weight: 800; font-family: 'JetBrains Mono', monospace; color: {C_TEXT_STRONG}; }}
.shibor-chg {{ font-size: 0.72rem; font-weight: 700; margin-top: 3px; }}
.shibor-up {{ color: #ef4444; }}
.shibor-dn {{ color: #00b865; }}

/* =====================================================================
   V11: 利率传导说明框
====================================================================== */
.rate-relay-box {{
    background: linear-gradient(135deg, rgba(41,98,255,0.08) 0%, rgba(0,242,254,0.04) 100%);
    border: 1px solid rgba(41,98,255,0.25);
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin: 10px 0;
    font-size: 0.82rem;
    line-height: 1.7;
    color: {C_TEXT};
}}
.rate-relay-box strong {{ color: {C_ACCENT_SOFT}; }}

/* =====================================================================
   V12 Bloomberg Edition · 视觉基元
   —— 排印规范：标题紧凑重字重、行情数字等宽、标签微型大写橙。
      等宽字体是硬要求：比例字体下多行数字的小数点无法纵向对齐，
      一列报价会呈锯齿状，这是终端类界面最典型的业余感来源。
====================================================================== */
.bb-header {{
    font-weight: 800;
    letter-spacing: -0.5px;
    color: {C_TEXT_STRONG};
    font-family: 'Inter', 'Helvetica Neue', 'Segoe UI', sans-serif;
    line-height: 1.2;
}}
/* 微型大写标签（栏目名 / 时间戳 / 数据源） */
.bb-label {{
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: {C_BB_ORANGE};
}}
.bb-label-mute {{
    font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; color: {C_NEUTRAL};
}}
.bb-card {{
    background: {C_BG_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 14px 16px;
}}
/* 重点聚焦区：顶部 2px 暖橙高亮线（彭博 Lead Story 质感） */
.bb-card-lead {{ border-top: 2px solid {C_BB_ORANGE}; border-radius: 0 0 4px 4px; }}
.bb-kpi-num {{
    font-family: 'JetBrains Mono', 'Roboto Mono', 'Consolas', monospace;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: {C_TEXT_STRONG};
    letter-spacing: -0.3px;
}}
.bb-badge-live {{
    display: inline-flex; align-items: center; gap: 5px;
    background: {C_BB_ORANGE_DIM};
    border: 1px solid {C_BB_ORANGE};
    color: {C_BB_ORANGE};
    font-size: 0.64rem; font-weight: 800; text-transform: uppercase;
    letter-spacing: 0.6px; padding: 2px 8px; border-radius: 3px;
    white-space: nowrap;
}}
.bb-badge-live::before {{
    content: "●"; font-size: 0.7rem; line-height: 1;
    animation: bb-pulse 1.8s ease-in-out infinite;
}}
@keyframes bb-pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.25; }} }}
/* 快讯条目 */
.bb-news-item {{
    display: flex; gap: 10px; align-items: baseline;
    padding: 7px 0;
    border-bottom: 1px solid {C_BORDER};
    font-size: 0.84rem; line-height: 1.5; color: {C_TEXT};
}}
.bb-news-item:last-child {{ border-bottom: none; }}
.bb-news-time {{
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 0.72rem; color: {C_BB_ORANGE}; font-weight: 700;
    flex: 0 0 auto; white-space: nowrap;
}}

/* 实时快讯带（Live Ribbon） */
.bb-ribbon {{
    display: flex; align-items: stretch; gap: 0;
    background: {C_BG_CARD};
    border: 1px solid {C_BORDER};
    border-left: 3px solid {C_BB_ORANGE};
    border-radius: 4px;
    overflow: hidden;
    margin: 6px 0 10px 0;
}}
.bb-ribbon-tag {{
    display: flex; align-items: center; gap: 6px;
    background: {C_BB_ORANGE_DIM};
    padding: 8px 12px;
    font-size: 0.66rem; font-weight: 800; text-transform: uppercase;
    letter-spacing: 0.6px; color: {C_BB_ORANGE}; white-space: nowrap;
    border-right: 1px solid {C_BORDER};
}}
.bb-ribbon-body {{
    display: flex; flex-wrap: wrap; align-items: center; gap: 4px 22px;
    padding: 8px 14px; min-width: 0; flex: 1 1 auto;
}}
.bb-ribbon-item {{ font-size: 0.8rem; color: {C_TEXT}; line-height: 1.5; }}
.bb-ribbon-item .t {{
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    color: {C_BB_ORANGE}; font-weight: 700; font-size: 0.72rem; margin-right: 6px;
}}

/* 跨资产矩阵（Cross-Asset Heat Matrix） */
.bb-matrix {{ width: 100%; border-collapse: collapse; font-size: 0.84rem; }}
.bb-matrix thead th {{
    font-size: 0.66rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; color: {C_NEUTRAL};
    text-align: right; padding: 7px 12px;
    border-bottom: 1px solid {C_BORDER}; white-space: nowrap;
}}
.bb-matrix thead th:first-child {{ text-align: left; }}
.bb-matrix td {{
    padding: 9px 12px; border-bottom: 1px solid rgba(255,255,255,0.04);
    text-align: right; white-space: nowrap;
}}
.bb-matrix td:first-child {{ text-align: left; }}
.bb-matrix tr:last-child td {{ border-bottom: none; }}
.bb-matrix tr:hover td {{ background: {C_BG_CARD_HI}; }}
.bb-asset-name {{ font-weight: 700; color: {C_TEXT_STRONG}; }}
.bb-asset-sub {{ font-size: 0.68rem; color: {C_NEUTRAL}; font-weight: 400; }}
.bb-num {{
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-variant-numeric: tabular-nums; font-weight: 700; color: {C_TEXT_STRONG};
}}
.bb-na {{ color: {C_NEUTRAL_DIM}; font-size: 0.76rem; font-style: italic; }}

</style>
""")


# ===========================================================================
# 2. 卡片与网格渲染
# ===========================================================================
def _cls_for(direction):
    return {"up": "v-up", "down": "v-down", "accent": "v-accent",
            "warn": "v-warn"}.get(direction, "v-neutral")


def card_html(label, value, sub="", direction="neutral", value_direction=None,
              percentile=None):
    """单张终端卡片 HTML。

    label            指标名
    value            主数值（已格式化字符串）
    sub              副行说明（可含涨跌）
    direction        副行色彩语义：up/down/neutral/accent/warn
    value_direction  主数值色彩语义（默认白色）
    percentile       0-100，给出则渲染迷你分位进度条
    """
    v_cls = _cls_for(value_direction) if value_direction else ""
    s_cls = _cls_for(direction)
    sub_html = f'<div class="tcard-sub {s_cls}">{sub}</div>' if sub else ""
    pct_html = ""
    p = sf(percentile)
    if p is not None:
        p = max(0.0, min(100.0, p))
        pct_html = f'<div class="mini-track"><div class="mini-marker" style="left:{p:.1f}%"></div></div>'
    return (f'<div class="tcard"><div class="tcard-label">{label}</div>'
            f'<div class="tcard-value {v_cls}">{value}</div>{sub_html}{pct_html}</div>')


def render_kpi_grid(cards, cols=4):
    """cards: list[dict(label,value,sub,direction,value_direction,percentile)]"""
    inner = "".join(card_html(**c) for c in cards)
    st.html(f'<div class="tg tg-{cols}">{inner}</div>')


def section_bar(title, note=""):
    st.html(f'<div class="term-bar"><div class="term-bar-title">{title}</div>'
            f'<div class="term-bar-note">{note}</div></div>')


# ===========================================================================
# 3. 顶部核心仪表盘（The Command Center）
# ===========================================================================
def render_command_center(name, ticker, info, hist, percentile_info=None, adv=None):
    """1 秒读盘：价格/涨跌、日内高低、成交额、换手率、股息率、估值分位等 4×N 矩阵。

    所有数值均来自真实抓取结果；缺失一律显示「数据缺失」，绝不填充假值。
    """
    info = info or {}
    cur = sf(info.get("currentPrice")) or sf(info.get("regularMarketPrice"))
    prev = sf(info.get("previousClose")) or sf(info.get("regularMarketPreviousClose"))
    if cur is None and hist is not None and not hist.empty:
        cur = sf(hist["Close"].iloc[-1])
    if prev is None and hist is not None and len(hist) >= 2:
        prev = sf(hist["Close"].iloc[-2])

    ccy = info.get("currency") or ""
    chg = (cur - prev) / prev * 100 if (cur and prev) else None
    day_hi = sf(info.get("dayHigh")) or sf(info.get("regularMarketDayHigh"))
    day_lo = sf(info.get("dayLow")) or sf(info.get("regularMarketDayLow"))
    if (day_hi is None or day_lo is None) and hist is not None and not hist.empty:
        day_hi = day_hi or sf(hist["High"].iloc[-1])
        day_lo = day_lo or sf(hist["Low"].iloc[-1])

    vol = sf(info.get("volume")) or sf(info.get("regularMarketVolume"))
    if vol is None and hist is not None and not hist.empty and "Volume" in hist:
        vol = sf(hist["Volume"].iloc[-1])
    turnover = vol * cur if (vol and cur) else None
    float_sh = sf(info.get("floatShares")) or sf(info.get("sharesOutstanding"))
    turnover_rate = (vol / float_sh * 100) if (vol and float_sh) else None

    div_y = sf(info.get("dividendYield"))
    if div_y is not None and div_y > 1:      # yfinance 部分标的直接给百分数
        div_y = div_y / 100.0
    mcap = sf(info.get("marketCap"))
    pe = sf(info.get("trailingPE")) or sf(info.get("forwardPE"))
    pb = sf(info.get("priceToBook"))
    wk_hi, wk_lo = sf(info.get("fiftyTwoWeekHigh")), sf(info.get("fiftyTwoWeekLow"))
    wk_pos = ((cur - wk_lo) / (wk_hi - wk_lo) * 100) if (cur and wk_hi and wk_lo and wk_hi > wk_lo) else None
    p_pct = (percentile_info or {}).get("price_pct")

    def money(v):
        if v is None:
            return "数据缺失"
        a = abs(v)
        if a >= 1e12:
            return f"{v/1e12:.2f}T"
        if a >= 1e8:
            return f"{v/1e8:.2f}亿"
        if a >= 1e4:
            return f"{v/1e4:.2f}万"
        return f"{v:,.0f}"

    d = "up" if (chg or 0) >= 0 else "down"
    cards = [
        dict(label="最新价 / 日内涨跌", value=(f"{cur:,.2f} {ccy}" if cur else "数据缺失"),
             sub=(f"{chg:+.2f}%  (前收 {prev:,.2f})" if chg is not None else "涨跌数据缺失"),
             direction=d, value_direction=d),
        dict(label="日内高 / 低", value=(f"{day_hi:,.2f} / {day_lo:,.2f}" if (day_hi and day_lo) else "数据缺失"),
             sub=(f"振幅 {(day_hi-day_lo)/prev*100:.2f}%" if (day_hi and day_lo and prev) else "振幅数据缺失")),
        dict(label="成交额 / 成交量", value=money(turnover),
             sub=(f"量 {money(vol)} 股" if vol else "成交量缺失")),
        dict(label="换手率", value=(f"{turnover_rate:.2f}%" if turnover_rate is not None else "数据缺失"),
             sub=("按流通股本口径" if turnover_rate is not None else "流通股本缺失"),
             value_direction="accent" if turnover_rate else None),
        dict(label="总市值", value=money(mcap), sub=(ccy or "")),
        dict(label="PE (TTM) / PB", value=(f"{pe:.2f}" if pe else "数据缺失"),
             sub=(f"PB {pb:.2f}" if pb else "PB 数据缺失")),
        dict(label="股息率", value=(f"{div_y*100:.2f}%" if div_y else "未派息/数据缺失"),
             sub=("年化 TTM 口径" if div_y else "接口未披露"),
             value_direction="up" if div_y else None),
        dict(label="52 周区间位置", value=(f"{wk_pos:.0f}%" if wk_pos is not None else "数据缺失"),
             sub=(f"{wk_lo:,.2f} ~ {wk_hi:,.2f}" if (wk_hi and wk_lo) else "52 周高低缺失"),
             percentile=wk_pos),
        dict(label="近 3 年股价分位", value=(f"{p_pct:.0f}%" if p_pct is not None else "数据缺失"),
             sub=("客观统计分位，非估值判断" if p_pct is not None else
                  (percentile_info or {}).get("error") or "历史数据缺失"),
             percentile=p_pct),
    ]

    adv = adv or {}
    cards += [
        dict(label="EBITDA 利润率",
             value=(f"{adv.get('ebitda_margin')*100:.2f}%" if adv.get("ebitda_margin") is not None else "数据缺失"),
             sub=adv.get("ebitda_note") or "报表未披露 EBITDA",
             value_direction="accent" if adv.get("ebitda_margin") else None),
        dict(label="现金流 / 净利润",
             value=(f"{adv.get('ocf_to_ni'):.2f}x" if adv.get("ocf_to_ni") is not None else "数据缺失"),
             sub=adv.get("earnings_quality_label") or "现金流或净利润缺失",
             direction=("up" if (adv.get("ocf_to_ni") or 0) >= 1 else "down") if adv.get("ocf_to_ni") else "neutral",
             value_direction=("up" if (adv.get("ocf_to_ni") or 0) >= 1 else "down") if adv.get("ocf_to_ni") else None),
        dict(label="PEG (PE / 增速)",
             value=(f"{adv.get('peg'):.2f}" if adv.get("peg") is not None else "数据缺失"),
             sub=(adv.get("peg_source") or "一致预期增速缺失"),
             direction=("up" if (adv.get("peg") or 99) < 1 else "down") if adv.get("peg") else "neutral",
             value_direction=("up" if (adv.get("peg") or 99) < 1 else "down") if adv.get("peg") else None),
    ]
    render_kpi_grid(cards, cols=4)


# ===========================================================================
# 4. 专业级 K 线图（多均线 + 量 + MACD + RSI）
# ===========================================================================
def build_pro_kline_chart(df, ticker, height=640):
    """TradingView 级别多指标同屏：K线+MA5/20/60/120/250、成交量、MACD、RSI。"""
    d = df.copy()
    for w in (5, 20, 60, 120, 250):
        if len(d) >= max(2, w // 3):
            d[f"MA{w}"] = d["Close"].rolling(w, min_periods=max(2, w // 3)).mean()

    e12 = d["Close"].ewm(span=12, adjust=False).mean()
    e26 = d["Close"].ewm(span=26, adjust=False).mean()
    dif = e12 - e26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_hist = dif - dea

    delta = d["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.015,
                        row_heights=[0.52, 0.14, 0.17, 0.17])

    fig.add_trace(go.Candlestick(
        x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        name="K线", increasing_line_color=C_UP, increasing_fillcolor=C_UP,
        decreasing_line_color=C_DOWN, decreasing_fillcolor=C_DOWN, line_width=1,
    ), row=1, col=1)

    ma_style = {"MA5": (C_WARN, 1), "MA20": (C_ACCENT, 1), "MA60": ("#A855F7", 1.2),
                "MA120": ("#F472B6", 1.6), "MA250": ("#FFFFFF", 1.8)}
    for k, (color, w) in ma_style.items():
        if k in d:
            label = k + (" 牛熊分界" if k in ("MA120", "MA250") else "")
            fig.add_trace(go.Scatter(x=d.index, y=d[k], name=label,
                                     line=dict(color=color, width=w),
                                     hovertemplate=f"{k}: %{{y:.2f}}<extra></extra>"), row=1, col=1)

    vol_colors = [C_UP if c >= o else C_DOWN for c, o in zip(d["Close"], d["Open"])]
    if "Volume" in d:
        fig.add_trace(go.Bar(x=d.index, y=d["Volume"], marker_color=vol_colors,
                             opacity=0.55, name="成交量"), row=2, col=1)

    fig.add_trace(go.Bar(x=d.index, y=macd_hist, name="MACD 柱",
                         marker_color=[C_UP if v >= 0 else C_DOWN for v in macd_hist],
                         opacity=0.7), row=3, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=dif, name="DIF", line=dict(color=C_ACCENT, width=1)), row=3, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=dea, name="DEA", line=dict(color=C_WARN, width=1)), row=3, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=rsi, name="RSI(14)",
                             line=dict(color="#A855F7", width=1.2)), row=4, col=1)
    fig.add_hline(y=70, line=dict(color=C_DOWN, width=0.8, dash="dot"), row=4, col=1)
    fig.add_hline(y=30, line=dict(color=C_UP, width=0.8, dash="dot"), row=4, col=1)

    fig.update_layout(
        height=height, template="plotly_dark", xaxis_rangeslider_visible=False,
        # V9 P3：顶部 60px 给标题呼吸空间；底部 40px 容纳下移的图例
        margin=dict(l=8, r=8, t=60, b=40), paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
        hovermode="x unified", bargap=0.05,
        # V9 P3：图例从顶部(y=1.06, 与标题/副图标题重叠)移到图表正下方
        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5,
                    font=dict(size=9), bgcolor="rgba(0,0,0,0)"),
        title=dict(text=f"{ticker} · 多周期均线 / 量能 / MACD / RSI 同屏", font=dict(size=12), x=0.01),
    )
    for r, lab in [(1, "价格"), (2, "量"), (3, "MACD"), (4, "RSI")]:
        fig.update_yaxes(title_text=lab, title_font=dict(size=9), gridcolor="rgba(255,255,255,0.05)",
                         zeroline=False, row=r, col=1)
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.04)", rangeslider_visible=False)
    return fig


# ===========================================================================
# 5. 杜邦分析驱动引擎图
# ===========================================================================
def build_dupont_chart(adv, height=300):
    """ROE = 净利率 × 总资产周转率 × 权益乘数 三因子驱动矩阵。"""
    nm = adv.get("net_margin")
    at = adv.get("asset_turnover")
    em = adv.get("equity_multiplier")
    roe = adv.get("roe_dupont") or adv.get("roe_reported")
    if nm is None or at is None or em is None:
        return None

    labels = ["净利率 (Net Margin)", "总资产周转率 (Asset Turnover)", "权益乘数 (Leverage)"]
    display = [f"{nm*100:.2f}%", f"{at:.2f}x", f"{em:.2f}x"]
    # 归一化为「相对贡献视觉刻度」：用各因子相对典型值的比例，避免量纲混淆
    norm = [min(max(nm / 0.15, 0.05), 3.0), min(max(at / 0.8, 0.05), 3.0), min(max(em / 2.0, 0.05), 3.0)]
    colors = [C_UP if v >= 1 else C_WARN if v >= 0.6 else C_DOWN for v in norm]

    fig = go.Figure(go.Bar(
        x=norm, y=labels, orientation="h", marker_color=colors,
        text=[f"{d}" for d in display], textposition="outside",
        textfont=dict(size=12, color=C_TEXT),
        hovertemplate="%{y}<br>实际值 %{text}<extra></extra>",
    ))
    fig.update_layout(
        height=height, template="plotly_dark", margin=dict(l=8, r=60, t=34, b=8),
        paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG, showlegend=False,
        title=dict(text=(f"杜邦拆解 · ROE ≈ {roe*100:.2f}%" if roe else "杜邦三因子拆解"),
                   font=dict(size=12), x=0.01),
        xaxis=dict(title="相对强度（1.0 = 行业常见典型水平基准刻度）",
                   title_font=dict(size=9), gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(tickfont=dict(size=10)),
    )
    fig.add_vline(x=1.0, line=dict(color=C_NEUTRAL, width=1, dash="dash"))
    return apply_institutional_axes(fig)


# ===========================================================================
# 6. 利润含金量桥图（OCF vs 净利润）
# ===========================================================================
def build_quality_bridge_chart(adv, height=280):
    ocf, ni = adv.get("ocf"), adv.get("net_income")
    if ocf is None or ni is None:
        return None
    gap = ocf - ni
    fig = go.Figure()
    fig.add_trace(go.Bar(x=["净利润 (Net Income)", "经营性现金流 (OCF)"], y=[ni, ocf],
                         marker_color=[C_NEUTRAL_DIM, C_UP if ocf >= ni else C_DOWN],
                         text=[f"{ni/1e8:,.2f}亿", f"{ocf/1e8:,.2f}亿"],
                         textposition="outside", textfont=dict(size=11), name="金额"))
    fig.update_layout(
        height=height, template="plotly_dark", margin=dict(l=8, r=8, t=34, b=8),
        paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG, showlegend=False,
        title=dict(text=(f"利润含金量 · 现金流-净利润差额 {gap/1e8:+.2f}亿 "
                         f"({(ocf/abs(ni)):.2f}x)" if ni else "利润含金量"),
                   font=dict(size=12), x=0.01),
        yaxis=dict(title="金额（原始币种）", title_font=dict(size=9),
                   gridcolor="rgba(255,255,255,0.05)"),
    )
    return apply_institutional_axes(fig)


# ===========================================================================
# 7. 估值推演多情景靶心图
# ===========================================================================
def build_scenario_chart(current_price, scenarios, price_label="", height=330):
    """scenarios: list[(情景名, 目标价, 说明)]，按悲观→中性→乐观排序。"""
    rows = [(n, sf(p), note) for n, p, note in scenarios if sf(p)]
    if not rows or not sf(current_price):
        return None
    cur = sf(current_price)
    names = [r[0] for r in rows]
    prices = [r[1] for r in rows]
    upside = [(p - cur) / cur * 100 for p in prices]
    colors = [C_UP if u >= 0 else C_DOWN for u in upside]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=prices, y=names, orientation="h", marker_color=colors, opacity=0.85,
        text=[f"{price_label}{p:,.2f}  ({u:+.1f}%)" for p, u in zip(prices, upside)],
        textposition="outside", textfont=dict(size=11, color=C_TEXT),
        customdata=[r[2] for r in rows],
        hovertemplate="%{y}<br>推演价 %{x:.2f}<br>%{customdata}<extra></extra>",
        name="情景推演价",
    ))
    fig.add_vline(x=cur, line=dict(color="#FFFFFF", width=1.6, dash="dash"),
                  annotation_text=f"现价 {price_label}{cur:,.2f}",
                  annotation_position="top", annotation_font=dict(size=10, color=C_TEXT))
    fig.update_layout(
        height=height, template="plotly_dark", margin=dict(l=8, r=110, t=34, b=8),
        paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG, showlegend=False,
        title=dict(text="多情景相对估值推演（悲观 / 中性 / 乐观）", font=dict(size=12), x=0.01),
        xaxis=dict(title="推演合理股价", title_font=dict(size=9),
                   gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(tickfont=dict(size=10)),
    )
    return apply_institutional_axes(fig)


# ===========================================================================
# 8. V8：EPS 盈利惊喜（Beat/Miss）柱状图 —— 用于填补右侧物理空白
# ===========================================================================
def apply_institutional_axes(fig):
    """V10 P10：机构级坐标轴基准线——所有柱状/折线图统一 X 轴边框与零线，
    对齐 Bloomberg/Wind 的严谨观感。饼图/雷达图等无坐标轴图表不适用。

    V12：图例位置在此统一收口。此前各图各自设定（y=-0.12 / 默认右侧悬浮 等），
    右侧悬浮图例会压住绘图区最右侧的数据点，是标签重叠的主要来源。
    本函数在各图 update_layout 之后调用，故此处设定为最终生效值。
    """
    try:
        fig.update_xaxes(showline=True, linewidth=1.5,
                         linecolor='rgba(255, 255, 255, 0.4)', mirror=True,
                         zeroline=True, zerolinewidth=1.5,
                         zerolinecolor='rgba(255, 255, 255, 0.5)')
    except Exception:
        pass
    try:
        fig.update_layout(
            legend=dict(orientation="h", y=-0.15, x=0.5,
                        xanchor="center", yanchor="top",
                        font=dict(size=10), bgcolor="rgba(0,0,0,0)"),
            margin=dict(b=64),
        )
    except Exception:
        pass
    return fig


def build_eps_surprise_chart(rows, height=300, is_usd=False):
    """过往各期 EPS 预期 vs 实际对比；超预期=沉稳绿，不及预期=警示红。"""
    rows = [r for r in (rows or []) if r.get("rep") is not None]
    if not rows:
        return None
    rows = list(reversed(rows))              # 时间正序
    periods = [r["period"] for r in rows]
    est = [r.get("est") for r in rows]
    rep = [r.get("rep") for r in rows]
    colors = [C_UP if (r.get("beat") is not False) else C_DOWN for r in rows]

    fig = go.Figure()
    if any(v is not None for v in est):
        fig.add_trace(go.Bar(x=periods, y=est, name="分析师预期 EPS",
                             marker_color=C_NEUTRAL_DIM, opacity=0.75,
                             hovertemplate="预期 %{y:.3f}<extra></extra>"))
    fig.add_trace(go.Bar(x=periods, y=rep, name="实际公布 EPS",
                         marker_color=colors,
                         text=[(f"{r['surprise_pct']:+.1f}%" if r.get("surprise_pct") is not None else "")
                               for r in rows],
                         textposition="outside", textfont=dict(size=10),
                         hovertemplate="实际 %{y:.3f}<extra></extra>"))
    fig.update_layout(
        height=height, template="plotly_dark", barmode="group",
        # P5：修复柱状图极度挤压和左侧留白，紧凑四周留白
        margin=dict(t=30, b=50, l=40, r=20), paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0,
                    font=dict(size=10)),
        yaxis=dict(title="EPS (元/股)" if not is_usd else "EPS ($)", title_font=dict(size=10), gridcolor="rgba(255,255,255,0.08)"),
        # P5：强制分类轴，消除空月份间隔
        xaxis=dict(type="category", tickfont=dict(size=10), tickangle=-20),
        bargap=0.3, bargroupgap=0.1
    )
    return apply_institutional_axes(fig)


def render_gap_bars(pairs):
    """V8：估值水位差横向进度条。pairs = [(名称, 本标的倍数, 同业中位)]。

    以同业中位数为中轴（50% 位置），向右为溢价(红)、向左为折价(绿)，
    ±100% 折溢价对应满格，纯客观倍数比较，不含任何买卖判断。
    """
    rows_html = []
    for name, cur, ref in pairs:
        cur_v, ref_v = sf(cur), sf(ref)
        if cur_v is None or not ref_v:
            rows_html.append(
                f'<div class="gapbar-row"><div class="gapbar-label">{name}</div>'
                f'<div class="gapbar-track"><div class="gapbar-mid"></div></div>'
                f'<div class="gapbar-val" style="color:{C_NEUTRAL}">真实数据缺失</div></div>')
            continue
        gap = (cur_v - ref_v) / ref_v * 100.0
        span = min(abs(gap), 100.0) / 2.0            # 半幅最大 50%
        if gap >= 0:
            style = f"left:50%; width:{span:.1f}%; background:{C_DOWN};"
            color, txt = C_DOWN, f"溢价 {gap:+.1f}%"
        else:
            style = f"right:50%; width:{span:.1f}%; background:{C_UP};"
            color, txt = C_UP, f"折价 {gap:+.1f}%"
        rows_html.append(
            f'<div class="gapbar-row"><div class="gapbar-label">{name}</div>'
            f'<div class="gapbar-track"><div class="gapbar-fill" style="{style}"></div>'
            f'<div class="gapbar-mid"></div></div>'
            f'<div class="gapbar-val" style="color:{color}">{txt}'
            f'<span style="color:{C_NEUTRAL}; font-weight:600;"> ({cur_v:.2f}x vs {ref_v:.2f}x)</span>'
            f'</div></div>')
    st.html('<div class="gapbar-wrap">' + "".join(rows_html) + '</div>')


# ============================================================================
# ▼▼▼ 内联模块：macro_capital.py  （原独立文件，V7 单文件版已合并至此）
# ============================================================================

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import akshare as ak
# ⚠️ V8 战役一：此处原为 `from datetime import datetime, timedelta`，会与本文件后段
# market_tape 的 `import datetime` 互相覆盖（后者把 datetime 重新绑定为模块），
# 导致 datetime.now() 抛 "module 'datetime' has no attribute 'now'"。
# 现全文统一为「模块式」绑定，所有调用一律写全 datetime.datetime.* / datetime.timedelta。
import datetime
import concurrent.futures
import requests
import plotly.graph_objects as go

@st.cache_data(ttl=60, show_spinner=False)
def fetch_national_team_etfs():
    """Fetch real-time data for key broad-based ETFs commonly bought by the National Team"""
    etfs = {
        '510300.SS': '华泰柏瑞沪深300', '510050.SS': '华夏上证50',
        '510500.SS': '南方中证500', '159915.SZ': '易方达创业板',
        '159845.SZ': '华夏中证1000', '512890.SS': '华泰红利',
        '510310.SS': '易方达沪深300', '159919.SZ': '嘉实沪深300',
        '510330.SS': '华夏沪深300', '588000.SS': '华夏科创50',
        '588090.SS': '易方达科创50', '159949.SZ': '华夏创业板50',
        '512100.SS': '南方中证1000', '159852.SZ': '广发中证1000',
        '512000.SS': '华宝券商ETF', '512800.SS': '华宝银行ETF'
    }
    
    # 优先使用 akshare 获取实时行情 (EM 接口)
    ak_data = {}
    try:
        df_spot = ak.fund_etf_spot_em()
        if df_spot is not None and not df_spot.empty:
            for _, row in df_spot.iterrows():
                code = str(row.get('代码', ''))
                if code:
                    ak_data[code] = {
                        'current_price': float(row.get('最新价', 0)) if row.get('最新价') is not None else 0.0,
                        'chg_pct': float(row.get('涨跌幅', 0)) if row.get('涨跌幅') is not None else 0.0,
                        'turnover_100m': float(row.get('成交额', 0)) / 1e8 if row.get('成交额') else 0.0
                    }
    except Exception:
        pass

    def get_etf(tk, name):
        code = tk.split('.')[0]
        current_price = None
        chg_pct = None
        turnover_100m = None

        # 优先从 akshare 提取
        if code in ak_data:
            current_price = ak_data[code]['current_price']
            chg_pct = ak_data[code]['chg_pct']
            turnover_100m = ak_data[code]['turnover_100m']

        # 如果 akshare 数据缺失，或者为0/NaN，降级使用 yfinance
        if current_price is None or pd.isna(current_price) or current_price == 0:
            try:
                t = yf.Ticker(tk)
                hist = t.history(period='5d')
                if len(hist) >= 1:
                    current_price = float(hist['Close'].iloc[-1])
                    if len(hist) >= 2:
                        prev_close = float(hist['Close'].iloc[-2])
                        chg_pct = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0.0
                    else:
                        chg_pct = 0.0
                    volume = float(hist['Volume'].iloc[-1])
                    turnover_100m = (current_price * volume) / 1e8
            except Exception:
                pass

        if current_price is not None and not pd.isna(current_price):
            # 获取主力净流入 (通过东财接口)
            secid = f"1.{code}" if tk.endswith('.SS') else f"0.{code}"
            url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f137"
            net_inflow_100m = 0.0
            try:
                r = requests.get(url, timeout=2).json()
                if r and 'data' in r and r['data']:
                    f137 = r['data'].get('f137')
                    if f137 and f137 != '-':
                        net_inflow_100m = float(f137) / 100000000.0
            except Exception:
                pass

            return {
                '代码': tk,
                '名称': name,
                '当前价': current_price,
                '涨跌幅': chg_pct if chg_pct is not None else 0.0,
                '成交额(亿元)': turnover_100m if turnover_100m is not None else 0.0,
                '主力净流入(亿元)': net_inflow_100m
            }
        return None

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(get_etf, tk, name): tk for tk, name in etfs.items()}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                results.append(res)
            
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values(by='成交额(亿元)', ascending=False)
    return df

def _fetch_with_timeout(fn, args=(), kwargs=None, timeout_s: int = 25, default=None):
    """V8 修复：akshare 等外部接口的裸 HTTP 请求没有超时，周末/接口维护时
    会无限挂起，把整页后半部分（Treemap/CFFEX/众包/研报区）全部堵死。
    用工作线程 + 硬超时兜底：超时即返回 default，页面继续渲染。
    注意：本函数绝不能加 @st.cache_data——fn 参数是函数对象，不可哈希。"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
    # 注意：不能用 with 语句——退出时会 shutdown(wait=True) 等待挂死线程，
    # 等于没超时。必须 shutdown(wait=False) 立即返回，卡死的线程留在后台。
    _pool = ThreadPoolExecutor(max_workers=1)
    _fut = _pool.submit(fn, *args, **(kwargs or {}))
    try:
        _r = _fut.result(timeout=timeout_s)
        _pool.shutdown(wait=False)
        return _r
    except _FutTimeout:
        _fut.cancel()
        _pool.shutdown(wait=False)
        return default


@st.cache_data(ttl=120, show_spinner=False)
def fetch_sector_fund_flow():
    """Fetch real-time sector fund flow from akshare"""
    # 优先采用官方 JSON 数据接口，防网页 DOM 变化导致 HTML 解析崩溃 (P2 & P1)
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日")
        if df is not None and not df.empty:
            df = df.rename(columns={
                '名称': '行业',
                '今日主力净流入-净额': '净流入(亿元)',
                '今日涨跌幅': '涨跌幅',
            })
            if '净流入(亿元)' in df.columns:
                df['净流入(亿元)'] = df['净流入(亿元)'].apply(lambda x: round(float(x) / 1e8, 2) if pd.notnull(x) else 0.0)
            else:
                net_col = [c for c in df.columns if '主力净流入-净额' in c or '净流入' in c]
                if net_col:
                    df['净流入(亿元)'] = df[net_col[0]].apply(lambda x: round(float(x) / 1e8, 2) if pd.notnull(x) else 0.0)
                else:
                    df['净流入(亿元)'] = 0.0
            
            chg_col = [c for c in df.columns if '涨跌幅' in c or '涨跌' in c]
            if chg_col:
                df['涨跌幅'] = df[chg_col[0]].apply(lambda x: round(float(str(x).replace('%', '').strip()), 2) if (pd.notnull(x) and str(x).strip() != '?') else 0.0)
            else:
                df['涨跌幅'] = 0.0

            df['绝对净流入'] = df['净流入(亿元)'].abs()
            df['领涨股'] = df.get('今日领涨股票', 'N/A')
            return df
    except Exception:
        pass

    # 备用降级逻辑 1
    try:
        df = ak.stock_fund_flow_industry(symbol='即时')
        def parse_amount(val):
            if isinstance(val, str):
                val = val.replace('亿', '').replace('万', '').strip()
                try: return float(val)
                except: return 0.0
            return float(val) if pd.notnull(val) else 0.0
        if df is not None and not df.empty:
            if '净额' in df.columns:
                df['净流入(亿元)'] = df['净额'].apply(parse_amount)
                df['净流入(亿元)'] = df['净流入(亿元)'].apply(lambda x: round(float(x), 2) if pd.notnull(x) else 0.0)
                df['绝对净流入'] = df['净流入(亿元)'].abs()
            else:
                df['净流入(亿元)'] = 0.0
                df['绝对净流入'] = 0.0
                
            if '行业-涨跌幅' in df.columns:
                df['涨跌幅'] = df['行业-涨跌幅'].astype(str).str.replace('%', '').str.strip()
                df['涨跌幅'] = df['涨跌幅'].apply(lambda x: round(float(x), 2) if (pd.notnull(x) and x != '?' and x != 'nan' and x != '') else 0.0)
            else:
                df['涨跌幅'] = 0.0
            return df
    except Exception:
        pass

    return pd.DataFrame()

def render_macro_capital_board():
    with st.expander("🌊 宏观资金面监控室 (Macro Capital Flows)", expanded=True):
        st.markdown("### 📊 核心宽基 ETF 资金异动监控")
        st.caption("实时监控核心宽基 ETF 成交额异常放大，捕捉主力/神秘资金大单进场与护盘交易信号。")
        
        df_etf = fetch_national_team_etfs()
        if not df_etf.empty:
            # Top metrics for the top 5 ETFs by Turnover
            top5 = df_etf.sort_values(by='成交额(亿元)', ascending=False).head(5)
            cols = st.columns(len(top5))
            for i, row in top5.reset_index().iterrows():
                with cols[i]:
                    chg = row['涨跌幅']
                    # V8：原代码列名漏写右括号（'成交额(亿元'），恒为 False 走兜底；已修正
                    turnover = row.get('成交额(亿元)') or 0.0
                    alert = "🔥 异动爆量" if turnover > 30 else ""
                    
                    st.metric(
                        label=f"{row['名称']} {alert}",
                        value=f"{turnover:.2f} 亿",
                        delta=f"{chg:.2f}%",
                        delta_color="normal"
                    )
            
            st.markdown('<div class="spacer-sm"></div>', unsafe_allow_html=True)
            
            # P6: 柱状图逻辑彻底改回以“成交额 (亿元)”为轴进行排行，恢复高可读性
            metric_x = '成交额(亿元)'
            title_suffix = "成交额"
            hover_data = {
                '成交额(亿元)': ':.2f',
                '涨跌幅': ':.2f',
                '名称': False,
                '颜色': False
            }
            custom_data = ['涨跌幅', '当前价', '成交额(亿元)']

            # 强制转换为浮点数值，防字符串字典排序错误
            df_etf[metric_x] = pd.to_numeric(df_etf[metric_x], errors='coerce').fillna(0.0)
            df_etf_sorted = df_etf.sort_values(by=metric_x, ascending=True) # Ascending for horizontal bar
            if '涨跌幅' in df_etf_sorted.columns:
                df_etf_sorted['颜色'] = df_etf_sorted['涨跌幅'].apply(lambda x: '#ef4444' if pd.notnull(x) and x >= 0 else '#00b865')
            else:
                df_etf_sorted['颜色'] = df_etf_sorted[metric_x].apply(lambda x: '#ef4444' if x > 0 else '#00b865')
            
            fig_etf = px.bar(
                df_etf_sorted,
                x=metric_x,
                y='名称',
                orientation='h',
                color='颜色',
                color_discrete_map='identity',
                title=f"📈 核心宽基 ETF {title_suffix} 排行 (亿元)",
                hover_data=hover_data,
                custom_data=custom_data
            )
            
            fig_etf.update_traces(
                hovertemplate="<b>%{y}</b><br>总成交额: %{customdata[2]:.2f}亿<br>涨跌幅: %{customdata[0]:.2f}%<br>现价: %{customdata[1]:.3f}<extra></extra>"
            )
                
            fig_etf.update_layout(
                margin=dict(t=40, l=10, r=10, b=10),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=450,
                showlegend=False,
                xaxis_title=f"{title_suffix} (亿元)",
                yaxis_title="",
                xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                yaxis=dict(categoryorder='array', categoryarray=df_etf_sorted['名称'].tolist()),
                bargap=0.2
            )
            st.plotly_chart(apply_institutional_axes(fig_etf), width="stretch", key="macro_etf_barchart")
            
        else:
            st.warning("暂无 ETF 数据")
            
        # P6: 新增：过往 30 天主力资金净流入/流出趋势图
        st.markdown("---")
        st.markdown("### 📊 核心宽基 ETF 近 30 日主力资金流向趋势")
        st.caption("基于每日成交额与价格涨跌幅权重估算的主力资金流入/流出趋势。")
        
        etf_choice = st.selectbox("选择要查看趋势的 ETF", ["510300.SS (华泰柏瑞沪深300 ETF)", "588000.SS (华夏科创50 ETF)"])
        etf_tk = etf_choice.split(" ")[0]
        
        try:
            # P1: 强防时间倒退 Bug - 明确限制起止日期并提供 fallback 数据获取机制
            t_etf = yf.Ticker(etf_tk)
            end_date_trend = datetime.datetime.now()
            start_date_trend = end_date_trend - datetime.timedelta(days=45)
            
            # 优先使用 start/end 精准范围拉取 yfinance 数据
            hist_etf = t_etf.history(start=start_date_trend.strftime('%Y-%m-%d'), end=end_date_trend.strftime('%Y-%m-%d'))
            
            # 立即校验最后一条数据的年份，防严重滞后或滞留旧数据
            if not hist_etf.empty:
                last_year = pd.to_datetime(hist_etf.index[-1]).year
                if last_year < 2026:
                    hist_etf = pd.DataFrame()
            
            # 校验：若返回空或索引数据不合理，则降级到更稳定的 A股 ETF 接口
            if hist_etf.empty:
                try:
                    df_ak = ak.fund_etf_hist_em(
                        symbol=etf_tk.split('.')[0],
                        period="daily",
                        start_date=start_date_trend.strftime('%Y%m%d'),
                        end_date=end_date_trend.strftime('%Y%m%d'),
                        adjust="qfq"
                    )
                    if df_ak is not None and not df_ak.empty:
                        df_ak['Date'] = pd.to_datetime(df_ak['日期'])
                        df_ak.set_index('Date', inplace=True)
                        hist_etf = pd.DataFrame({
                            'Close': df_ak['收盘'].astype(float),
                            'Volume': df_ak['成交量'].astype(float)
                        })
                        
                        # 再次校验最后一条数据的年份
                        if not hist_etf.empty:
                            last_year = pd.to_datetime(hist_etf.index[-1]).year
                            if last_year < 2026:
                                hist_etf = pd.DataFrame()
                except Exception:
                    hist_etf = pd.DataFrame()
            
            # 终极数据隔离校验：强制只保留 2026 年以后的今日有效数据，彻底隔离 2008 历史倒退数据
            if not hist_etf.empty:
                hist_etf.index = pd.to_datetime(hist_etf.index).tz_localize(None)
                cutoff_date = datetime.datetime(2026, 1, 1)
                hist_etf = hist_etf[hist_etf.index >= cutoff_date]

            if not hist_etf.empty and len(hist_etf) >= 2:
                hist_etf['Prev_Close'] = hist_etf['Close'].shift(1)
                hist_etf['chg_pct'] = (hist_etf['Close'] - hist_etf['Prev_Close']) / hist_etf['Prev_Close']
                hist_etf['turnover'] = hist_etf['Close'] * hist_etf['Volume'] / 1e8
                
                # 资金流向粗略估算算法
                hist_etf['net_flow'] = hist_etf['turnover'] * hist_etf['chg_pct'] * 4.0
                hist_etf['net_flow'] = hist_etf.apply(lambda r: np.clip(r['net_flow'], -0.2 * r['turnover'], 0.2 * r['turnover']), axis=1)
                hist_etf = hist_etf.dropna().tail(30)
                
                df_trend = pd.DataFrame({
                    '日期': [d.strftime('%Y-%m-%d') for d in hist_etf.index],
                    '净流入(亿元)': hist_etf['net_flow'].values
                })
                
                # 水平线上方红色，水平线下方绿色
                colors_trend = ['#ef4444' if val >= 0 else '#00b865' for val in df_trend['净流入(亿元)']]
                
                fig_trend = go.Figure(go.Bar(
                    x=df_trend['日期'],
                    y=df_trend['净流入(亿元)'],
                    marker_color=colors_trend,
                    name="估算主力净流入"
                ))
                
                fig_trend.update_layout(
                    height=280,
                    margin=dict(l=10, r=10, t=30, b=10),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    template='plotly_dark',
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', type='category'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)', title="净额 (亿元)")
                )
                
                st.plotly_chart(apply_institutional_axes(fig_trend), width="stretch", key=f"flow_trend_{etf_tk}")
            else:
                st.info("暂无足够的历史日线数据来估算资金流趋势。")
        except Exception as e:
            st.info(f"资金流量趋势计算暂缓: {e}")

        st.markdown("---")
        st.markdown("### 🗺️ 全市场行业主力资金净流入热力图 (Treemap)")
        st.caption("方块大小代表资金活跃度(净额绝对值)，红色代表净流入，绿色代表净流出。点击可下钻或悬停查看详情。")
        
        # V8 修复：加 25s 硬超时，防止同花顺接口周末无响应时整页挂死
        df_sector = _fetch_with_timeout(fetch_sector_fund_flow, timeout_s=25, default=pd.DataFrame())
        if not df_sector.empty and '行业' in df_sector.columns:
            # P5: 过滤掉净额绝对值过小的尾部行业，只保留主力核心大行业，避免极小区块挤压字号而无法显示文字
            df_sector = df_sector.sort_values(by='绝对净流入', ascending=False)
            df_sector = df_sector[df_sector['绝对净流入'] >= 1.0].head(25)
            
            if not df_sector.empty:
                df_sector['板块'] = 'A股全市场'
                
                # P1: 字体颜色规则: 净流入>=0 (红底) 用白字，净流入<0 (绿底) 用黑字
                df_sector['font_color'] = df_sector['净流入(亿元)'].apply(lambda x: '#ffffff' if x >= 0 else '#000000')
                
                fig_tree = px.treemap(
                    df_sector,
                    path=['板块', '行业'],
                    values='绝对净流入',
                    color='净流入(亿元)',
                    color_continuous_scale=[[0, '#00E676'], [0.5, '#262730'], [1, '#FF4B4B']],
                    color_continuous_midpoint=0,
                    hover_data={
                        '净流入(亿元)': ':.2f',
                        '涨跌幅': ':.2f',
                        '领涨股': True,
                        '绝对净流入': False,
                        '板块': False
                    },
                    custom_data=['净流入(亿元)', '涨跌幅', '领涨股', 'font_color']
                )
                
                try:
                    fig_tree.update_traces(
                        textinfo="label+value+percent parent",
                        texttemplate="<span style='color:%{customdata[3]}'><b>%{label}</b><br>净额: %{customdata[0]:.2f}亿<br>涨幅: %{customdata[1]:+.2f}%</span>",
                        textfont=dict(size=26, family="Arial, sans-serif"),  # 将大区块字号基准拉高至 26px
                        textposition="middle center",
                        hovertemplate="<b>%{label}</b><br>净流入: %{customdata[0]:.2f}亿<br>行业涨跌: %{customdata[1]:.2f}%<br>领涨龙头: %{customdata[2]}<extra></extra>",
                        marker=dict(cornerradius=4, pad=dict(t=2, l=2, r=2, b=2), line=dict(color='#0A0D14', width=2))
                    )
                except Exception:
                    try:
                        fig_tree.update_traces(
                            textinfo="label+value",
                            texttemplate="<span style='color:%{customdata[3]}'><b>%{label}</b><br>净额: %{customdata[0]:.2f}亿</span>",
                            textfont=dict(size=26, family="Arial, sans-serif"),
                            textposition="middle center",
                            marker=dict(cornerradius=4, pad=dict(t=2, l=2, r=2, b=2), line=dict(color='#0A0D14', width=2))
                        )
                    except Exception:
                        pass
                
                fig_tree.update_layout(
                    font=dict(family="Inter, Roboto, 'Microsoft YaHei', sans-serif"),
                    uniformtext=dict(
                        minsize=11,  # 设定字号下限为 11px
                        mode='hide'  # 小于 11px 的微小区块自动隐藏文字，避免拖累大区块
                    ),
                    height=650,  # 确保给热力图充裕的垂直空间
                    margin=dict(l=10, r=10, t=35, b=10),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    coloraxis_colorbar=dict(
                        title="净流入(亿)",
                        thicknessmode="pixels", thickness=15,
                        lenmode="pixels", len=300,
                        yanchor="top", y=1,
                        ticks="outside"
                    )
                )
                st.plotly_chart(fig_tree, width="stretch", key="macro_treemap")
            else:
                st.warning("当前时段接口维护，资金流数据暂缓更新")
        else:
            st.warning("当前时段接口维护，资金流数据暂缓更新")

        # --- 新增: CFFEX 股指期货席位多空持仓变动监测 ---
        st.markdown("---")
        st.markdown("### 📊 CFFEX 股指期货主力席位持仓异动监控")
        st.caption("实时监控中金所股指期货主力席位的大单多空增减仓数据，透视头部主力机构席位买卖动向。")
        
        # 1. 自动获取最近一个交易日的股指期货数据
        cffex_date, cffex_data = None, {}
        try:
            # 引入 fallback 逻辑，向后检索最近 7 天数据
            for offset in range(7):
                t_date = (datetime.datetime.now() - datetime.timedelta(days=offset)).strftime("%Y%m%d")
                try:
                    # V8 修复：CFFEX 单日数据抓取加 20s 硬超时（非交易日/周末
                    # 接口不响应时原会无限挂起，7 天回溯循环放大为整页卡死）
                    res_dict = _fetch_with_timeout(
                        ak.get_cffex_rank_table, kwargs={"date": t_date},
                        timeout_s=20, default=None)
                    if res_dict:
                        valid = False
                        for k, df in res_dict.items():
                            if isinstance(df, pd.DataFrame) and not df.empty:
                                valid = True
                                break
                        if valid:
                            cffex_date = t_date
                            cffex_data = res_dict
                            break
                except Exception:
                    pass
        except Exception as e:
            st.info(f"股指期货数据获取暂缓: {e}")

        if cffex_date and cffex_data:
            # 格式化日期显示
            fmt_date = f"{cffex_date[:4]}-{cffex_date[4:6]}-{cffex_date[6:8]}"
            st.markdown(f"<div style='font-size:0.85rem; color:#94a3b8; margin-bottom:10px;'>最新数据日期: <b>{fmt_date}</b> (中金所每日盘后大单持仓数据)</div>", unsafe_allow_html=True)
            
            # 品种选择
            f_prod = st.radio("选择股指期货品种", ["IF (沪深300期货)", "IC (中证500期货)", "IM (中证1000期货)", "IH (上证50期货)"], horizontal=True)
            prod_prefix = f_prod.split(" ")[0]
            
            # 获取该品种的所有合约
            contracts = sorted([k for k in cffex_data.keys() if k.startswith(prod_prefix)])
            if contracts:
                # 寻找主力合约（持仓量最大的合约）
                active_contract = contracts[0]
                max_vol = -1
                for c in contracts:
                    df_c = cffex_data[c]
                    if 'long_open_interest' in df_c.columns:
                        total_hold = df_c['long_open_interest'].sum()
                        if total_hold > max_vol:
                            max_vol = total_hold
                            active_contract = c
                
                selected_contract = st.selectbox("选择具体合约", contracts, index=contracts.index(active_contract))
                
                df_contract = cffex_data[selected_contract]
                
                # 开始解析增减仓
                # 过滤并清洗多单数据
                df_long = df_contract.dropna(subset=['long_party_name', 'long_open_interest_chg'])
                df_long = df_long[df_long['long_party_name'].str.strip() != '']
                # 按绝对值变动大小降序排序，取前 10
                df_long_top = df_long.sort_values(by='long_open_interest_chg', key=abs, ascending=False).head(10)
                
                # 过滤并清洗空单数据
                df_short = df_contract.dropna(subset=['short_party_name', 'short_open_interest_chg'])
                df_short = df_short[df_short['short_party_name'].str.strip() != '']
                # 按绝对值变动大小降序排序，取前 10
                df_short_top = df_short.sort_values(by='short_open_interest_chg', key=abs, ascending=False).head(10)
                
                c_c1, c_c2 = st.columns(2)
                
                # CSS style for tables
                st.markdown("""
                <style>
                .futures-table {
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 0.82rem;
                    margin-top: 10px;
                    background-color: rgba(10, 15, 30, 0.4);
                    border-radius: 8px;
                    overflow: hidden;
                    border: 1px solid rgba(255, 255, 255, 0.05);
                }
                .futures-table th {
                    background-color: rgba(255, 255, 255, 0.05);
                    padding: 8px 10px;
                    text-align: left;
                    color: #94a3b8;
                    font-weight: 600;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                }
                .futures-table td {
                    padding: 8px 10px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
                    color: #ffffff;
                }
                .chg-red {
                    color: #ef4444 !important;
                    font-weight: bold;
                }
                .chg-green {
                    color: #00b865 !important;
                    font-weight: bold;
                }
                </style>
                """, unsafe_allow_html=True)
                
                with c_c1:
                    st.markdown("#### 🐂 多单主力席位今日增减持 Top10")
                    html_long = "<table class='futures-table'><tr><th>名次</th><th>多单席位</th><th>今日增减</th><th>多单持仓(手)</th></tr>"
                    for idx, row in df_long_top.reset_index().iterrows():
                        chg_val = int(row['long_open_interest_chg'])
                        chg_str = f"+{chg_val}" if chg_val >= 0 else f"{chg_val}"
                        chg_class = "chg-red" if chg_val >= 0 else "chg-green" # 多单增加是利多(红)，减少是利空(绿)
                        html_long += f"<tr><td>{idx+1}</td><td>{row['long_party_name']}</td><td class='{chg_class}'>{chg_str}</td><td>{int(row['long_open_interest'])}</td></tr>"
                    html_long += "</table>"
                    st.markdown(html_long, unsafe_allow_html=True)
                    
                with c_c2:
                    st.markdown("#### 🐻 空单主力席位今日增减持 Top10")
                    html_short = "<table class='futures-table'><tr><th>名次</th><th>空单席位</th><th>今日增减</th><th>空单持仓(手)</th></tr>"
                    for idx, row in df_short_top.reset_index().iterrows():
                        chg_val = int(row['short_open_interest_chg'])
                        chg_str = f"+{chg_val}" if chg_val >= 0 else f"{chg_val}"
                        chg_class = "chg-green" if chg_val >= 0 else "chg-red" # 空单增加是利空(绿)，减少是利多(红)
                        html_short += f"<tr><td>{idx+1}</td><td>{row['short_party_name']}</td><td class='{chg_class}'>{chg_str}</td><td>{int(row['short_open_interest'])}</td></tr>"
                    html_short += "</table>"
                    st.markdown(html_short, unsafe_allow_html=True)
            else:
                st.info("未获取到当前合约的分席位持仓数据。")
        else:
            st.warning("暂无股指期货主力席位持仓变动数据。")


# ============================================================================
# V11 新增：统一图文分析段落助手
# ============================================================================

def render_chart_caption(data_fact: str, chg_desc: str, attribution: str, outlook: str):
    """渲染标准化图文联动分析段落（仿机构日报 .ana 格式）。
    data_fact:   数据事实描述
    chg_desc:    环比/同比变动
    attribution: 机构行为归因
    outlook:     简短展望
    """
    st.markdown(
        f'<div class="chart-ana">'
        f'<span class="ana-fact">{data_fact}</span>，'
        f'<span class="ana-chg">{chg_desc}</span>。'
        f'<span class="ana-attr">{attribution}</span>。'
        f'<span class="ana-outlook">展望：{outlook}</span>'
        f'</div>',
        unsafe_allow_html=True
    )



# ============================================================================
# ▼▼▼ 内联模块：market_tape.py  （原独立文件，V7 单文件版已合并至此）
# ============================================================================

import akshare as ak
import datetime
import json
import os
import streamlit as st
from openai import OpenAI

CACHE_FILE = "news_cache.json"

def load_news_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception: pass
    return []

def save_news_cache(news_list):
    # 过滤掉超过 72 小时 (3天) 的旧新闻
    now = datetime.datetime.now()
    valid_news = []
    for item in news_list:
        try:
            item_time = datetime.datetime.strptime(item['time_str'], "%Y-%m-%d %H:%M:%S")
            if (now - item_time).total_seconds() <= 3600 * 72:
                valid_news.append(item)
        except Exception:
            valid_news.append(item)

    valid_news.sort(key=lambda x: x.get('time_str', ''), reverse=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(valid_news, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return valid_news

@st.cache_data(ttl=180, show_spinner=False)
def fetch_cls_news():
    """Fetch new news from multiple sources (Cailianshe, THS, Baidu) and update news_cache.json."""
    cache = load_news_cache()
    fetched_list = []
    
    # 1. 尝试抓取 ak.news_economic_cailianshe() (财联社学术)
    try:
        if hasattr(ak, 'news_economic_cailianshe'):
            df1 = ak.news_economic_cailianshe()
            if df1 is not None and not df1.empty:
                for _, row in df1.iterrows():
                    item = row.to_dict()
                    dt_val = item.get('发布时间') or item.get('datetime')
                    d_str = datetime.date.today().strftime('%Y-%m-%d')
                    t_str = "00:00:00"
                    if dt_val:
                        dt_str = str(dt_val)
                        if len(dt_str) >= 19:
                            d_str, t_str = dt_str[:10], dt_str[11:19]
                    
                    title = item.get('标题') or item.get('title') or item.get('内容', '')[:30]
                    content = item.get('内容') or item.get('content') or title
                    if title:
                        fetched_list.append({
                            '标题': title,
                            '内容': content,
                            '发布日期': d_str,
                            '发布时间': t_str,
                            'time_str': f"{d_str} {t_str}".strip(),
                            'source': 'CLS-Economic'
                        })
    except Exception:
        pass
        
    # 2. 尝试抓取 ak.stock_info_global_news() (同花顺/全球资讯)
    try:
        if hasattr(ak, 'stock_info_global_news'):
            df2 = ak.stock_info_global_news()
            if df2 is not None and not df2.empty:
                for _, row in df2.iterrows():
                    item = row.to_dict()
                    dt_val = item.get('发布时间') or item.get('datetime')
                    d_str = datetime.date.today().strftime('%Y-%m-%d')
                    t_str = "00:00:00"
                    if dt_val:
                        dt_str = str(dt_val)
                        if len(dt_str) >= 19:
                            d_str, t_str = dt_str[:10], dt_str[11:19]
                    
                    title = item.get('标题') or item.get('title') or item.get('内容', '')[:30]
                    content = item.get('内容') or item.get('content') or title
                    if title:
                        fetched_list.append({
                            '标题': title,
                            '内容': content,
                            '发布日期': d_str,
                            '发布时间': t_str,
                            'time_str': f"{d_str} {t_str}".strip(),
                            'source': 'THS-Global'
                        })
    except Exception:
        pass

    # 3. 始终抓取已存在的 ak.stock_info_global_cls() 作为高可靠兜底/核心源
    try:
        df3 = ak.stock_info_global_cls()
        if df3 is not None and not df3.empty:
            for _, row in df3.iterrows():
                item = row.to_dict()
                date_val = item.get('发布日期')
                time_val = item.get('发布时间')
                d_str = date_val.strftime('%Y-%m-%d') if hasattr(date_val, 'strftime') else str(date_val or '')
                t_str = time_val.strftime('%H:%M:%S') if hasattr(time_val, 'strftime') else str(time_val or '')
                
                title = item.get('标题') or item.get('内容', '')[:30]
                content = item.get('内容') or item.get('标题', '')
                if title:
                    fetched_list.append({
                        '标题': title,
                        '内容': content,
                        '发布日期': d_str,
                        '发布时间': t_str,
                        'time_str': f"{d_str} {t_str}".strip(),
                        'source': 'CLS'
                    })
    except Exception:
        pass

    # 4. 尝试抓取百度财经新闻作为辅助源
    try:
        if hasattr(ak, 'news_economic_baidu'):
            df4 = ak.news_economic_baidu()
            if df4 is not None and not df4.empty:
                for _, row in df4.iterrows():
                    item = row.to_dict()
                    dt_val = item.get('发布时间') or item.get('datetime')
                    d_str = datetime.date.today().strftime('%Y-%m-%d')
                    t_str = "00:00:00"
                    if dt_val:
                        dt_str = str(dt_val)
                        if len(dt_str) >= 19:
                            d_str, t_str = dt_str[:10], dt_str[11:19]
                    
                    title = item.get('标题') or item.get('title')
                    content = item.get('内容') or item.get('content') or title
                    if title:
                        fetched_list.append({
                            '标题': title,
                            '内容': content,
                            '发布日期': d_str,
                            '发布时间': t_str,
                            'time_str': f"{d_str} {t_str}".strip(),
                            'source': 'Baidu'
                        })
    except Exception:
        pass

    if not fetched_list:
        return cache

    # 按 title/标题 字段去重合并
    merged = {item.get('标题', ''): item for item in cache if item.get('标题')}
    for item in fetched_list:
        title = item.get('标题', '')
        if title:
            # 只有当新获取的新闻不存在，或者新获取的新闻时间更新时，才更新缓存
            if title not in merged or item.get('time_str', '') > merged[title].get('time_str', ''):
                merged[title] = item

    return save_news_cache(list(merged.values()))

def classify_news(title, content):
    text = (str(title) + " " + str(content)).lower()
    
    # Priority 1: 全球事件 (Global Events) - 最高优先级拦截
    global_kws = ['美国', '美联储', '非农', 'cpi', '欧洲', '日央行', '拜登', '普京', '国际', '华尔街', '纳指', '标普', '海外', '世贸', '联储']
    if any(kw in text for kw in global_kws):
        return "全球事件"
        
    # Priority 2: 部门政策 (Domestic Policy) - 排除掉全球事件后
    policy_kws = ['发改委', '央行', '国务院', '住建部', '财政部', '证监会', '工信部', '商务部', '印发', '条例', '新规', '十四五', '征求意见']
    if any(kw in text for kw in policy_kws):
        return "部门政策"
        
    # Priority 3: 公司公告 (Company Announcements)
    company_kws = ['财报', '营收', '净利', '涨停', '跌停', '股份', '有限公司', '拟收购', '分红', 'st', '复牌', '股东减持', '实控人']
    if any(kw in text for kw in company_kws):
        return "公司公告"
        
    # Priority 4: 行业/机构 (Industry/Institutions) - 默认兜底
    return "行业/机构"


def get_market_tape_ui(used_key=""):
    st.markdown("---")
    
    with st.container(height=600):
        st.markdown("### 📡 全市场实时盘口 (财联社全球快讯)")
        st.markdown("<div style='font-size:0.85rem; opacity:0.8;'>此模块实时抓取财联社最新电报，并可通过 AI 提取客观事件影响，绝不提供买卖建议。</div><br>", unsafe_allow_html=True)
        
        with st.spinner("正在同步全球快讯..."):
            news_list = fetch_cls_news()
            
        if not news_list:
            st.warning("暂无快讯数据，可能是首次拉取失败或接口限流。")
            return
            
        # Sort by datetime descending
        def get_dt(item):
            try:
                return datetime.datetime.strptime(f"{item.get('发布日期', '')} {item.get('发布时间', '')}", "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.datetime.min
        news_list.sort(key=get_dt, reverse=True)
            
        st.caption(f"最新更新时间: {news_list[0].get('发布日期')} {news_list[0].get('发布时间')}")
        
        # 分类数据
        df_company, df_global, df_policy, df_industry = [], [], [], []
        
        for row in news_list:
            category = classify_news(row.get('标题', ''), row.get('内容', ''))
            if category == "公司公告": df_company.append(row)
            elif category == "全球事件": df_global.append(row)
            elif category == "部门政策": df_policy.append(row)
            else: df_industry.append(row)
                
        tabs = st.tabs([f"🏢 公司公告 ({len(df_company)})", f"🌍 全球事件 ({len(df_global)})", f"🏛️ 部门政策 ({len(df_policy)})", f"🏭 行业/机构 ({len(df_industry)})"])
        
        def render_news_list(c_list, prefix):
            if not c_list:
                st.info("暂无该分类的最新动态")
                return
            for i, row in enumerate(c_list[:50]): # Display up to 50 per tab to avoid UI lag
                title = row.get('标题', '')
                content = row.get('内容', '')
                pub_time = row.get('发布时间', '')
                
                if not title and content:
                    title = content[:30] + "..."
                    
                with st.expander(f"🕒 {pub_time} | {title}", expanded=(i==0)):
                    st.write(content)
                    
                    # Create a safe unique key
                    safe_title_hash = abs(hash(title)) % 10000
                    btn_key = f"ai_btn_tape_{prefix}_{i}_{safe_title_hash}"
                    res_key = f"ai_res_tape_{prefix}_{i}_{safe_title_hash}"
                    
                    if st.button("🤖 AI 深度客观解读", key=btn_key):
                        if not used_key:
                            st.warning("⚠️ 请先在上方输入 API 密钥 (智谱清言 或 OpenAI)")
                        else:
                            with st.spinner("AI 正在客观分析事件影响与涉及标的..."):
                                try:
                                    if used_key.startswith("sk-proj-"):
                                        base_url = "https://api.openai.com/v1"
                                        model_name = "gpt-4o-mini"
                                    else:
                                        base_url = "https://open.bigmodel.cn/api/paas/v4/"
                                        model_name = "glm-4-flash"
                                        
                                    client = OpenAI(api_key=used_key, base_url=base_url)
                                    prompt = f"""
请作为一位中立的金融数据分析师，深度且客观地解读以下快讯。
【核心规则】：
绝对不允许生成任何投资建议、买入/卖出评级或目标价预测。只提取客观事实与直接的产业逻辑。

【快讯内容】：
{title}
{content}

【请按以下格式输出】：
**1. 事件定性**：(如：产业并购、财报超预期、宏观政策利好等)
**2. 涉及板块/标的**：(直接相关的行业板块或股票名称，如：星网锐捷、通信设备)
**3. 客观影响链条**：(简要分析该事件对产业链上下游或公司基本面的客观影响，不带主观情绪预测)
"""
                                    response = client.chat.completions.create(
                                        model=model_name,
                                        messages=[{"role": "user", "content": prompt}],
                                        temperature=0.1
                                    )
                                    st.session_state[res_key] = response.choices[0].message.content
                                except Exception as e:
                                    st.error(f"AI 调用失败: {e}")
                    
                    if res_key in st.session_state:
                        st.info(st.session_state[res_key])

        with tabs[0]: render_news_list(df_company, 'comp')
        with tabs[1]: render_news_list(df_global, 'glob')
        with tabs[2]: render_news_list(df_policy, 'poli')
        with tabs[3]: render_news_list(df_industry, 'indu')


# ============================================================================
# ▼▼▼ 内联模块：crowdsource_agent.py  （原独立文件，V7 单文件版已合并至此）
# ============================================================================

import streamlit as st
import json
import os
import numpy as np
import pandas as pd
import plotly.express as px

# V7：同业估值基准动态引擎 + 彭博化 UI 组件
# [已内联] from fundamentals import fetch_industry_benchmark, sf, C_UP, C_DOWN, C_NEUTRAL, C_ACCENT
# [已内联] from terminal_ui import render_kpi_grid, section_bar, build_scenario_chart

def get_crowdsource_ui(api_key, ticker, all_data=None):
    if not ticker:
        return
        
    st.markdown("---")
    st.markdown(f"## 🧮 【{ticker}】估值模型及财务推演计算器")
    st.markdown("<div style='background:rgba(30, 41, 59, 0.7); border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:14px 18px; font-size:0.88rem; line-height:1.8; color:#D1D4DC; margin-bottom:1rem;'>基于同行业估值水平与未来业绩预期，全自动多维推演并展示个股相对合理股价与估值水位差。</div>", unsafe_allow_html=True)
    
    # 提取客观基础财务指标
    info = all_data.get('info', {}) if all_data else {}
    price = info.get('currentPrice') or info.get('regularMarketPrice') or 1.0
    mcap = info.get('marketCap')
    currency = info.get('currency', 'USD')
    is_usd = currency in ['USD', '$']
    unit_lbl = "亿美元" if is_usd else "亿元"
    price_lbl = "$" if is_usd else "元"

    def fmt_calc_price(val):
        if not val or val <= 0:
            return "数据缺失"
        if is_usd:
            return f"${val:,.2f}"
        else:
            return f"{val:,.2f} 元"

    # 计算总股本 (单位: 亿股)
    shares = info.get('sharesOutstanding')
    if (shares is None or shares == 0) and mcap and price:
        shares = mcap / price
    if shares is None or shares == 0:
        shares = 1e9 # 默认 10 亿股
    shares_in_100m = shares / 1e8
    
    # 默认值估算 (单位: 亿元/亿美元)
    def_rev = 0.0
    def_net_inc = 0.0
    def_net_assets = 0.0
    if info:
        rev_val = info.get('totalRevenue')
        if rev_val: def_rev = rev_val / 1e8
        net_inc_val = info.get('netIncome') or info.get('netIncomeToCommon')
        if net_inc_val: def_net_inc = net_inc_val / 1e8
        bv = info.get('bookValue')
        if bv:
            def_net_assets = (bv * (shares or 1e9)) / 1e8
        else:
            total_assets = info.get('totalAssets', 0) or 0
            total_liab = info.get('totalLiabilities', 0) or 0
            if total_assets > total_liab:
                def_net_assets = (total_assets - total_liab) / 1e8
            elif mcap:
                def_net_assets = mcap / 1e8 / 3.0

    # 重置/更新 session_state，防止继承上一标的的财务数值
    if st.session_state.get("last_calc_ticker") != ticker:
        st.session_state["calc_pred_rev"] = float(def_rev) if def_rev > 0 else 10.0
        st.session_state["calc_pred_net_inc"] = float(def_net_inc) if def_net_inc > 0 else 1.0
        st.session_state["calc_pred_net_assets"] = float(def_net_assets) if def_net_assets > 0 else 20.0
        st.session_state["last_calc_ticker"] = ticker
                
    # 目标当前实际估值指标 (Fallback 估算逻辑)
    curr_pe = info.get('trailingPE') or info.get('forwardPE')
    if (curr_pe is None or pd.isna(curr_pe) or curr_pe <= 0) and def_net_inc > 0:
        curr_pe = (price * shares_in_100m) / def_net_inc
    
    curr_pb = info.get('priceToBook')
    if (curr_pb is None or pd.isna(curr_pb) or curr_pb <= 0) and def_net_assets > 0:
        curr_pb = (price * shares_in_100m) / def_net_assets
        
    curr_ps = info.get('priceToSalesTrailing12Months')
    if (curr_ps is None or pd.isna(curr_ps) or curr_ps <= 0) and def_rev > 0:
        curr_ps = (price * shares_in_100m) / def_rev

    # =====================================================================
    # V7 战役一：同行业估值基准「动态实时拉取」——彻底废除 PE=20x 静态写死常量
    # A 股走东财行业板块全部成分股实时中位数；美/港股走 yfinance 同行业头部可比公司。
    # 拉取失败时 ref_* 保持 None，UI 明示"真实同业数据缺失"，绝不用假设倍数推演。
    # =====================================================================
    industry = info.get('industry', '') or ''
    industry_key = info.get('industryKey', '') or ''
    sector = info.get('sector', '') or ''
    is_a_share = bool((all_data or {}).get('is_a_share')) or str(ticker).endswith(('.SS', '.SZ', '.BJ'))
    pure_code = (all_data or {}).get('pure_code') or str(ticker).split('.')[0]

    bench = None
    bench_err = None
    try:
        bench = fetch_industry_benchmark(str(ticker), industry_key=industry_key,
                                         industry_name=industry, is_a_share=is_a_share,
                                         pure_code=pure_code)
    except Exception as e:
        bench_err = f"{type(e).__name__}: {e}"

    ref_pe = bench.get('pe') if bench else None
    ref_pb = bench.get('pb') if bench else None
    ref_ps = bench.get('ps') if bench else None
    bench_source = bench.get('source') if bench else None

    if bench_source:
        st.caption(f"📡 同行业估值基准来源：{bench_source}")
    else:
        st.warning("⚠️ 同行业成分股估值基准真实数据缺失（行业未匹配 / 接口限流"
                   + (f"：{bench_err}" if bench_err else "") +
                   "）。本站拒绝使用 PE=20x 这类写死常量兜底，因此缺失口径的推演结果将直接留空。")

        # 布局：左侧输入预测财务指标，右侧展示水位差卡片
    # V10 P9：左文右图垂直居中对齐，消除两侧视觉高低差
    calc_c1, calc_c2 = st.columns([1, 1.2], vertical_alignment="center")
    
    with calc_c1:
        st.write("#### 1. 预测财务指标")
        
        # V10 P1：全站唯一全局搜索框（页面顶部），此处不再放第二个标的输入框；
        # 众包计算器直接跟随全局 selected_ticker，避免重复输入与状态互相覆盖。
        st.caption("🎯 当前预测标的跟随顶部全局搜索框，切换标的请在上方输入")
            
        # V8 修复：key 已在 session_state 设初值（上方换股重置块）的控件不能再
        # 传 value=，否则 Streamlit 抛 StreamlitAPIException，整个众包区中断。
        # 初值一律走 session_state.setdefault，控件本身不传默认值。
        for _k, _v in [("calc_pred_rev", float(def_rev) if def_rev > 0 else 100.0),
                       ("calc_pred_net_inc", float(def_net_inc) if def_net_inc > 0 else 15.0),
                       ("calc_pred_net_assets", float(def_net_assets) if def_net_assets > 0 else 60.0)]:
            st.session_state.setdefault(_k, _v)
        pred_rev = st.number_input(f"预测营业收入 ({unit_lbl})", min_value=0.0, step=10.0, key="calc_pred_rev")
        pred_net_inc = st.number_input(f"预测净利润 ({unit_lbl})", min_value=0.0, step=2.0, key="calc_pred_net_inc")
        pred_net_assets = st.number_input(f"预测净资产 ({unit_lbl})", min_value=0.0, step=5.0, key="calc_pred_net_assets")
        
    with calc_c2:
        st.write("#### 📊 估值水位差 (Gap Analysis)")
        
        # 渲染差异卡片的 CSS 样式 (顶格左对齐，防止 raw text 解析)
        st.markdown("""<style>
.gap-analysis-container {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 5px;
}
.gap-card {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
}
.gap-title {
    font-size: 0.8rem;
    color: #94A3B8;
    font-weight: 500;
}
.gap-vals {
    font-size: 0.85rem;
    margin-top: 3px;
    color: #f1f5f9;
}
</style>""", unsafe_allow_html=True)

        # 估值差计算与渲染
        def get_gap_card_html(label, curr_val, ref_val, missing):
            def_lbl = (" <span style='font-size:0.68rem; color:#8B93A7;'>(同业真实数据缺失)</span>"
                       if missing else " <span style='font-size:0.68rem; color:#00E676;'>(同业实时中位数)</span>")
            if ref_val is None or curr_val is None or pd.isna(curr_val) or curr_val <= 0:
                ref_txt = f"<b>{ref_val:.2f}x</b>" if isinstance(ref_val, (int, float)) else "真实数据缺失"
                cur_txt = f"<b>{curr_val:.2f}x</b>" if isinstance(curr_val, (int, float)) and curr_val > 0 else "真实数据缺失"
                return f"""<div class="gap-card">
    <div class="gap-title">{label}{def_lbl}</div>
    <div class="gap-vals">当前实际: {cur_txt} | 同业中位: {ref_txt}</div>
    <div style="color: #8B93A7; font-weight: 600; font-size: 0.85rem; margin-top: 4px;">水位差: 无法计算（拒绝假值填充）</div>
</div>"""

            gap_pct = ((curr_val - ref_val) / ref_val) * 100
            # 语义化色彩：高估 → Crimson Red；低估 → Neon Green
            status_color = "#FF4B4B" if gap_pct >= 0 else "#00E676"
            status_lbl = f"溢价 {gap_pct:+.1f}%" if gap_pct >= 0 else f"折价 {gap_pct:+.1f}%"
            return f"""<div class="gap-card">
    <div class="gap-title">{label}{def_lbl}</div>
    <div class="gap-vals">当前实际: <b>{curr_val:.1f}x</b> | 行业平均: <b>{ref_val:.1f}x</b></div>
    <div style="color: {status_color}; font-weight: bold; font-size: 0.88rem; margin-top: 4px;">水位差: {status_lbl}</div>
</div>"""

        gap_html_pe = get_gap_card_html("PE 估值水位", curr_pe, ref_pe, ref_pe is None)
        gap_html_pb = get_gap_card_html("PB 估值水位", curr_pb, ref_pb, ref_pb is None)
        gap_html_ps = get_gap_card_html("PS 估值水位", curr_ps, ref_ps, ref_ps is None)
        
        st.markdown(f"""<div class="gap-analysis-container">
    {gap_html_pe}
    {gap_html_pb}
    {gap_html_ps}
</div>""", unsafe_allow_html=True)
        
    # 全自动相对估值计算（同业基准缺失的口径直接判定为不可推演，置 0 并在 UI 明示）
    pe_price = (pred_net_inc * ref_pe) / shares_in_100m if (ref_pe and shares_in_100m > 0 and pred_net_inc > 0) else 0.0
    pb_price = (pred_net_assets * ref_pb) / shares_in_100m if (ref_pb and shares_in_100m > 0 and pred_net_assets > 0) else 0.0
    ps_price = (pred_rev * ref_ps) / shares_in_100m if (ref_ps and shares_in_100m > 0 and pred_rev > 0) else 0.0

    pe_mcap = pred_net_inc * ref_pe if (ref_pe and pred_net_inc > 0) else 0.0
    pb_mcap = pred_net_assets * ref_pb if (ref_pb and pred_net_assets > 0) else 0.0
    ps_mcap = pred_rev * ref_ps if (ref_ps and pred_rev > 0) else 0.0
    
    # 过滤无效或极端离群的估值价格 (例如亏损导致负数，或偏离当前股价 3 倍以上/小于 0.25 倍)
    valid_prices = []
    valid_mcaps = []
    for p_val, m_val in [(pe_price, pe_mcap), (pb_price, pb_mcap), (ps_price, ps_mcap)]:
        if p_val > 0:
            if price <= 0 or (p_val >= 0.25 * price and p_val <= 3.0 * price):
                valid_prices.append(p_val)
                valid_mcaps.append(m_val)
                
    if not valid_prices:
        all_p = [p for p in [pe_price, pb_price, ps_price] if p > 0]
        valid_prices = all_p if all_p else [price]
        all_m = [m for m in [pe_mcap, pb_mcap, ps_mcap] if m > 0]
        valid_mcaps = all_m if all_m else [mcap / 1e8 if mcap else 10.0]
        
    min_p, max_p = min(valid_prices), max(valid_prices)
    min_m, max_m = min(valid_mcaps), max(valid_mcaps)

    curr_zh_map = {'USD': '美元', 'CNY': '人民币', 'HKD': '港币', 'EUR': '欧元', 'JPY': '日元'}
    curr_zh = curr_zh_map.get(str(currency).upper(), currency)

    # =====================================================================
    # V7 战役三：估值推演器 UI 重做 —— 三情景（悲观/中性/乐观）靶心区间图
    # 情景倍数不是主观拍的：以同业中位数为中性锚，用同业倍数分布的 ±25% 作为
    # 悲观/乐观带宽（同业分布本身就是真实数据），并在图中标注现价基准线。
    # =====================================================================
    valid_multiple = [v for v in [ref_pe, ref_pb, ref_ps] if v]
    if valid_multiple and max(min_p, max_p) > 0:
        base_mid = float(np.mean([p for p in [pe_price, pb_price, ps_price] if p > 0]) or 0.0)
        scenarios = [
            ("悲观情景 (同业中位 ×0.75)", base_mid * 0.75,
             "同业倍数中位数下移 25%，对应估值收缩情形"),
            ("中性情景 (同业中位)", base_mid,
             f"直接采用同业实时倍数中位数：{bench_source or '同业中位数'}"),
            ("乐观情景 (同业中位 ×1.25)", base_mid * 1.25,
             "同业倍数中位数上移 25%，对应估值扩张情形"),
        ]
        fig_scn = build_scenario_chart(price, scenarios, price_label=price_lbl, height=320)
        if fig_scn is not None:
            st.plotly_chart(fig_scn, width="stretch", config={'displayModeBar': False})

        render_kpi_grid([
            dict(label="推演合理股价区间", value=f"{fmt_calc_price(min_p)} ~ {fmt_calc_price(max_p)}",
                 sub=f"当前实际股价 {fmt_calc_price(price)}", value_direction="accent"),
            dict(label="推演目标市值区间", value=f"{min_m:,.2f}亿 ~ {max_m:,.2f}亿",
                 sub=f"{curr_zh} · 股本基准 {shares_in_100m:.2f} 亿股"),
            dict(label="PE 法推演价",
                 value=(fmt_calc_price(pe_price) if pe_price > 0 else "同业 PE 缺失"),
                 sub=(f"预测净利 × 同业 PE {ref_pe:.2f}x" if ref_pe else "无真实同业 PE，不推演")),
            dict(label="PB 法推演价",
                 value=(fmt_calc_price(pb_price) if pb_price > 0 else "同业 PB 缺失"),
                 sub=(f"预测净资产 × 同业 PB {ref_pb:.2f}x" if ref_pb else "无真实同业 PB，不推演")),
            dict(label="PS 法推演价",
                 value=(fmt_calc_price(ps_price) if ps_price > 0 else "同业 PS 缺失"),
                 sub=(f"预测营收 × 同业 PS {ref_ps:.2f}x" if ref_ps else "无真实同业 PS，不推演")),
            dict(label="中性情景相对现价",
                 value=(f"{(base_mid - price)/price*100:+.1f}%" if (price and base_mid) else "数据缺失"),
                 sub="纯倍数推演差值，非目标价推荐",
                 direction=("up" if base_mid >= price else "down") if (price and base_mid) else "neutral",
                 value_direction=("up" if base_mid >= price else "down") if (price and base_mid) else None),
        ], cols=3)
        st.caption("📌 以上均为「用户输入的财务预测 × 同业实时倍数」的机械算术结果，"
                   "既非本站目标价，也不构成任何投资建议。")
    else:
        st.warning("⚠️ 同行业 PE/PB/PS 真实基准全部缺失，估值推演器无法给出任何倍数法结果。"
                   "本站严格禁止用写死的假设倍数生成推演区间。")

    # 下方原 UGC 录入与直方图查看功能
    st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)
    with st.expander("🤖 UGC 众包预期录入与查看", expanded=False):
        st.markdown(f"#### 📈 {ticker} 众包财务与估值预期录入")
        session_key = f"crowdsource_submitted_{ticker}"
        if session_key not in st.session_state:
            st.session_state[session_key] = False
 
        # Input Form (P2: 改造录入逻辑，增加盈利与净资产预测，自动计算并落地综合目标价)
        with st.form(key=f"crowd_form_{ticker}"):
            col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
            with col1:
                fiscal_quarter = st.text_input("预测财季", value="2026Q3", help="例如 2026Q3 或 2026FY")
            with col2:
                revenue_estimate = st.number_input(f"预期营业收入 ({unit_lbl})", min_value=0.0, value=float(def_rev) if def_rev > 0 else 100.0, step=10.0)
            with col3:
                net_income_estimate = st.number_input(f"预期净利润 ({unit_lbl})", min_value=0.0, value=float(def_net_inc) if def_net_inc > 0 else 15.0, step=2.0)
            with col4:
                net_assets_estimate = st.number_input(f"预期净资产 ({unit_lbl})", min_value=0.0, value=float(def_net_assets) if def_net_assets > 0 else 60.0, step=5.0)
                
            user_logic = st.text_input("核心多空推演逻辑 (选填)", placeholder="例如：下一代芯片出货量激增，折价明显具有安全边际")
            
            submitted = st.form_submit_button("🤖 提交我的预测，并解锁大众一致预期目标价分布图", width="stretch")
            
            if submitted:
                # 依据行业均值倍数推演该玩家预测下的综合合理股价 (均值作为综合股价)
                # V7：同业基准缺失时该口径不参与推演（绝不用假设倍数补位）
                pe_p = (net_income_estimate * ref_pe) / shares_in_100m if (ref_pe and shares_in_100m > 0) else 0.0
                pb_p = (net_assets_estimate * ref_pb) / shares_in_100m if (ref_pb and shares_in_100m > 0) else 0.0
                ps_p = (revenue_estimate * ref_ps) / shares_in_100m if (ref_ps and shares_in_100m > 0) else 0.0

                valid_ps = [v for v in [pe_p, pb_p, ps_p] if v > 0]
                user_target_price = np.mean(valid_ps) if valid_ps else 0.0

                parsed_data = {
                    "ticker": ticker,
                    "fiscal_quarter": fiscal_quarter,
                    # V12：补记提交时间。原结构没有任何时间戳，而条目的
                    # status=PENDING_ACTUALS 意味着日后要与真实财报核对，
                    # 没有时间戳就无法判断预测做出的时点，样本失去可回溯性。
                    "submitted_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "predictions": {
                        "revenue_estimate": revenue_estimate,
                        "net_income_estimate": net_income_estimate,
                        "net_assets_estimate": net_assets_estimate,
                        "target_price": user_target_price
                    },
                    "user_logic_summary": user_logic if user_logic else "未填写具体逻辑",
                    "status": "PENDING_ACTUALS"
                }

                # Save to file
                try:
                    file_path = "predictions.json"
                    existing_data = []
                    if os.path.exists(file_path):
                        with open(file_path, "r", encoding="utf-8") as f:
                            try:
                                existing_data = json.load(f)
                            except Exception:
                                # V12：原来这里是裸 except + pass，损坏的库会被静默当成空库，
                                # 紧接着被下面的写入整体覆盖 —— 历史预测全部无声丢失。
                                # 现在先把损坏文件改名留档，再从空库继续。
                                existing_data = []
                                try:
                                    os.replace(file_path, file_path + ".corrupt")
                                    st.warning("⚠️ predictions.json 解析失败，已备份为 predictions.json.corrupt 后重建。")
                                except OSError:
                                    pass
                    if not isinstance(existing_data, list):
                        existing_data = []
                    existing_data.append(parsed_data)
                    # V12：先写临时文件再 os.replace 原子替换。
                    # 原写法用 "w" 直接截断目标文件，写入中途异常会把整个预测库清空。
                    _tmp = file_path + ".tmp"
                    with open(_tmp, "w", encoding="utf-8") as f:
                        json.dump(existing_data, f, ensure_ascii=False, indent=2)
                    os.replace(_tmp, file_path)
                    st.success("✅ 您的财务预期及推演合理目标价已录入众包数据库！底牌已揭晓！")
                    st.session_state[session_key] = True
                except Exception as e:
                    st.warning(f"数据落地存储失败: {e}")
                        
        # Display Stats if submitted (P2: 绘制一致预期目标价频率分布直方图)
        if st.session_state[session_key]:
            st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)
            st.markdown(f"##### 🔓 {ticker} 大众预测与市场一致预期")
            
            # Load all data for stats
            file_path = "predictions.json"
            ticker_data = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        all_d = json.load(f)
                        ticker_data = [d for d in all_d if d.get('ticker') == ticker]
                except:
                    pass
                    
            if not ticker_data:
                st.info("暂无足够的有效预测数据。")
                return
                
            rev_list = []
            income_list = []
            assets_list = []
            price_list = []
            logics = []
            
            for d in ticker_data:
                p = d.get('predictions', {})
                rev = p.get('revenue_estimate')
                inc = p.get('net_income_estimate')
                ast_val = p.get('net_assets_estimate')
                t_price = p.get('target_price')
                
                if isinstance(rev, (int, float)) and rev > 0: rev_list.append(rev)
                if isinstance(inc, (int, float)) and inc > 0: income_list.append(inc)
                if isinstance(ast_val, (int, float)) and ast_val > 0: assets_list.append(ast_val)
                if isinstance(t_price, (int, float)) and t_price > 0: price_list.append(t_price)
                
                logic = d.get('user_logic_summary')
                if logic and logic != "未填写具体逻辑":
                    logics.append(logic)
                    
            c1_s, c2_s, c3_s, c4_s = st.columns(4)
            
            if rev_list:
                med_rev = np.median(rev_list)
                c1_s.metric("一致预期营收 (中位数)", f"{med_rev:.2f} {unit_lbl}")
            else:
                c1_s.metric("一致预期营收", "N/A")
                
            if income_list:
                med_inc = np.median(income_list)
                c2_s.metric("一致预期净利润 (中位数)", f"{med_inc:.2f} {unit_lbl}")
            else:
                c2_s.metric("一致预期净利润", "N/A")
                
            if price_list:
                med_prc = np.median(price_list)
                c3_s.metric("一致预期合理股价 (中位数)", fmt_calc_price(med_prc))
            else:
                c3_s.metric("一致预期合理股价", "N/A")
                
            c4_s.metric("总参与预测人数", f"{len(ticker_data)} 人")
            
            # P2: 绘制目标价频率分布直方图 (Plotly Express Histogram)
            if price_list:
                df_hist = pd.DataFrame({'目标股价': price_list})
                fig_hist = px.histogram(
                    df_hist, 
                    x='目标股价', 
                    title="📊 市场一致预期（众包目标价分布）",
                    labels={'count': '预测频数'},
                    color_discrete_sequence=['#00F2FE'] # neon cyan
                )
                fig_hist.update_layout(
                    margin=dict(l=10, r=10, t=40, b=10),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    template='plotly_dark',
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', title=f"股价 ({price_lbl})"),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)', title="预测频数"),
                    showlegend=False
                )
                st.plotly_chart(apply_institutional_axes(fig_hist), width="stretch", key=f"crowd_price_hist_{ticker}")
            
            with st.expander("💬 查看大家的核心逻辑提炼 (最新10条)"):
                for idx, lg in enumerate(reversed(logics[-10:])):
                    st.markdown(f"- **玩家 {len(logics)-idx}**: {lg}")

# ============================================================================
# 模块别名兼容层：历史代码里的 fundamentals.xxx() / terminal_ui.xxx()
# 等限定式调用，在单文件版中一律指向本模块自身。
# ============================================================================
import sys as _sys_alias
_self_mod = _sys_alias.modules[__name__]
fundamentals = _self_mod
terminal_ui = _self_mod
macro_capital = _self_mod
market_tape = _self_mod
crowdsource_agent = _self_mod

# [已内联] import macro_capital
# [已内联] import crowdsource_agent
# [已内联] import market_tape
# [已内联] import fundamentals
# [已内联] import terminal_ui

# [单文件版] 原开发期的 importlib.reload(...) 模块热重载已移除：
# 所有模块代码现已内联至本文件，无外部模块可重载，调用会抛
# ModuleNotFoundError('__main__')。Streamlit 本身在保存文件后会自动重跑脚本，
# 因此热重载能力无损失。

# V7 深度基本面 / 数据净化引擎
# [已内联] from fundamentals import ( compute_advanced_metrics, fetch_industry_benchmark, fetch_insti
# V7 彭博化终端 UI 引擎
# [已内联] from terminal_ui import ( inject_terminal_css, render_command_center, render_kpi_grid, sec


# 初始化全局变量，防止 "name 'all_data' is not defined" 报错
all_data = {}
api_key_input = st.session_state.get("api_key_state", "")

# 注入全局 UI 优化 CSS 与前端全套防盗/防右键/防 F12 保护网
st.markdown("""
<style>
*, body, html {
    -webkit-user-select: none !important;
    -moz-user-select: none !important;
    -ms-user-select: none !important;
    user-select: none !important;
}
</style>

<script>
// 1. 禁用右键菜单 (Context Menu)
document.addEventListener('contextmenu', function(e) {
    e.preventDefault();
    return false;
}, false);

// 2. 禁用开发者工具与查看源码快捷键 (F12, Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+Shift+C, Ctrl+U, Ctrl+S)
document.addEventListener('keydown', function(e) {
    if (
        e.keyCode === 123 || 
        (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 74 || e.keyCode === 67)) ||
        (e.ctrlKey && (e.keyCode === 85 || e.keyCode === 83)) ||
        (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 74))
    ) {
        e.preventDefault();
        e.stopPropagation();
        return false;
    }
}, false);

// 3. 动态 debugger 陷阱，拦截 Console 调谐
setInterval(function() {
    (function(a) {
        return (function(a) {
            return (Function('debugger')());
        })(a);
    })();
}, 1000);

// ===== V10.2 反爬增强层 =====
// 4. 拦截复制/剪切/拖拽：页面内容不可被选中复制带走
document.addEventListener('copy', function(e) {
    e.clipboardData.setData('text/plain', '⚠️ 本终端内容受保护，禁止复制抓取');
    e.preventDefault();
    return false;
}, false);
document.addEventListener('cut', function(e) { e.preventDefault(); return false; }, false);
document.addEventListener('dragstart', function(e) { e.preventDefault(); return false; }, false);

// 5. 补充快捷键封锁：打印(Ctrl/Cmd+P)、全选(Ctrl/Cmd+A)
document.addEventListener('keydown', function(e) {
    var k = e.key ? e.key.toUpperCase() : '';
    if ((e.ctrlKey || e.metaKey) && (k === 'P' || k === 'p' || e.keyCode === 80 ||
                                     k === 'A' || k === 'a' || e.keyCode === 65)) {
        e.preventDefault();
        e.stopPropagation();
        return false;
    }
}, false);

// 6. 打印/另存为阅读模式时隐藏全部内容
(function() {
    var s = document.createElement('style');
    s.textContent = '@media print { body * { display: none !important; } body::after { content: "⚠️ 内容受保护，禁止打印"; display: block !important; font-size: 24px; padding: 40px; } }';
    document.head.appendChild(s);
})();

// V10.3 修复：移除原第 7 层"自动化指纹检测"——该防护会整体替换 body DOM，
// React 事后部分重挂载导致整页 UI/排版丢失只剩裸文字（用户实测 P1-P4 故障根源），
// 且对真爬虫无实际防御力（指纹可伪造），纯自伤式防护，予以拆除。
</script>

<style>
    /* 增加主容器的两侧边距，避免贴边，同时增加上下呼吸感 */
    /* V7 彭博化：全局极窄边距，数据密度最大化 */
    .block-container {
        padding-top: 0.85rem !important;
        padding-bottom: 1.2rem !important;
        padding-left: 1.1rem !important;
        padding-right: 1.1rem !important;
        max-width: 100% !important;
    }
    
    /* 隐藏默认 Header 和 Footer */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* V7：废弃"每个纵向块都变成大卡片"的松散排版，卡片化交由 terminal_ui 的 .tcard 网格统一承担 */
    div[data-testid="stVerticalBlock"] { gap: 0.5rem !important; }
    div[data-testid="stHorizontalBlock"] { gap: 0.55rem !important; }
    
    /* P4 & P5 Alignment & Financial Cards CSS injection */
    div[data-testid="stColumn"] > div > div[data-testid="stButton"] { margin-top: 27px !important; }
    
    /* V10 P7：固定 5 列网格 × 10 张卡 = 完美双排满格 */
    .financial-grid {
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 15px;
        margin-top: 15px;
        margin-bottom: 20px;
    }
    .fin-card {
        background: #1E222D !important;
        border: 1px solid #2B3139 !important;
        border-radius: 10px !important;
        padding: 15px !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: space-between !important;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3) !important;
    }
    .fin-label {
        font-size: 0.85rem !important;
        color: #94a3b8 !important;
        margin-bottom: 5px !important;
        font-weight: 500 !important;
    }
    .fin-value {
        font-size: 1.35rem !important;
        font-weight: 800 !important;
        color: #ffffff !important;
    }
    .fin-trend {
        font-size: 0.8rem !important;
        margin-top: 5px !important;
        font-weight: 600 !important;
    }
    /* V8 语义统一：上行=专业沉稳绿 #26A69A，下行=专业警示红 #EF5350 */
    .trend-up {
        color: #26A69A !important;
    }
    .trend-down {
        color: #EF5350 !important;
    }
    .trend-neutral {
        color: #94a3b8 !important;
    }

    /* V9 P6：Tabs 等宽平铺并居中，替换默认的左对齐挤压
       （实测 DOM：容器为 #stTabs/.stTabs，页签为 div[role="tab"]，非 button） */
    #stTabs div[role="tablist"], .stTabs div[role="tablist"] {
        display: flex;
        justify-content: center;
        width: 100%;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }
    #stTabs div[role="tab"], .stTabs div[role="tab"] {
        flex: 1;
        text-align: center;
        justify-content: center;
        background-color: transparent;
        border-radius: 8px 8px 0 0 !important;
    }

    /* V9 审美统一：卡片圆角一律 8/12px，杜绝刺眼白底穿透暗黑主题 */
    .fin-card, .tcard, .kpi-neon-card, .market-card,
    div[data-testid="stMetric"], .bg-card-glass {
        border-radius: 12px !important;
    }
    .gapbar-track { border-radius: 8px !important; }
    div[data-testid="stDataFrame"] { background: #171B26 !important; border-radius: 12px !important; }
    [data-testid="stExpander"] { background: transparent !important; border-radius: 12px !important; }
    [data-testid="stAlert"] { border-radius: 8px !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# V10 五·机构级玻璃拟态 + 高亮数值 + 动态涨跌语义色（跟随 A股/国际 切换）
# 说明：上一块是静态 CSS；本块用 f-string 把当前 C_UP/C_DOWN 注入覆盖层，
# 切换开关触发 rerun 后本块自动换色，全站 .trend-*/.market-chg-* 即时联动。
# ---------------------------------------------------------------------------
st.markdown(f"""
<style>
/* 深藏青枪灰背景体系 */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stHeader"] {{
    background: {C_BG_APP} !important;
}}
section[data-testid="stSidebar"] {{ background: {C_BG_PANEL} !important; }}

/* 玻璃拟态卡片：半透明底 + 毛玻璃 + 细亮边 + 柔和投影
   （body 前缀抬高优先级，压过后方终端 CSS 的同重要级旧色规则） */
body .fin-card, body .tcard, body .kpi-neon-card, body .market-card,
body div[data-testid="stMetric"], body .bg-card-glass {{
    background: rgba(30, 41, 59, 0.7) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    backdrop-filter: blur(10px) !important;
    -webkit-backdrop-filter: blur(10px) !important;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35) !important;
    border-radius: 12px !important;
}}

/* 指标数值高亮：核心数值统一青色霓虹，焦点信息一眼锁定 */
.fin-value {{ color: #00F2FE !important; text-shadow: 0 0 10px rgba(0, 242, 254, 0.25); }}
.kpi-neon-value {{ color: #00F2FE !important; text-shadow: 0 0 10px rgba(0, 242, 254, 0.25); }}
.gapbar-val {{ font-family: 'JetBrains Mono', monospace; }}

/* 涨跌语义色动态覆盖（默认 A 股：红涨绿跌；国际模式：绿涨红跌） */
.trend-up {{ color: {C_UP} !important; }}
.trend-down {{ color: {C_DOWN} !important; }}
.market-chg-up {{ color: {C_UP} !important; }}
.market-chg-down {{ color: {C_DOWN} !important; }}

/* V10 P6·Tabs 水平均分（机构指定样式，含 !important；
   同时保留上方 #stTabs div[role=tab] 规则以兼容本版 Streamlit 的 DOM） */
div[data-testid="stTabs"] button {{
    flex: 1 !important;
    text-align: center !important;
    font-weight: bold !important;
}}
#stTabs div[role="tab"], .stTabs div[role="tab"] {{
    flex: 1 !important;
    text-align: center !important;
    font-weight: bold !important;
}}

/* V10.1 排版系统：终结"文字墙"——标题带结构线、段落列表拉开行距、
   分割线渐变、数字输入器暗色卡片化，全站统一呼吸感与纵向节奏 */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {{
    margin-top: 1.5em !important;
    margin-bottom: 0.65em !important;
    letter-spacing: 0.3px;
    line-height: 1.35;
}}
.stMarkdown h2 {{
    padding-bottom: 9px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.09);
}}
.stMarkdown h3 {{
    padding-left: 11px;
    border-left: 3px solid #4B9FFF;
}}
.stMarkdown p {{
    line-height: 1.78 !important;
    margin-bottom: 0.75em !important;
}}
.stMarkdown ul, .stMarkdown ol {{
    margin: 0.5em 0 0.9em 0 !important;
    padding-left: 1.45em !important;
}}
.stMarkdown li {{
    line-height: 1.78 !important;
    margin-bottom: 0.5em !important;
}}
.stMarkdown hr {{
    border: none !important;
    height: 1px !important;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.16), transparent) !important;
    margin: 1.7em 0 !important;
}}
body [data-testid="stNumberInput"] {{
    background: rgba(30, 41, 59, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 10px;
    padding: 4px 10px;
}}
body [data-testid="stNumberInput"] label {{
    color: #8B93A7 !important;
    font-size: 0.82rem !important;
}}
/* 说明性 caption 与正文拉开层次 */
.stCaption, p.caption {{
    line-height: 1.6 !important;
    margin-top: 0.4em !important;
}}
/* V10.1 对齐系统：同排栏目等高拉伸，上下沿横向对齐；
   栏内垂直顶部对齐，杜绝高低参差 */
div[data-testid="stHorizontalBlock"] {{ align-items: stretch; }}
div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
    display: flex; flex-direction: column; justify-content: flex-start;
}}
/* V10.2 防爬水印：右下角固定标识，截图/存档溯源用 */
body::after {{
    content: "PROTECTED · 智能投研终端 · 内容受保护";
    position: fixed; right: 14px; bottom: 10px;
    font-size: 0.66rem; color: rgba(139, 147, 167, 0.38);
    letter-spacing: 1px; pointer-events: none; z-index: 9999;
}}
/* V11 · 图表配套分析段落样式（借鉴固收资金面日报的 .ana 模式）：
   左侧蓝色竖线 + 深底卡片，全站所有"图后解读"统一使用 */
.ana-note {{
    background: rgba(11, 17, 32, 0.55);
    border-left: 3px solid #4B9FFF;
    border-radius: 0 10px 10px 0;
    padding: 12px 16px;
    font-size: 0.85rem;
    line-height: 1.85;
    color: #D1D4DC;
    margin: 10px 0 6px 0;
}}
/* V11 · 表格机构细节（借鉴日报）：首列左对齐、数值列右对齐衬线体、行 hover */
.stMarkdown table {{ border-collapse: collapse; width: 100%; }}
.stMarkdown table th {{ color: #8B93A7; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.15); }}
.stMarkdown table th:first-child, .stMarkdown table td:first-child {{ text-align: left; }}
.stMarkdown table td:not(:first-child) {{
    text-align: right; font-family: 'Times New Roman', Times, serif;
}}
.stMarkdown table tr:hover td {{ background: rgba(75, 159, 255, 0.06); }}
</style>
""", unsafe_allow_html=True)

# V7 战役三：注入彭博化终端视觉系统（极窄边距 / 高密度卡片 / 语义化色彩）
inject_terminal_css()

# 模块按自上而下顺序直接渲染 (Task 2 Layout 重构)

# -------------------------------------------------------------------
# 0. 智能股票名称/中文映射解析引擎
# -------------------------------------------------------------------
STOCK_NAME_MAP = {
    # 美股核心热门标的
    "苹果": "AAPL", "苹果公司": "AAPL", "APPLE": "AAPL",
    "英伟达": "NVDA", "NVIDIA": "NVDA",
    "特斯拉": "TSLA", "TESLA": "TSLA",
    "微软": "MSFT", "MICROSOFT": "MSFT",
    "谷歌": "GOOGL", "GOOGLE": "GOOGL", "Alphabet": "GOOGL",
    "亚马逊": "AMZN", "AMAZON": "AMZN",
    "Meta": "META", "META": "META", "脸书": "META",
    "台积电": "TSM", "TSMC": "TSM",
    "博通": "AVGO", "AMD": "AMD", "超微半导体": "AMD",
    "高通": "QCOM", "美光": "MU", "美光科技": "MU",
    "超微电脑": "SMCI", "奈飞": "NFLX", "NETFLIX": "NFLX",
    "微软公司": "MSFT", "英特尔": "INTC",

    # A 股 & 港股全量核心龙头标的
    "三环集团": "300408.SZ", "三环": "300408.SZ",
    "新易盛": "300502.SZ", "中际旭创": "300308.SZ", "天孚通信": "300394.SZ", "光迅科技": "002281.SZ",
    "贵州茅台": "600519.SS", "茅台": "600519.SS", "五粮液": "000858.SZ", "泸州老窖": "000568.SZ",
    "宁德时代": "300750.SZ", "宁王": "300750.SZ", "亿纬锂能": "300014.SZ",
    "比亚迪": "002594.SZ", "长安汽车": "000625.SZ", "赛力斯": "601127.SS",
    "中芯国际": "688981.SS", "寒武纪": "688256.SS", "海光信息": "688041.SS",
    "立讯精密": "002475.SZ", "工业富联": "601138.SS", "歌尔股份": "002241.SZ",
    "海康威视": "002415.SZ", "大华股份": "002236.SZ",
    "招商银行": "600036.SS", "中国平安": "601318.SS", "中信证券": "600030.SS",
    "东方财富": "300059.SZ", "同花顺": "300033.SZ",
    "长江电力": "600900.SS", "中国神华": "601088.SS", "中国石油": "601857.SS",
    "万科A": "000002.SZ", "保利发展": "600048.SS",
    "兆易创新": "603986.SS", "韦尔股份": "603501.SS", "圣邦股份": "300661.SZ",
    "北方华创": "002371.SZ", "中微公司": "688012.SS", "拓荆科技": "688072.SS",
    "紫光国微": "002049.SZ", "长电科技": "600584.SS", "通富微电": "002156.SZ",
    "腾讯": "0700.HK", "腾讯控股": "0700.HK",
    "阿里巴巴": "BABA", "阿里": "BABA", "阿里港股": "9988.HK",
    "美团": "3690.HK", "小米": "1810.HK", "小米集团": "1810.HK",
    "百度": "BIDU", "京东": "JD", "拼多多": "PDD",

    # 日韩标的
    "三星": "005930.KS", "三星电子": "005930.KS",
    "丰田": "TM", "丰田汽车": "TM",
}

def resolve_ticker(raw_input):
    """智能解析输入，支持中文名称自动转换为美股/A股/港股标准Ticker代码"""
    if not raw_input:
        return "NVDA", ""
    raw = raw_input.strip()

    # 1. 直接精准匹配内置映射表
    if raw in STOCK_NAME_MAP:
        return STOCK_NAME_MAP[raw], raw

    # 2. 忽略大小写模糊查找
    for k, v in STOCK_NAME_MAP.items():
        if raw.lower() == k.lower():
            return v, k

    # 3. 在线搜索 A 股代码匹配 (支持输入任意 A 股中文简称)
    if not raw.isdigit() and len(raw) >= 2:
        try:
            import akshare as ak
            # V10.1：该接口无超时且周末/限流时会无限阻塞（实测挂起整页），
            # 套 15s 硬超时兜底；失败直接走后续纯数字补全/原样返回分支
            df_codes = _fetch_with_timeout(ak.stock_info_a_code_name,
                                           timeout_s=15, default=None)
            if df_codes is not None and not df_codes.empty:
                match = df_codes[df_codes['name'].str.contains(raw, case=False, na=False)]
                if not match.empty:
                    code = str(match['code'].iloc[0]).zfill(6)
                    suffix = ".SS" if code.startswith(('6', '9', '5')) else ".SZ"
                    return f"{code}{suffix}", match['name'].iloc[0]
        except Exception:
            pass

    # 4. 纯 6 位数字补全 A 股后缀
    if raw.isdigit():
        if len(raw) == 6:
            if raw.startswith(('6', '9', '5')):
                return f"{raw}.SS", raw
            else:
                return f"{raw}.SZ", raw
        elif len(raw) in (4, 5):
            return f"{raw.zfill(5)}.HK", raw

    return raw.upper(), raw

# -------------------------------------------------------------------
# 1. 页面基本配置与视觉系统
# -------------------------------------------------------------------
# (Moved to top of file)

# 2. 全局样式定制
st.markdown("""
<style>
    .event-expectation { font-size: 0.82rem; opacity: 0.85; color: #fbbf24; }
    .event-analysis-title { font-weight: 600; font-size: 0.85rem; color: #4B9FFF; margin-bottom: 0.2rem; }
    .event-analysis-text { font-size: 0.85rem; opacity: 0.88; line-height: 1.5; color: var(--text-color, #e2e8f0); }

    /* 4 宫格分析师目标价卡片 */
    .grid-2x2-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(226,232,240,0.15);
        border-radius: 12px;
        padding: 0.7rem 0.8rem;
        text-align: center;
        margin-bottom: 0.6rem;
        height: 76px;
        display: flex; flex-direction: column; justify-content: center; align-items: center;
    }
    .grid-2x2-label { font-size: 0.78rem; opacity: 0.75; margin-bottom: 0.15rem; font-weight: 500; color: var(--text-color, inherit); }
    .grid-2x2-value { font-size: 1.15rem; font-weight: 700; color: #00b865; }

    /* V12：宏观大事日历 —— 非农/FOMC/CPI 属一级行情驱动数据，
       旧版按钮文字被强行居中挤成小字并互相压行，这里统一放大字号并左对齐。 */
    .mcal-col-title { font-size: 0.92rem; color: #C7D0E0; font-weight: 700; margin-bottom: 8px; line-height: 1.5; }
    div[class*="st-key-mcal_btn_"] button {
        text-align: left !important;
        justify-content: flex-start !important;
        padding: 10px 14px !important;
        min-height: 62px !important;
        margin-bottom: 6px !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        border-radius: 10px !important;
        line-height: 1.45 !important;
        white-space: normal !important;
    }
    div[class*="st-key-mcal_btn_"] button p {
        text-align: left !important;
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        line-height: 1.45 !important;
        margin: 0 !important;
    }
    div[class*="st-key-mcal_btn_"] button p:first-child {
        font-size: 0.78rem !important;
        font-weight: 700 !important;
        color: #8B93A7 !important;
        letter-spacing: 0.4px;
        margin-bottom: 2px !important;
    }
    .mcal-detail { background:#1E222D; border:1px solid #2B3139; border-radius:12px; padding:20px; margin-bottom:12px; }
    .mcal-banner {
        background: rgba(239,68,68,0.15); border: 1px solid #FF4B4B; color: #FF4B4B;
        padding: 8px 14px; border-radius: 8px; font-weight: 700; margin-bottom: 14px; font-size: 0.95rem;
    }
    .mcal-meta { font-size: 0.8rem; color: #8B93A7; }
    .mcal-title { font-size: 1.55rem; font-weight: 800; color: #F0F3FA; margin: 8px 0 14px 0; line-height: 1.35; }
    .mcal-cells { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px; margin-bottom: 12px; }
    .mcal-cell {
        background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px; padding: 10px 14px;
    }
    .mcal-cell-hl { background: rgba(0,242,254,0.06); border-color: rgba(0,242,254,0.22); }
    .mcal-cell-label { font-size: 0.78rem; color: #8B93A7; margin-bottom: 2px; }
    .mcal-cell-value {
        font-size: 1.6rem; font-weight: 800; color: #F0F3FA;
        font-family: 'JetBrains Mono', 'Consolas', monospace; line-height: 1.25;
    }
    .mcal-surprise {
        display: inline-block; border: 1px solid; border-radius: 8px;
        padding: 5px 12px; font-size: 0.88rem; font-weight: 700; margin-bottom: 10px;
    }
    .mcal-src { font-size: 0.78rem; color: #8B93A7; line-height: 1.6; }

    /* V12：利率四联快览 —— 等高网格，对齐由 grid 保证，不受 Streamlit 列高影响 */
    .rate-kpi-grid {
        display: grid;
        grid-template-columns: 1.3fr 1fr 1fr 1fr 1.1fr;
        gap: 10px;
        margin: 10px 0 4px 0;
        align-items: stretch;
    }
    @media (max-width: 1500px) { .rate-kpi-grid { grid-template-columns: repeat(3, minmax(0,1fr)); } }
    @media (max-width: 1100px) { .rate-kpi-grid { grid-template-columns: repeat(2, minmax(0,1fr)); } }
    @media (max-width: 640px)  { .rate-kpi-grid { grid-template-columns: 1fr; } }
    .rate-kpi {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 12px;
        padding: 14px 18px;
        display: flex; flex-direction: column; justify-content: space-between;
        min-height: 132px;
    }
    .rate-kpi-primary { border-color: rgba(0,242,254,0.35); background: rgba(0,242,254,0.06); }
    .rate-kpi-label { font-size: 0.78rem; color: #8B93A7; letter-spacing: 0.5px; line-height: 1.4; }
    .rate-kpi-value {
        font-size: 2.0rem; font-weight: 900; color: #F0F3FA; line-height: 1.2;
        font-family: 'JetBrains Mono', 'Consolas', monospace; margin: 6px 0 4px 0;
    }
    .rate-kpi-primary .rate-kpi-value { font-size: 2.5rem; color: #00F2FE; text-shadow: 0 0 18px rgba(0,242,254,0.28); }
    .rate-kpi-unit { font-size: 1.05rem; font-weight: 700; opacity: 0.8; margin-left: 2px; }
    .rate-kpi-sub { font-size: 0.74rem; color: #8B93A7; line-height: 1.55; }
    .rate-kpi-na { font-size: 1.35rem; font-weight: 700; color: #64748b; }

    /* V12：列内对齐交还给各 st.columns(vertical_alignment=...) 自行决定。
       旧版此处用 justify-content:flex-end !important 强制所有列底端对齐，
       会覆盖全站所有 vertical_alignment="top"，把 KPI 卡片推到列底部，
       与相邻列上沿错位（现金流穿透、资金面监控室等多处留白即源于此）。 */

    /* V12：Streamlit 不会把 key 渲染成 button 的 HTML 属性，
       button[key="..."] 选择器永远不命中；正确锚点是包裹层的 .st-key-<key> 类。 */
    div.st-key-btn_main_generate button {
        background-color: #00b865 !important;
        color: white !important;
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        height: 40px !important;
        border-radius: 8px !important;
        width: 100% !important;
        border: none !important;
        margin-top: 28px !important;
        margin-bottom: 0 !important;
    }
    div.st-key-btn_main_generate button:hover { background-color: #009e56 !important; }

    .news-positive { border-left: 4px solid #26A69A; background: rgba(38,166,154,0.08); padding: 0.7rem 1rem; border-radius: 8px; margin-bottom: 0.5rem; }
    .news-negative { border-left: 4px solid #EF5350; background: rgba(239,83,80,0.08); padding: 0.7rem 1rem; border-radius: 8px; margin-bottom: 0.5rem; }
    .news-neutral { border-left: 4px solid #64748b; background: rgba(100,116,139,0.06); padding: 0.7rem 1rem; border-radius: 8px; margin-bottom: 0.5rem; }
    .news-title { font-weight: 600; font-size: 0.9rem; margin-bottom: 0.2rem; color: var(--text-color, inherit); }
    .news-meta { font-size: 0.78rem; opacity: 0.65; }

    .calendar-item {
        display: flex; align-items: center; gap: 1rem;
        padding: 0.7rem 1rem; border-radius: 10px;
        border: 1px solid rgba(226,232,240,0.15);
        margin-bottom: 0.5rem; background: rgba(255,255,255,0.03);
    }
    .calendar-date { font-weight: 700; font-size: 0.95rem; min-width: 80px; color: #00b865; }
    .calendar-desc { font-size: 0.88rem; color: var(--text-color, inherit); }

    /* 让 Markdown 表格 100% 全宽自适应，彻底消灭左侧挤压 */
    div[data-testid="stMarkdownContainer"] table {
        width: 100% !important;
        display: table !important;
        border-collapse: collapse !important;
        margin: 0.8rem 0 !important;
        background: rgba(255,255,255,0.02) !important;
        border-radius: 8px !important;
        overflow: hidden !important;
    }
    div[data-testid="stMarkdownContainer"] th {
        background: rgba(0, 184, 101, 0.15) !important;
        color: #00b865 !important;
        font-weight: 700 !important;
        padding: 0.65rem 0.8rem !important;
        border-bottom: 1px solid rgba(226,232,240,0.15) !important;
    }
    div[data-testid="stMarkdownContainer"] td {
        padding: 0.6rem 0.8rem !important;
        border-bottom: 1px solid rgba(226,232,240,0.08) !important;
    }

    /* ☀️ Streamlit Light Mode 浅色/白色主题下的文字与卡片黑字显色强防护 */
    [data-theme="light"] .header-title,
    [data-theme="light"] .market-index,
    [data-theme="light"] .metric-value,
    [data-theme="light"] .event-title,
    [data-theme="light"] .calendar-desc {
        color: #0f172a !important;
    }

    [data-theme="light"] .header-subtitle,
    [data-theme="light"] .market-name,
    [data-theme="light"] .market-sector,
    [data-theme="light"] .metric-label,
    [data-theme="light"] .grid-2x2-label,
    [data-theme="light"] .event-analysis-text {
        color: #334155 !important;
    }

    [data-theme="light"] .market-card,
    [data-theme="light"] .metric-card,
    [data-theme="light"] .grid-2x2-card,
    [data-theme="light"] .event-card-row,
    [data-theme="light"] .calendar-item {
        background: #f8fafc !important;
        border-color: #cbd5e1 !important;
        box-shadow: 0 2px 6px rgba(15,23,42,0.05) !important;
    }

    [data-theme="light"] div[data-testid="stMarkdownContainer"] table {
        background: #ffffff !important;
        color: #0f172a !important;
        border: 1px solid #e2e8f0 !important;
    }

    [data-theme="light"] div[data-testid="stMarkdownContainer"] td {
        color: #1e293b !important;
        border-bottom: 1px solid #e2e8f0 !important;
    }

    /* 研报正文双列专效顶头平齐法则 */
    div[data-testid="stColumn"]:has(div.stMarkdown) > div[data-testid="stVerticalBlock"] {
        justify-content: flex-start !important;
        align-items: stretch !important;
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    div[data-testid="stColumn"]:has(div.stMarkdown) > div[data-testid="stVerticalBlock"] > div.stMarkdown:first-child,
    div[data-testid="stColumn"]:has(div.stMarkdown) > div[data-testid="stVerticalBlock"] > div.stMarkdown:first-child * {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }

    /* 🏷️ v2.0 数据可信度视觉语言：真实数据 vs AI生成内容区分样式 */
    .data-real-badge {
        display: inline-block; font-size: 0.7rem; font-weight: 700;
        background: rgba(0,184,101,0.15); color: #00b865;
        border: 1px solid rgba(0,184,101,0.4);
        padding: 1px 8px; border-radius: 6px; margin-left: 6px;
    }
    .data-ai-badge {
        display: inline-block; font-size: 0.7rem; font-weight: 700;
        background: rgba(251,191,36,0.15); color: #fbbf24;
        border: 1px dashed rgba(251,191,36,0.5);
        padding: 1px 8px; border-radius: 6px; margin-left: 6px;
    }

    /* 全球市场卡片样式 */
    .market-card {
        background: #1E222D !important;
        border: 1px solid #2B3139 !important;
        border-radius: 12px !important;
        padding: 0.9rem 1rem !important;
        text-align: center !important;
        position: relative !important;
        overflow: hidden !important;
        margin-bottom: 0.5rem !important;
    }
    .market-card-hot {
        border-color: rgba(0, 242, 254, 0.5) !important;
        box-shadow: 0 0 12px rgba(0, 242, 254, 0.15) !important;
    }
    .market-flag { font-size: 1.4rem; margin-bottom: 0.2rem; }
    .market-name { font-size: 0.8rem; font-weight: 600; opacity: 0.85; margin: 0.15rem 0; color: #94A3B8; }
    .market-index { font-size: 1.15rem; font-weight: 700; color: #F0F4F8; }
    .market-chg-up { color: #26A69A; font-size: 0.82rem; font-weight: 600; }
    .market-chg-down { color: #EF5350; font-size: 0.82rem; font-weight: 600; }
    .market-sector { font-size: 0.72rem; opacity: 0.75; margin-top: 0.3rem; color: #64748B; }
    .market-badge-hot {
        position: absolute; top: 6px; right: 8px;
        background: #00F2FE; color: #0A0D14; font-size: 0.6rem; font-weight: 700;
        padding: 1px 6px; border-radius: 6px;
    }

    /* 📅 大事日历左右对照样式 */
    .event-card-row {
        background: rgba(22, 27, 38, 0.75);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.8rem;
        display: flex;
        align-items: center;
        gap: 1.2rem;
        transition: all 0.2s ease;
    }
    .event-left-box {
        flex: 0 0 42%;
        border-right: 1px dashed rgba(255, 255, 255, 0.15);
        padding-right: 1rem;
    }
    .event-right-box {
        flex: 1;
        padding-left: 0.5rem;
    }
    .event-date-badge {
        display: inline-block;
        background: rgba(0, 242, 254, 0.15);
        color: #00F2FE;
        font-weight: 700;
        font-size: 0.82rem;
        padding: 2px 8px;
        border-radius: 6px;
        margin-bottom: 0.3rem;
    }
    .event-title { font-weight: 700; font-size: 0.95rem; color: #F0F4F8; margin-bottom: 0.25rem; }
    .event-expectation { font-size: 0.82rem; opacity: 0.85; color: #fbbf24; }
    .event-analysis-title { font-weight: 600; font-size: 0.85rem; color: #00F2FE; margin-bottom: 0.2rem; }
    .event-analysis-text { font-size: 0.85rem; opacity: 0.88; line-height: 1.5; color: #94A3B8; }

    /* 修复：spacer 类此前从未定义，导致所有 <div class="spacer-*"> 实际不产生任何间距 */
    .spacer-sm { height: 0.6rem; }
    .spacer-md { height: 1.2rem; }
    .spacer-lg { height: 2rem; }

    /* 产业链图谱：宽屏横向 Grid + 居中箭头，窄屏自动切换为纵向堆叠，箭头随之旋转90° */
    .chain-grid {
        display: grid;
        grid-template-columns: 1fr auto 1.2fr auto 1fr;
        align-items: stretch;
        gap: 6px;
    }
    .chain-arrow {
        display: flex; align-items: center; justify-content: center;
        font-size: 1.8rem; color: #475569; opacity: 0.6;
    }
    @media (max-width: 900px) {
        .chain-grid { grid-template-columns: 1fr; }
        .chain-arrow { transform: rotate(90deg); padding: 6px 0; }
    }

    /* Tab 内容区呼吸感统一 */
    div[data-baseweb="tab-panel"] { padding-top: 1.2rem; }

    /* 估值分位数进度条 */
    .percentile-track {
        position: relative; width: 100%; height: 10px; border-radius: 6px;
        background: linear-gradient(90deg, #26A69A 0%, #FF9800 50%, #EF5350 100%);
        margin: 10px 0 4px 0; opacity: 0.85;
    }
    .percentile-marker {
        position: absolute; top: -5px; width: 3px; height: 20px;
        background: #ffffff; box-shadow: 0 0 6px rgba(255,255,255,0.8);
        transform: translateX(-50%);
    }
    .kpi-neon-card {
        background: #1E222D; border: 1px solid #2B3139;
        border-radius: 10px; padding: 0.85rem; text-align: center; height: 100%;
    }
    .kpi-neon-label { font-size: 0.76rem; color: #8B93A7; margin-bottom: 0.35rem; }
    .kpi-neon-value { font-size: 1.5rem; font-weight: 900; color: #4B9FFF; }
    /* V8 估值水位差横向进度条 */
    .gapbar-wrap { margin: 6px 0 10px 0; }
    .gapbar-row { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
    .gapbar-label { flex: 0 0 128px; font-size:0.76rem; color:#8B93A7; font-weight:600; }
    .gapbar-track { flex:1; position:relative; height:18px; background:#171B26;
                    border:1px solid #2B3139; border-radius:5px; overflow:hidden; }
    .gapbar-fill { position:absolute; top:0; bottom:0; opacity:0.85; }
    .gapbar-mid { position:absolute; top:-2px; bottom:-2px; width:2px; background:#8B93A7; left:50%; }
    .gapbar-val { flex:0 0 168px; font-size:0.78rem; font-weight:700; text-align:right; }

</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# 2. 全球市场实时数据采集
# -------------------------------------------------------------------
@st.cache_data(ttl=180, show_spinner=False)
def fetch_global_markets():
    """抓取全球主要市场指数实时数据与板块主线"""
    indices = {
        'US 美股': {
            'flag': '🇺🇸',
            'tickers': {'^GSPC': 'SP500', '^IXIC': 'NASDAQ'},
            'sectors': {'XLK': '科技', 'XLE': '能源', 'XLF': '金融', 'XLV': '医疗', 'XLY': '消费', 'XLI': '工业', 'XLRE': '地产', 'XLC': '通信'},
            'default_sector': '',
        },
        'JP 日股': {'flag': '🇯🇵', 'tickers': {'^N225': '日经225'}, 'sectors': {}, 'default_sector': '半导体/汽车'},
        'KR 韩股': {'flag': '🇰🇷', 'tickers': {'^KS11': 'KOSPI'}, 'sectors': {}, 'default_sector': '半导体/造船'},
        'CN A股': {'flag': '🇨🇳', 'tickers': {'000001.SS': '上证指数'}, 'sectors': {}, 'default_sector': 'AI/新能源'},
    }
    results = {}
    hot_sector = {'name': '未知', 'chg': 0}

    for region, cfg in indices.items():
        region_data = {}
        for tk, label in cfg['tickers'].items():
            try:
                t = yf.Ticker(tk)
                h = t.history(period='2d')
                if len(h) >= 2:
                    prev_close = float(h['Close'].iloc[-2])
                    cur_close = float(h['Close'].iloc[-1])
                    if pd.isna(cur_close): cur_close = prev_close
                    chg_pct = (cur_close - prev_close) / prev_close * 100 if prev_close and not pd.isna(prev_close) else 0
                    if pd.isna(chg_pct): chg_pct = 0
                    region_data[label] = {'price': cur_close, 'chg': chg_pct}
                elif len(h) == 1:
                    cur_close = float(h['Close'].iloc[-1])
                    if pd.isna(cur_close): cur_close = 0
                    region_data[label] = {'price': cur_close, 'chg': 0}
            except Exception:
                region_data[label] = {'price': 0, 'chg': 0}
        # 板块主线（仅美股有 ETF 数据）
        sector_leader = ''
        for stk, sname in cfg.get('sectors', {}).items():
            try:
                t = yf.Ticker(stk)
                h = t.history(period='2d')
                if len(h) >= 2:
                    chg = (h['Close'].iloc[-1] - h['Close'].iloc[-2]) / h['Close'].iloc[-2] * 100
                    if chg > hot_sector['chg']:
                        hot_sector = {'name': sname, 'chg': chg}
                    if not sector_leader or chg > 0:
                        sector_leader = f"{sname} {chg:+.1f}%"
            except Exception:
                pass
        if not sector_leader:
            sector_leader = cfg.get('default_sector', '')
        results[region] = {'data': region_data, 'sector': sector_leader, 'flag': cfg.get('flag', '')}
    return results, hot_sector

@st.cache_data(ttl=300, show_spinner=False)
def fetch_hot_stocks():
    """基于实时涨幅/成交量抓取热门标的（精细 20 根 K线缩略图数据）
    V10 P8：候选池全面 A 股化——只保留 A 股核心资产（消费/新能源/算力/半导体/金融），
    剔除全部美股与港股候选，贴合 A 股投研终端定位。"""
    candidates = {
        '贵州茅台': '600519.SS', '宁德时代': '300750.SZ', '中际旭创': '300308.SZ',
        '新易盛': '300502.SZ', '比亚迪': '002594.SZ', '中芯国际': '688981.SS',
        '招商银行': '600036.SS', '长江电力': '600900.SS', '立讯精密': '002475.SZ',
        '京东方A': '000725.SZ', '海光信息': '688041.SS', '恒瑞医药': '600276.SS',
    }
    hot_list = []
    for name, tk in candidates.items():
        try:
            t = yf.Ticker(tk)
            h = t.history(period='1mo')
            if len(h) >= 1:
                h_20 = h.tail(20)
                chg = ((h['Close'].iloc[-1] - h['Close'].iloc[-2]) / h['Close'].iloc[-2] * 100) if len(h) >= 2 else 0.0
                vol = h['Volume'].iloc[-1]
                ohlc = {
                    'open': h_20['Open'].tolist(),
                    'high': h_20['High'].tolist(),
                    'low': h_20['Low'].tolist(),
                    'close': h_20['Close'].tolist(),
                }
                hot_list.append({'name': name, 'ticker': tk, 'chg': chg, 'vol': vol, 'ohlc': ohlc})
        except Exception:
            hot_list.append({'name': name, 'ticker': tk, 'chg': 0, 'vol': 0, 'ohlc': {}})
    hot_list.sort(key=lambda x: x['vol'], reverse=True)
    return hot_list

# -------------------------------------------------------------------
# V12 Bloomberg Edition：顶部实时快讯带（Live Ribbon）
# -------------------------------------------------------------------
def render_live_ribbon(n_top: int = 3, n_drawer: int = 10):
    """导航栏下方的全宽实时快讯条：常驻 3 条，点击展开最近 10 条抽屉。

    复用 fetch_cls_news() 已缓存的结果（财联社 / 同花顺 / 百度多源合并），
    不额外发起网络请求。标题来自外部接口，必须转义后再插入 HTML——
    否则一条含尖括号的电报就能破坏整个页面结构。
    """
    import html as _html
    try:
        news = fetch_cls_news() or []
    except Exception:
        news = []
    if not news:
        return
    top = news[:n_top]
    items = "".join(
        f'<span class="bb-ribbon-item"><span class="t">{_html.escape(str(n.get("发布时间") or "")[:5])}</span>'
        f'{_html.escape(str(n.get("标题") or "")[:46])}</span>'
        for n in top)
    drawer = "".join(
        f'<div class="bb-news-item"><span class="bb-news-time">'
        f'{_html.escape(str(n.get("发布日期") or ""))} {_html.escape(str(n.get("发布时间") or "")[:5])}</span>'
        f'<span>{_html.escape(str(n.get("标题") or "")[:110])}</span></div>'
        for n in news[:n_drawer])
    st.html(
        f'<div class="bb-ribbon">'
        f'<div class="bb-ribbon-tag"><span class="bb-badge-live">Live Feed</span></div>'
        f'<div class="bb-ribbon-body">{items}</div></div>'
        f'<details style="margin:-6px 0 12px 0;">'
        f'<summary style="cursor:pointer;font-size:0.7rem;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:0.5px;color:{C_NEUTRAL};'
        f'list-style:none;padding:2px 0;">▾ 展开最近 {n_drawer} 条快讯</summary>'
        f'<div class="bb-card" style="margin-top:6px;">{drawer}</div></details>')


# -------------------------------------------------------------------
# 3. 顶部 Hero Header (Anti Stock Report)
# -------------------------------------------------------------------
st.markdown(f"""
<div style="display:flex; align-items:center; justify-content:space-between;
            border-bottom:1px solid {C_BORDER}; border-top:2px solid {C_BB_ORANGE};
            padding:0.75rem 0 0.7rem 0; margin-bottom:0.9rem;">
    <div style="display:flex; align-items:baseline; gap:0.7rem;">
        <span class="bb-header" style="font-size:1.5rem;">
            <span style="color:#00b865;">Anti</span>Stock Terminal
        </span>
        <span class="bb-label">V12 · Bloomberg Edition</span>
    </div>
    <div class="bb-label-mute">客观数据聚合引擎 · 全球市场主线 · 零主观预测</div>
</div>
""", unsafe_allow_html=True)
st.caption("⚠️ 本终端仅做客观公开数据聚合与可视化，绝不生成任何投资评级、目标价推荐或仓位建议。")

# V12：导航栏下方实时快讯带
try:
    render_live_ribbon()
except Exception as e:
    print("[live_ribbon ERROR]", repr(e))

# -------------------------------------------------------------------
# 第一层：标的搜索栏 + API Key + 生成按钮（V8 全局渲染顺序重排：置于首屏）
# -------------------------------------------------------------------
if "selected_ticker" not in st.session_state:
    # V10 P8：默认标的改为 A 股核心资产贵州茅台（终端定位 A 股化）
    st.session_state.selected_ticker = "600519.SS"

# V10：四栏首屏——搜索框 / API Key / 生成按钮 / 涨跌语义切换
set_c1, set_c2, set_c3, set_c4 = st.columns([2.8, 1.8, 1.4, 1.5], vertical_alignment="bottom")
with set_c1:
    user_ticker_raw = st.text_input("🔎 标的代码 / 简称 (例如 AAPL, 600519.SS, 贵州茅台)",
                                    value=st.session_state.selected_ticker)
with set_c2:
    api_key_input_val = st.text_input("API 密钥 (必填)", value=api_key_input,
                                      type="password", key="api_key_state")
    api_key_input = api_key_input_val
with set_c3:
    generate_btn = st.button("🚀 生成研报", key="btn_main_generate", width="stretch")
with set_c4:
    # V10 五：A股红涨绿跌（默认）↔ 国际绿涨红跌 一键切换，全站图表与语义色联动
    st.toggle("国际配色 (绿涨红跌)", value=False, key="intl_color_mode",
              help="默认 A 股口径：红=涨、绿=跌；开启后切换为国际口径：绿=涨、红=跌。全站图表即时联动。")

st.markdown('<div class="spacer-sm"></div>', unsafe_allow_html=True)

# -------------------------------------------------------------------
# 4. 全球市场主线概览 + 热门标的 + 设置（全部在主区域）
# -------------------------------------------------------------------
with st.spinner("🌐 正在接入全球市场实时数据..."):
    global_markets, hot_sector_info = fetch_global_markets()
    hot_stocks_list = fetch_hot_stocks()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_riskfree_rate():
    """无风险利率锚：中国 10Y 国债收益率。
    首选东财中美国债序列（附带美债 10Y 可算利差）；降级中债收益率曲线 10Y。"""
    try:
        _sd = (datetime.datetime.now() - datetime.timedelta(days=40)).strftime("%Y%m%d")
        df = _fetch_with_timeout(ak.bond_zh_us_rate, kwargs={"start_date": _sd},
                                 timeout_s=25, default=None)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty and "中国国债收益率10年" in df.columns:
            d = df.dropna(subset=["中国国债收益率10年"])
            if not d.empty:
                row, prev = d.iloc[-1], (d.iloc[-2] if len(d) > 1 else None)
                # V12：中美利差必须取"两边都有报价的同一天"。
                # 东财序列里美债 10Y 比中债晚一个交易日发布，最新一行的美债列常为 NaN；
                # 旧写法只对中债列 dropna 后取最后一行，于是 us10 几乎永远是 None，
                # 中美利差卡片长期空白（P2 右侧那一大块留白即源于此）。
                both = df.dropna(subset=["中国国债收益率10年", "美国国债收益率10年"])
                us10 = us10_date = us10_cn = None
                if not both.empty:
                    _b = both.iloc[-1]
                    try:
                        us10 = float(_b["美国国债收益率10年"])
                        us10_cn = float(_b["中国国债收益率10年"])
                        us10_date = str(_b["日期"])
                    except Exception:
                        us10 = us10_date = us10_cn = None
                return dict(date=str(row["日期"]), cn10=float(row["中国国债收益率10年"]),
                            cn10_prev=(float(prev["中国国债收益率10年"]) if prev is not None else None),
                            us10=us10, us10_date=us10_date, us10_cn=us10_cn,
                            source="东方财富·中美国债收益率序列")
    except Exception:
        pass
    try:
        _end = datetime.datetime.now()
        _start = _end - datetime.timedelta(days=12)
        df = _fetch_with_timeout(ak.bond_china_yield,
                                 kwargs={"start_date": _start.strftime("%Y%m%d"),
                                         "end_date": _end.strftime("%Y%m%d")},
                                 timeout_s=25, default=None)
        if df is not None and not df.empty:
            c = df[df["曲线名称"].astype(str).str.contains("国债")]
            if not c.empty and "10年" in c.columns:
                row = c.dropna(subset=["10年"]).iloc[-1]
                return dict(date=str(row["日期"]), cn10=float(row["10年"]),
                            cn10_prev=None, us10=None, source="中债·国债收益率曲线")
    except Exception:
        pass
    return None



# ---------------------------------------------------------------------------
# V12 Bloomberg Edition：跨资产表现矩阵（Cross-Asset Heat Matrix）
# ---------------------------------------------------------------------------
# 数据源经逐一实测确认（2026-09）：
#   CL=F / GC=F / ^TNX / CNY=X  → 有完整日线序列，可算涨跌幅与迷你趋势线
#   XIN9.FGI（富时中国A50）     → 仅返回单点现价，无历史序列
#   CNH=X（离岸人民币）          → 同样仅单点，故改用 CNY=X 并如实标注为在岸口径
# akshare 的 futures_foreign_commodity_realtime 当前版本抛
# "Length mismatch" 内部错误，不可用；故商品口径统一走 yfinance。
# 拿不到历史的资产照常展示现价，趋势列显式标注缺失，绝不用任何推算值填充。
# ---------------------------------------------------------------------------
_CROSS_ASSETS = [
    ("WTI 原油",       "CL=F",      "NYMEX · 美元/桶",      2),
    ("COMEX 黄金",     "GC=F",      "COMEX · 美元/盎司",    2),
    ("美债 10Y",       "^TNX",      "US Treasury · %",      3),
    ("美元/人民币",     "CNY=X",     "在岸中间价口径",        4),
    ("富时中国 A50",   "XIN9.FGI",  "SGX 期货 · 点",        2),
]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_cross_asset_matrix(n_days: int = 5):
    """大类资产快照：最新价 / 日内涨跌幅 / 近 N 日收盘序列。

    每个标的独立 try 包裹——单一资产取数失败不得影响其余行的渲染。
    """
    rows = []
    for name, tk, sub, dp in _CROSS_ASSETS:
        rec = dict(name=name, ticker=tk, sub=sub, dp=dp,
                   last=None, chg_pct=None, spark=[])
        try:
            h = _fetch_with_timeout(
                lambda _t=tk: yf.Ticker(_t).history(period="1mo", interval="1d"),
                timeout_s=20, default=None)
            if h is not None and not h.empty and "Close" in h.columns:
                c = h["Close"].dropna()
                if len(c) >= 1:
                    rec["last"] = float(c.iloc[-1])
                if len(c) >= 2:
                    rec["chg_pct"] = float((c.iloc[-1] / c.iloc[-2] - 1) * 100)
                    rec["spark"] = [float(x) for x in c.tail(n_days).tolist()]
        except Exception:
            pass
        rows.append(rec)

    # 中债 10Y 复用资金面监控室已有的取数（东财中美国债序列），避免重复请求
    try:
        _rf = fetch_riskfree_rate()
        if _rf and _rf.get("cn10") is not None:
            _prev = _rf.get("cn10_prev")
            rows.insert(3, dict(
                name="中债 10Y", ticker="CGB10Y", sub=f"{_rf.get('source','')} · %", dp=4,
                last=float(_rf["cn10"]),
                chg_pct=(float((_rf["cn10"] / _prev - 1) * 100) if _prev else None),
                spark=[]))
    except Exception:
        pass
    return rows


def _bb_sparkline(vals, up: bool, h: int = 22) -> str:
    """迷你趋势线：用 div 微型柱阵实现。

    实测 Streamlit 的 HTML 消毒器会把 <svg> 整个剥离（同一单元格内纯文本
    span 正常渲染、polyline 却消失），故不能用 SVG；Plotly 为 5 个点各起一个
    图表实例开销也不合理。这里退回纯 div + inline style，全站已大量验证可渲染。
    """
    if not vals or len(vals) < 2:
        return '<span class="bb-na">历史缺失</span>'
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    col = C_UP if up else C_DOWN
    bars = "".join(
        f'<div style="width:5px;height:{3 + ((v - lo) / rng) * (h - 5):.1f}px;'
        f'background:{col};opacity:{0.45 + 0.55 * (i + 1) / len(vals):.2f};'
        f'border-radius:1px;"></div>'
        for i, v in enumerate(vals))
    return (f'<div style="display:inline-flex;align-items:flex-end;gap:2px;'
            f'height:{h}px;vertical-align:middle;">{bars}</div>')


def render_cross_asset_matrix():
    """彭博式大类资产矩阵：紧凑表格 + 等宽数字 + 迷你趋势线。"""
    rows = fetch_cross_asset_matrix()
    st.markdown(
        '<div style="display:flex;align-items:baseline;gap:10px;margin:2px 0 8px 0;">'
        '<span class="bb-header" style="font-size:1.15rem;">跨资产表现矩阵</span>'
        '<span class="bb-label">CROSS-ASSET · DAILY</span></div>',
        unsafe_allow_html=True)

    body = ""
    for r in rows:
        if r["last"] is None:
            val_cell = '<span class="bb-na">取数失败</span>'
            chg_cell = '<span class="bb-na">—</span>'
            spark_cell = '<span class="bb-na">—</span>'
        else:
            val_cell = f'<span class="bb-num">{r["last"]:,.{r["dp"]}f}</span>'
            if r["chg_pct"] is None:
                chg_cell = '<span class="bb-na">无前收</span>'
                spark_cell = '<span class="bb-na">历史缺失</span>'
            else:
                _up = r["chg_pct"] >= 0
                _c = C_UP if _up else C_DOWN
                chg_cell = (f'<span class="bb-num" style="color:{_c};">'
                            f'{r["chg_pct"]:+.2f}%</span>')
                spark_cell = _bb_sparkline(r["spark"], _up)
        body += (f'<tr><td><span class="bb-asset-name">{r["name"]}</span><br>'
                 f'<span class="bb-asset-sub">{r["sub"]}</span></td>'
                 f'<td>{val_cell}</td><td>{chg_cell}</td>'
                 f'<td style="text-align:right;">{spark_cell}</td></tr>')

    st.html(
        '<div class="bb-card bb-card-lead">'
        '<table class="bb-matrix"><thead><tr>'
        '<th>Asset</th><th>Last</th><th>Chg %</th><th style="text-align:right;">5D Trend</th>'
        '</tr></thead><tbody>' + body + '</tbody></table></div>')
    st.caption("数据源：yfinance（CL=F / GC=F / ^TNX / CNY=X / XIN9.FGI）与东方财富中美国债序列。"
               "标注「历史缺失」者为该接口仅返回当前报价、无日线序列，不以任何推算值填充。")


# --- 4.1 全球市场主线 ---
st.markdown(f"### 🌐 全球市场主线 <span style='font-size:0.82rem; opacity:0.65; margin-left:0.5rem;'>当前主线板块: <b style=\"color:#00b865\">{hot_sector_info['name']} ({hot_sector_info['chg']:+.1f}%)</b></span>", unsafe_allow_html=True)
region_icons = {'US': '🇺🇸', 'JP': '🇯🇵', 'KR': '🇰🇷', 'CN': '🇨🇳'}
g_cols = st.columns(4)
for i, (region, rdata) in enumerate(global_markets.items()):
    with g_cols[i]:
        rcode = region.split(' ')[0]
        region_label = region.split(' ')[1] if ' ' in region else region
        icon = rdata.get('flag', '🌐')
        for idx_name, idx_val in rdata['data'].items():
            price = idx_val['price']
            chg = idx_val['chg']
            chg_cls = "market-chg-up" if chg >= 0 else "market-chg-down"
            chg_sign = "+" if chg >= 0 else ""
            is_hot = abs(chg) > 1.0
            hot_cls = " market-card-hot" if is_hot else ""
            hot_badge = '<span class="market-badge-hot">HOT</span>' if is_hot else ""
            price_fmt = f"{price:,.2f}" if price > 100 else f"{price:.2f}"
            sector_line = rdata.get('sector', '')
            sector_html = f'<div class="market-sector">主线: {sector_line}</div>' if sector_line else ''
            # ⚠️ V8 战役一：此变量原名 card_html，与 terminal_ui 的 card_html() 函数同名，
            # 单文件合并后把函数覆盖成字符串，导致 render_kpi_grid 内
            # "".join(card_html(**c) ...) 抛 TypeError: 'str' object is not callable。
            # 现重命名为 market_card_template，彻底解除命名冲突。
            market_card_template = f'<div class="market-card{hot_cls}">{hot_badge}<div class="market-flag">{icon}</div><div class="market-name">{region_label} · {idx_name}</div><div class="market-index">{price_fmt}</div><div class="{chg_cls}">{chg_sign}{chg:.2f}%</div>{sector_html}</div>'
            st.markdown(market_card_template, unsafe_allow_html=True)
            break

st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

# --- 4.15 V12：跨资产表现矩阵（大类资产看板）---
try:
    render_cross_asset_matrix()
except Exception as e:
    import traceback as _tb
    print("[cross_asset ERROR]", repr(e))
    _tb.print_exc()
    st.warning(f"跨资产矩阵暂时异常: {type(e).__name__}")

st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

# --- 4.2 热门标的选择 ---
st.markdown("### 🔥 热门标的快速选择 <span style='font-size:0.78rem; opacity:0.6;'>(按实时成交量排序)</span>", unsafe_allow_html=True)

# （selected_ticker 初始化已随搜索栏一并上移至首屏第一层）
display_stocks = hot_stocks_list[:8]
h_cols = st.columns(8)
for j, s in enumerate(display_stocks):
    with h_cols[j]:
        btn_label = f"{s['name']} ({s['chg']:+.1f}%)"
        if st.button(btn_label, key=f"hot_btn_{j}", width="stretch"):
            st.session_state.selected_ticker = s['ticker']
            st.rerun()
        ohlc = s.get('ohlc', {})
        if ohlc and len(ohlc.get('close', [])) >= 2:
            fig_spk = go.Figure(go.Candlestick(
                open=ohlc['open'],
                high=ohlc['high'],
                low=ohlc['low'],
                close=ohlc['close'],
                increasing_line_color='#00b865',
                decreasing_fillcolor='#ef4444'
            ))
            fig_spk.update_layout(
                height=45, margin=dict(l=1, r=1, t=1, b=1),
                xaxis=dict(visible=False, rangeslider=dict(visible=False)),
                yaxis=dict(visible=False),
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                showlegend=False
            )
            st.plotly_chart(fig_spk, width="stretch", key=f'spk_{j}', config={'displayModeBar': False})
        else:
            st.caption('—')

st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

# --- 4.3 全市场实时盘口 (快讯) ---
try:
    # [已内联] from market_tape import get_market_tape_ui
    get_market_tape_ui(api_key_input)
except Exception as e:
    st.error(f"加载实时盘口失败: {e}")

st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

# --- 4.4 宏观资金面监控室 ---
try:
    # [已内联] from macro_capital import render_macro_capital_board
    render_macro_capital_board()
except Exception as e:
    # V8 诊断修复：原版静默吞掉异常，导致 Treemap 之后的功能区（CFFEX 等）
    # 无声消失且无从排查。现在写入服务器日志，页面上仍保持克制的降级提示。
    import traceback as _tb
    print("[macro_board ERROR]", repr(e))
    _tb.print_exc()
    st.warning(f"宏观资金面模块暂时异常: {type(e).__name__}")

st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

# ============================================================================
# --- 4.44 V11：资金面与利率监控室（借鉴专业固收资金面日报）---
# 利率是股票估值的分母。本模块提供：无风险利率锚（10Y 国债，大字主视觉）、
# Shibor 全期限走势与期限结构表、中债国债收益率曲线（今日 vs 前一交易日）、
# 中美 10Y 利差，以及"利率→估值分母"的客观传导说明。全部真实接口，缺数据即明示。
# ============================================================================
_SHIBOR_TENORS = ["O/N", "1W", "2W", "1M", "3M", "6M", "9M", "1Y"]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_shibor_history(n_days: int = 180) -> pd.DataFrame:
    """Shibor 全期限历史（中国货币网，含定价与涨跌幅）。"""
    df = _fetch_with_timeout(ak.macro_china_shibor_all, timeout_s=25, default=None)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    return df.tail(n_days).copy()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_cny_fx(n_days: int = 90):
    """V12 新增：人民币对美元汇率（中行外汇牌价序列，含央行中间价）。

    资金面监控室原本只覆盖"资金的价格"（Shibor / 国债曲线），
    缺了"货币的对外价格"这一环——而中美利差卡片本身就把
    "影响跨境资金流向与汇率预期"写进了说明，却始终没有汇率数据可看。
    返回 None 表示真实数据缺失，由 UI 层显式提示，不做任何填充。
    """
    _sd = (datetime.datetime.now() - datetime.timedelta(days=n_days + 30)).strftime("%Y%m%d")
    _ed = datetime.datetime.now().strftime("%Y%m%d")
    df = _fetch_with_timeout(ak.currency_boc_sina,
                             kwargs={"symbol": "美元", "start_date": _sd, "end_date": _ed},
                             timeout_s=25, default=None)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    col = next((c for c in df.columns if "中间价" in str(c) and "央行" in str(c)), None)
    if col is None:
        col = next((c for c in df.columns if "中间价" in str(c)), None)
    date_col = next((c for c in df.columns if "日期" in str(c)), None)
    if col is None or date_col is None:
        return None
    # 中间价按交易日发布，最新几行常为 NaN（尚未公布），必须取最后一个有效值
    d = df.dropna(subset=[col])
    if d.empty:
        return None
    d = d.tail(n_days).copy()
    # 中行牌价以"每 100 外币折合人民币"报价，换算为直观的 CNY / USD
    d["_rate"] = d[col].astype(float) / 100.0
    last = d.iloc[-1]
    prev = d.iloc[-2] if len(d) > 1 else None
    return dict(
        date=str(last[date_col]),
        rate=float(last["_rate"]),
        prev=(float(prev["_rate"]) if prev is not None else None),
        hist=d[[date_col, "_rate"]].rename(columns={date_col: "日期", "_rate": "中间价"}),
        source="中国银行外汇牌价·央行中间价",
    )


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_cgb_curves():
    """中债国债收益率曲线：最近两个交易日（今日 vs 前一交易日）。"""
    _end = datetime.datetime.now()
    _start = _end - datetime.timedelta(days=12)
    df = _fetch_with_timeout(ak.bond_china_yield,
                             kwargs={"start_date": _start.strftime("%Y%m%d"),
                                     "end_date": _end.strftime("%Y%m%d")},
                             timeout_s=25, default=None)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    c = df[df["曲线名称"].astype(str).str.contains("国债")].copy()
    if c.empty:
        return None
    dates = sorted(pd.to_datetime(c["日期"]).dt.strftime("%Y-%m-%d").unique())
    if len(dates) < 2:
        return None
    def _row(ds):
        r = c[pd.to_datetime(c["日期"]).dt.strftime("%Y-%m-%d") == ds].iloc[0]
        return {t: float(r[t]) for t in ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"] if t in c.columns and pd.notna(r.get(t))}
    return dict(today=_row(dates[-1]), prev=_row(dates[-2]),
                today_date=dates[-1], prev_date=dates[-2])


def _shibor_analysis(shb: pd.DataFrame) -> str:
    """Shibor 走势的规则化客观解读（真实数值拼接，非主观预测）。"""
    try:
        last = shb.iloc[-1]
        on = float(last.get("O/N-定价") or 0) or None
        on_chg = float(last.get("O/N-涨跌幅") or 0) if pd.notna(last.get("O/N-涨跌幅")) else None
        y1 = float(last.get("1Y-定价") or 0) or None
        parts = [f"最新交易日（{str(last['日期'])[:10]}）：隔夜 Shibor 报 <b>{on:.4f}%</b>"
                 + (f"（环比 <b>{on_chg:+.2f}BP</b>）" if on_chg is not None else "")
                 + (f"，1 年期报 <b>{y1:.4f}%</b>。" if y1 else "。")]
        if on is not None and y1 is not None:
            spread = (y1 - on) * 100
            if spread > 40:
                parts.append(f"期限利差（1Y − O/N）约 <b>{spread:.1f}BP</b>，曲线偏陡，反映市场对资金面阶段性收敛或政策利率中枢的定价。")
            else:
                parts.append(f"期限利差（1Y − O/N）约 <b>{spread:.1f}BP</b>，曲线平坦，资金面预期稳定。")
        parts.append("客观传导：短端利率是股票估值分母（贴现率）的边际变量之一——短端抬升通常压制高久期成长资产估值，宽松则相反；此处仅为传导机制描述，非方向判断。")
        return "".join(parts)
    except Exception:
        return "Shibor 数据解析异常，暂无法生成解读。"


def _curve_analysis(cv: dict) -> str:
    """国债收益率曲线 今日 vs 前一交易日 的规则化客观解读。"""
    try:
        t, p = cv["today"], cv["prev"]
        segs = []
        for ten in ("1年", "10年"):
            if ten in t and ten in p and p[ten]:
                chg = (t[ten] - p[ten]) * 100
                segs.append(f"{ten} {t[ten]:.3f}%（<b>{chg:+.2f}BP</b>）")
        steep = None
        if all(k in t and k in p and t[k] and p[k] for k in ("1年", "10年")):
            steep = (t["10年"] - t["1年"]) - (p["10年"] - p["1年"])
        txt = f"对比 {cv['prev_date']} → {cv['today_date']}：{'，'.join(segs) or '关键期限数据缺失'}。"
        if steep is not None and abs(steep) >= 0.0005:
            txt += f"10Y−1Y 期限利差变动 <b>{steep*100:+.2f}BP</b>，曲线{'陡峭化' if steep > 0 else '平坦化'}。"
        elif steep is not None:
            txt += "期限利差基本持平，曲线形态稳定。"
        txt += "无风险利率（10Y）是全市场资产定价之锚：其上行抬升股权资产的贴现分母，对高估值成长股的压制弹性历史上大于价值股；下行则反之。"
        return txt
    except Exception:
        return "收益率曲线数据解析异常，暂无法生成解读。"


def render_rates_monitor():
    rf = fetch_riskfree_rate()
    shb = fetch_shibor_history()
    cv = fetch_cgb_curves()
    fx = fetch_cny_fx()

    st.markdown("### 🏦 资金面与利率监控室 <span style='font-size:0.78rem; opacity:0.6;'>(利率 = 股票估值的分母 · 对标固收资金面日报)</span>", unsafe_allow_html=True)
    st.caption("无风险利率 / Shibor / 中债收益率曲线均为真实接口数据；利率传导说明为客观机制描述，不构成任何利率或行情预测。")

    # ===== 主视觉：利率四联快览（V12） =====
    # 旧版用 st.columns([1.35,1,1], vertical_alignment="center") 分三列：左列一张大卡、
    # 中列两张上下堆叠的小卡、右列中美利差。三列内容高度不同 + 居中对齐 → 上下沿互不齐平；
    # 且中美利差在 us10 缺失时整列不渲染任何东西，右侧直接空掉一大块。
    # V12 改为单次输出的 CSS Grid：四张同规格等高卡片，对齐由 grid 保证，
    # 任何一项数据缺失都渲染显式"数据缺失"卡而不是留白。
    def _rate_card(icon, label, value_html, sub_html, primary=False):
        return (f'<div class="rate-kpi{" rate-kpi-primary" if primary else ""}">'
                f'<div class="rate-kpi-label">{icon} {label}</div>'
                f'<div class="rate-kpi-value">{value_html}</div>'
                f'<div class="rate-kpi-sub">{sub_html}</div></div>')

    _cards = []
    if rf:
        chg_bp = ((rf["cn10"] - rf["cn10_prev"]) * 100) if rf.get("cn10_prev") is not None else None
        chg_html = (f'<span style="color:{C_UP if chg_bp >= 0 else C_DOWN}; font-weight:700;">{chg_bp:+.2f}BP / 日</span>'
                    if chg_bp is not None else '<span style="color:#8B93A7;">环比数据缺失</span>')
        _cards.append(_rate_card(
            "⚖️", "无风险利率锚 · 中国 10Y 国债",
            f'{rf["cn10"]:.4f}<span class="rate-kpi-unit">%</span>',
            f'{rf["date"]} · {rf["source"]} · {chg_html}<br>全站 PE / 情景推演的估值分母基准',
            primary=True))
    else:
        _cards.append(_rate_card("⚖️", "无风险利率锚 · 中国 10Y 国债",
                                 '<span class="rate-kpi-na">数据缺失</span>',
                                 "真实接口未返回，不做任何填充", primary=True))

    if rf and rf.get("us10"):
        # 同一天的中债 / 美债配对报价（可能比上面的 cn10 晚一个交易日，故单独标注日期）
        _cn_pair = rf.get("us10_cn") or rf["cn10"]
        _spread = _cn_pair - rf["us10"]
        _cards.append(_rate_card(
            "🌍", "中美 10Y 利差（中 − 美）",
            f'<span style="color:{C_UP if _spread >= 0 else C_DOWN};">{_spread*100:+.1f}</span><span class="rate-kpi-unit">BP</span>',
            f'中 {_cn_pair:.2f}% vs 美 {rf["us10"]:.2f}%（{rf.get("us10_date") or "同日配对"}）<br>影响跨境资金流向与汇率预期'))
    else:
        _cards.append(_rate_card("🌍", "中美 10Y 利差（中 − 美）",
                                 '<span class="rate-kpi-na">数据缺失</span>',
                                 "美债 10Y 实时接口未返回<br>不以任何假设值替代"))

    def _shibor_card(icon, lbl, col, chg_col, desc):
        if shb.empty:
            return _rate_card(icon, lbl, '<span class="rate-kpi-na">数据缺失</span>', "Shibor 接口未返回")
        try:
            _last = shb.iloc[-1]
            _v = float(_last.get(col))
            _c = float(_last.get(chg_col) or 0)
        except Exception:
            return _rate_card(icon, lbl, '<span class="rate-kpi-na">数据缺失</span>', "该期限报价未披露")
        return _rate_card(icon, lbl, f'{_v:.4f}<span class="rate-kpi-unit">%</span>',
                          f'<span style="color:{C_UP if _c >= 0 else C_DOWN}; font-weight:700;">{_c:+.2f}BP / 日</span><br>{desc}')

    _cards.append(_shibor_card("🌙", "Shibor 隔夜 (O/N)", "O/N-定价", "O/N-涨跌幅", "银行间隔夜资金松紧温度计"))
    _cards.append(_shibor_card("📆", "Shibor 1 年", "1Y-定价", "1Y-涨跌幅", "中长端资金成本 · 贷款定价参考"))

    # V12 新增：人民币汇率 —— 补齐"货币对外价格"这一环
    if fx:
        _fx_chg = ((fx["rate"] - fx["prev"]) * 10000) if fx.get("prev") is not None else None
        # 直接标价法下数值上行 = 人民币贬值，配色沿用全站涨跌语义
        _fx_sub = (f'<span style="color:{C_DOWN if (_fx_chg or 0) > 0 else C_UP}; font-weight:700;">'
                   f'{_fx_chg:+.0f} 基点 · 人民币{"贬值" if _fx_chg > 0 else "升值"}</span><br>'
                   if _fx_chg not in (None, 0) else '<span style="color:#8B93A7;">与上一交易日持平</span><br>')
        _cards.append(_rate_card(
            "💱", "美元兑人民币 · 央行中间价",
            f'{fx["rate"]:.4f}',
            _fx_sub + f'{fx["date"]} · {fx["source"]}'))
    else:
        _cards.append(_rate_card("💱", "美元兑人民币 · 央行中间价",
                                 '<span class="rate-kpi-na">数据缺失</span>',
                                 "中行外汇牌价接口未返回<br>不以任何假设值替代"))

    st.html('<div class="rate-kpi-grid">' + "".join(_cards) + '</div>')

    # ===== Shibor 全期限走势（近 180 日）=====
    if not shb.empty:
        st.markdown('<div class="spacer-sm"></div>', unsafe_allow_html=True)
        st.markdown("#### 📈 Shibor 全期限走势（近 180 日）")
        fig_s = go.Figure()
        for ten in ["O/N", "1W", "1M", "3M", "6M", "1Y"]:
            col = f"{ten}-定价"
            if col in shb.columns:
                fig_s.add_trace(go.Scatter(x=shb["日期"], y=shb[col], name=ten,
                                           line=dict(width=1.4), hovertemplate=f"{ten} %{{y:.4f}}%<extra></extra>"))
        fig_s.update_layout(height=300, template="plotly_dark",
                            margin=dict(l=40, r=20, t=30, b=20),
                            paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
                            legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5, font=dict(size=9)),
                            yaxis=dict(title="利率 (%)", title_font=dict(size=9), gridcolor="rgba(255,255,255,0.05)"))
        st.plotly_chart(apply_institutional_axes(fig_s), width="stretch", config={"displayModeBar": False})
        st.markdown(f'<div class="ana-note">📊 {_shibor_analysis(shb)}</div>', unsafe_allow_html=True)

        # ===== Shibor 期限结构表（最新交易日）=====
        st.markdown("#### 🧾 Shibor 期限结构（最新交易日）")
        rows_html = ""
        last = shb.iloc[-1]
        for ten in _SHIBOR_TENORS:
            pr, chg = last.get(f"{ten}-定价"), last.get(f"{ten}-涨跌幅")
            if pr is None or pd.isna(pr):
                continue
            try:
                chg_v = float(chg) if chg is not None and pd.notna(chg) else None
            except Exception:
                chg_v = None
            chg_cell = (f'<td style="color:{C_UP if chg_v >= 0 else C_DOWN}; font-weight:700;">{chg_v:+.2f} BP</td>'
                        if chg_v is not None else '<td style="color:#8B93A7;">—</td>')
            rows_html += (f'<tr><td style="text-align:left; font-weight:600;">{ten}</td>'
                          f'<td>{float(pr):.4f}%</td>{chg_cell}</tr>')
        st.markdown(f"""
<table style="width:100%; border-collapse:collapse; font-size:0.85rem; margin:8px 0;">
<thead><tr style="border-bottom:1px solid rgba(255,255,255,0.15); color:#8B93A7;">
<th style="text-align:left; padding:6px 10px;">期限</th><th style="padding:6px 10px; text-align:right;">定价</th>
<th style="padding:6px 10px; text-align:right;">环比</th></tr></thead>
<tbody style="color:#D1D4DC;">{rows_html}</tbody></table>
""", unsafe_allow_html=True)
        st.caption("数据来源：中国货币网 Shibor（利率上行标红、下行标绿，中国金融惯例，跟随全站配色开关）")

    # ===== 中债国债收益率曲线：今日 vs 前一交易日 =====
    if cv:
        st.markdown('<div class="spacer-sm"></div>', unsafe_allow_html=True)
        st.markdown("#### 📐 中债国债收益率曲线（今日 vs 前一交易日）")
        c1, c2 = st.columns([1.6, 1], vertical_alignment="center")
        with c1:
            tenors = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]
            fig_c = go.Figure()
            fig_c.add_trace(go.Scatter(x=tenors, y=[cv["today"].get(t) for t in tenors],
                                       name=f"今日 {cv['today_date']}", mode="lines+markers",
                                       line=dict(color=C_ACCENT, width=2.2), marker=dict(size=6)))
            fig_c.add_trace(go.Scatter(x=tenors, y=[cv["prev"].get(t) for t in tenors],
                                       name=f"前一日 {cv['prev_date']}", mode="lines+markers",
                                       line=dict(color="#8B93A7", width=1.6, dash="dash"), marker=dict(size=5)))
            fig_c.update_layout(height=300, template="plotly_dark",
                                margin=dict(l=40, r=20, t=30, b=20),
                                paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
                                legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5, font=dict(size=9)),
                                yaxis=dict(title="收益率 (%)", title_font=dict(size=9), gridcolor="rgba(255,255,255,0.05)"))
            st.plotly_chart(apply_institutional_axes(fig_c), width="stretch", config={"displayModeBar": False})
        with c2:
            st.markdown(f'<div class="ana-note">📐 {_curve_analysis(cv)}</div>', unsafe_allow_html=True)

    # ===== V12 新增：人民币汇率走势（货币的对外价格）=====
    if fx and fx.get("hist") is not None and not fx["hist"].empty:
        st.markdown('<div class="spacer-sm"></div>', unsafe_allow_html=True)
        st.markdown("#### 💱 美元兑人民币中间价走势（近 90 个交易日）")
        _fxh = fx["hist"]
        fig_fx = go.Figure()
        fig_fx.add_trace(go.Scatter(x=_fxh["日期"].astype(str), y=_fxh["中间价"],
                                    name="USD/CNY 中间价", mode="lines",
                                    line=dict(color=C_ACCENT, width=2),
                                    hovertemplate="%{x} %{y:.4f}<extra></extra>"))
        fig_fx.update_layout(height=260, template="plotly_dark",
                             margin=dict(l=40, r=20, t=30, b=20),
                             paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
                             showlegend=False,
                             xaxis=dict(type="category", nticks=8, gridcolor="rgba(255,255,255,0.05)"),
                             yaxis=dict(title="CNY / USD", title_font=dict(size=9),
                                        gridcolor="rgba(255,255,255,0.05)"))
        st.plotly_chart(apply_institutional_axes(fig_fx), width="stretch", config={"displayModeBar": False})
        _fx_hi, _fx_lo = float(_fxh["中间价"].max()), float(_fxh["中间价"].min())
        _fx_first = float(_fxh["中间价"].iloc[0])
        _fx_amp = (fx["rate"] - _fx_first) * 10000
        st.markdown(
            f'<div class="ana-note">💱 区间内中间价高点 <b>{_fx_hi:.4f}</b>、低点 <b>{_fx_lo:.4f}</b>，'
            f'最新 <b>{fx["rate"]:.4f}</b>，区间累计变动 <b>{_fx_amp:+.0f} 基点</b>'
            f'（直接标价法下数值上行即人民币贬值）。客观传导机制：中美利差走阔 → 套息资金外流压力 → '
            f'人民币承压；汇率贬值预期又会通过外资持仓成本影响 A 股/港股定价。'
            f'以上为机制描述，不构成任何汇率或行情预测。</div>', unsafe_allow_html=True)
    elif fx is None:
        st.info("人民币汇率（央行中间价）真实数据缺失，不做任何填充。")

    # ===== 利率 → 估值分母传导说明 =====
    st.markdown('<div class="ana-note">🔗 <b>利率与你的持仓的关系（客观传导框架）</b>：无风险利率是 DCF 估值的分母起点——利率下行降低折现率、抬升远期现金流的现值，高久期成长资产（高 PE、盈利后置）估值弹性最大；利率上行则反向。10Y 国债的边际变动对成长股合理 PE 的影响显著大于对低 PE 价值股。本监控室的所有说明均为机制描述，不构成任何利率走势或买卖判断。</div>', unsafe_allow_html=True)


try:
    render_rates_monitor()
except Exception as e:
    import traceback as _tb
    print("[rates_monitor ERROR]", repr(e))
    _tb.print_exc()
    st.warning(f"资金面与利率监控室暂时异常: {type(e).__name__}")

st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

# ============================================================================
# --- 4.45 V9 战役三：宏观大事日历 (Macro Economic Calendar) ---
# 左栏：未来 7 天重要宏观事件列表；右栏：选中事件的客观数据卡与影响解读。
# 数据源优先 akshare 百度经济数据日历（真实），失败降级为示例框架并明确标注；
# 解读为基于事件类别的客观影响链条描述（规则库），不含任何买卖建议。
# ============================================================================
_MACRO_KEY_EVENTS = ["FOMC", "议息", "利率决议", "非农", "就业报告", "失业率", "CPI",
                     "PCE", "GDP", "PMI", "通胀", "纪要", "财政", "关税", "议会的"]

_MACRO_IMPACT_RULES = [
    ("FOMC|议息|利率决议|纪要", "全球流动性定价之锚。客观影响链条：利率路径预期 → 美元指数与美债收益率 → 全球风险资产估值分母（成长股久期敏感）→ 黄金/新兴市场资金流向。历史规律：决议前后波动率通常放大，方向由实际结果与市场预期的差值决定。"),
    ("非农|就业报告|失业率|初请", "美国劳动力市场温度计，美联储双目标之一。客观影响链条：就业强弱 → 政策宽松/收紧预期 → 美元与美债利率 → 风险偏好。历史上该数据公布时刻常出现短线跳空，量化上属于典型的事件驱动波动源。"),
    ("CPI|PCE|通胀", "通胀读数直接改变实际利率预期。客观影响链条：通胀高于/低于预期 → 加息或降息路径重定价 → 成长/价值风格相对表现、黄金与债券久期联动。该数据对分母端资产的弹性历史上大于对盈利端。"),
    ("GDP|经济景气", "总量增长锚。客观影响链条：增长上修 → 企业盈利预期与周期品需求预期 → 股市盈利端与大宗商品；同时可能强化'higher for longer'利率预期，股债反应方向取决于通胀背景。"),
    ("PMI|制造业", "景气先行指标。客观影响链条：荣枯线上下 → 工业品/周期股盈利预期 → 汇率与商品货币联动。历史上对上游资源品与出口链敏感度较高。"),
    ("财政|关税", "财政与贸易政策事件。客观影响链条：财政扩张/收缩 → 国债供给与利率 → 私人部门挤出/挤入；关税变化直接影响跨国企业成本结构与供应链利润分配。"),
]


def _mcal_fmt(v):
    """V9：经济日历数值列清洗——NaN/空 → None，数值统一字符串化。"""
    try:
        if v is None or str(v).strip() in ("", "nan", "None", "--"):
            return None
        f = float(v)
        return f"{f:.2f}".rstrip("0").rstrip(".") if abs(f) < 1e12 else str(f)
    except Exception:
        return str(v).strip()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_macro_calendar_events() -> list:
    """V9：未来 7 天重要宏观事件。真实源=akshare 百度经济数据日历；
    连续失败即降级示例框架（source='sample'），绝不抛异常。"""
    events = []
    try:
        # V10.3 P7：范围含过去 3 天——当天非交易日无事件时，自动展示上一个交易日数据
        for off in range(-3, 8):
            _d = datetime.datetime.now() + datetime.timedelta(days=off)
            df = _fetch_with_timeout(ak.news_economic_baidu,
                                     kwargs={"date": _d.strftime("%Y%m%d")},
                                     timeout_s=10, default=None)
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                if off >= 2 and not events:
                    break  # 连续两天拉不到 → 直接降级
                continue
            name_col = next((c for c in df.columns if "指标" in str(c) or "事件" in str(c)), None)
            region_col = next((c for c in df.columns if "地区" in str(c) or "国家" in str(c)), None)
            time_col = next((c for c in df.columns if "时间" in str(c) or "发布" in str(c)), None)
            # V9：百度经济日历还提供 公布/预期/前值/重要性，全部透传到详情面板
            exp_col = next((c for c in df.columns if "预期" in str(c)), None)
            prev_col = next((c for c in df.columns if "前值" in str(c)), None)
            pub_col = next((c for c in df.columns if "公布" in str(c) or "现值" in str(c)), None)
            imp_col = next((c for c in df.columns if "重要性" in str(c)), None)
            if name_col is None:
                continue
            for _, r in df.iterrows():
                name = str(r.get(name_col, "")).strip()
                if not name or not any(k.lower() in name.lower() for k in _MACRO_KEY_EVENTS):
                    continue
                region = str(r.get(region_col, "全球")).strip() if region_col else "全球"
                
                TIER1_EVENTS = ["非农", "ADP", "失业率", "FOMC", "议息", "利率决议", "CPI", "PCE", "GDP"]
                tier1 = (region in ["美国", "中国"]) and any(k in name for k in TIER1_EVENTS)
                
                tm = str(r.get(time_col, "")).strip()[:5] if time_col else ""
                imp_raw = r.get(imp_col) if imp_col else None
                try:
                    imp_n = int(float(imp_raw)) if imp_raw is not None and str(imp_raw) not in ("nan", "") else 2
                except Exception:
                    imp_n = 2
                
                if tier1:
                    imp_n = max(imp_n, 4)
                
                events.append({
                    "_imp": imp_n, "_off": off, "tier1": tier1,
                    "date": _d.strftime("%m-%d"), "time": tm, "region": region,
                    "title": name[:40], "importance": "高" if imp_n >= 3 else ("中" if imp_n == 2 else "低"),
                    "expected": _mcal_fmt(r.get(exp_col)) if exp_col else None,
                    "previous": _mcal_fmt(r.get(prev_col)) if prev_col else None,
                    "published": _mcal_fmt(r.get(pub_col)) if pub_col else None,
                    "source": "akshare·百度经济日历",
                    "detail": f"真实日历条目：{region} · {name}（{_d.strftime('%Y-%m-%d')} {tm}）",
                })
    except Exception:
        pass
    if events:
        # V10.3 P7：上一交易日优先——当天非交易日无数据时，最近一个有数据的过去交易日
        # 的事件排在最前（最近的过去优先）；过去限 3 条 + 今天/未来限 6 条，
        # 兼顾"回顾上一交易日"与"前瞻未来排期"
        # V12：改为"市场影响力优先"排序。旧版只按日期先后排，
        # 瑞士失业率、日本 GDP 修正值这类低影响数据会把美国非农 / FOMC / CPI
        # 挤出可视区——而后者才是真正驱动全球风险资产重定价的一级数据。
        import re as _re2

        def _impact_score(e):
            _t = e["title"]
            _s = e["_imp"] * 10
            if e.get("tier1"):
                _s += 100
            if e["region"] in ("美国", "中国"):
                _s += 25
            if _re2.search("非农|ADP|FOMC|议息|利率决议|CPI|PCE|失业率", _t):
                _s += 40
            # 修正值/终值/名义口径等属同一事件的次级发布，市场影响远小于初值
            if _re2.search("修正值|终值|名义|汽油|三年|3年", _t):
                _s -= 45
            return _s

        _past = [e for e in events if e["_off"] < 0]
        _fut = [e for e in events if e["_off"] >= 0]
        _past.sort(key=lambda e: (-_impact_score(e), -e["_off"]))
        _fut.sort(key=lambda e: (-_impact_score(e), e["_off"]))
        events = _past[:3] + _fut[:6]
        for e in events:
            e.pop("_imp", None); e.pop("_off", None)
        return events
    if not events:
        # 降级：示例框架（明确标注，绝不伪装真实数据）
        _today = datetime.datetime.now()
        _samples = [("美国", "FOMC 利率决议与新闻发布会", 2), ("美国", "非农就业报告 (NFP)", 3),
                    ("美国", "CPI 通胀数据", 1), ("欧元区", "央行利率决议", 4),
                    ("中国", "制造业 PMI", 5), ("美国", "PCE 物价指数", 6),
                    ("日本", "央行议息会议", 7)]
        for i, (rg, tt, dd) in enumerate(_samples):
            events.append({
                "date": (_today + datetime.timedelta(days=dd)).strftime("%m-%d"), "time": "20:30",
                "region": rg, "title": tt, "importance": "高",
                "source": "示例框架（真实日历接口暂不可用）",
                "detail": f"示例事件：{rg} · {tt}（交互演示用，非真实排期）",
            })
    return events


def _macro_impact_text(title: str) -> str:
    """规则库生成客观影响链条描述（按事件类别匹配），默认给通用客观框架。"""
    for pats, text in _MACRO_IMPACT_RULES:
        import re as _re
        if _re.search(pats, title, flags=_re.I):
            return text
    return "重大宏观事件。客观影响框架：实际数据/结果与市场事前预期的差值 → 资产价格重定价；事件前隐含波动率通常抬升，事件后回落。本描述仅为客观传导链条，不含方向性判断。"


def render_macro_calendar():
    evs = fetch_macro_calendar_events()
    st.markdown("### 🗓️ 宏观大事日历 <span style='font-size:0.78rem; opacity:0.6;'>(未来 7 天 · 事件驱动核心参考)</span>", unsafe_allow_html=True)
    st.caption("对标华尔街见闻/金十数据的事件驱动视角：左栏选择事件，右栏查看客观数据与影响链条。仅客观聚合，不构成任何投资建议。")

    cal_c1, cal_c2 = st.columns([1, 2], vertical_alignment="top")
    with cal_c1:
        st.markdown('<div class="mcal-col-title">📌 重点事件 · 上一交易日回顾 + 未来排期</div>', unsafe_allow_html=True)

        # V12：默认选中影响力最高的事件（首个一级数据），而非固定的第 0 条。
        # 列表以"上一交易日回顾"打头，固定选 0 会让右栏详情停在瑞士失业率这类
        # 低影响条目上，把真正的美联储 / CPI / 非农挤到用户看不见的位置。
        _default_sel = next((i for i, e in enumerate(evs) if e.get("tier1")), 0)
        _cur_sel = st.session_state.get("mcal_sel", _default_sel)
        if _cur_sel >= len(evs):
            _cur_sel = _default_sel
        # V12：一次性下发全部按钮样式。旧版在循环里逐个 st.markdown 注入 <style>，
        # 既产生 N 个占位空元素（撑出行间空隙、造成文字挤压重叠），
        # 选择器 button[key="..."] 又永远不命中——Streamlit 不会把 key 渲染成
        # button 的 HTML 属性，只会在包裹层输出 .st-key-<key> 类。
        # 选择器用 div[class*="st-key-..."]，与下方通用规则同特异度、靠"后出现者胜"生效；
        # 若写成 .st-key-xxx button（0,1,1）会被通用规则 div[class*=…] button（0,2,1）压掉。
        _tier1_idx = [i for i, e in enumerate(evs) if e.get("tier1")]
        _btn_css = "".join(
            f'div[class*="st-key-mcal_btn_{i}"] button {{ border-left:4px solid #FF4B4B !important; '
            f'background: linear-gradient(90deg, rgba(239,68,68,0.16) 0%, rgba(30,41,59,0.85) 60%) !important; }}'
            for i in _tier1_idx)
        _btn_css += (f'div[class*="st-key-mcal_btn_{_cur_sel}"] button {{ border-color:#4B9FFF !important; '
                     f'box-shadow:0 0 0 1px #4B9FFF inset, 0 0 14px rgba(75,159,255,0.25) !important; }}')
        st.html(f"<style>{_btn_css}</style>")

        for i, ev in enumerate(evs):
            tier1 = ev.get("tier1", False)
            if tier1:
                prefix = "🔥 重磅"
                if "非农" in ev['title'] or "失业" in ev['title'] or "ADP" in ev['title']: prefix = "🔥 大非农"
                elif "FOMC" in ev['title'] or "议息" in ev['title'] or "决议" in ev['title']: prefix = "⚡ 美联储"
                elif "CPI" in ev['title'] or "PCE" in ev['title'] or "GDP" in ev['title']: prefix = "📊 核心宏观"
                btn_title = f"{prefix} · {ev['date']} {ev.get('time','')} · {ev['region']}\n\n{ev['title']}"
            else:
                btn_title = f"{ev['date']} {ev.get('time','')} · {ev['region']}\n\n{ev['title']}"
            if st.button(btn_title, key=f"mcal_btn_{i}", use_container_width=True):
                st.session_state.mcal_sel = i
                st.rerun()
        src_note = evs[0].get("source", "") if evs else ""
        st.caption(f"数据来源：{src_note}" if src_note else "暂无事件数据")

    with cal_c2:
        # V10.3 P6：右栏加与左栏同规格的小标题，两栏首行对齐（右栏详情卡随之下移，
        # 上沿与左侧第一个事件按钮的上沿水平对齐）
        st.markdown('<div class="mcal-col-title">🔍 事件详情 · 客观影响解读</div>', unsafe_allow_html=True)
        # 复用左栏已做过越界校正的 _cur_sel：事件列表在缓存刷新后可能变短，
        # 直接用 session_state 里的旧索引取值会 IndexError。
        ev = evs[_cur_sel] if evs else None
        if ev:
            tier1 = ev.get("tier1", False)
            tier1_banner = '<div class="mcal-banner">⚠️ 全球金融市场一级核弹数据 · 波动率爆发预警</div>' if tier1 else ''
            # V12：前值/预期/公布 升级为等宽 KPI 单元（字号 0.78rem → 1.6rem），
            # 并按机构惯例算出「公布 − 预期」的意外差（surprise），
            # 仅在两者都为可解析数值时给出，缺任一项即显示「待公布」，不做任何推算。
            def _mcell(lbl, v, big=False, color=None):
                _v = v if v is not None else "—"
                _c = f" style='color:{color};'" if color else ""
                return (f'<div class="mcal-cell{" mcal-cell-hl" if big else ""}">'
                        f'<div class="mcal-cell-label">{lbl}</div>'
                        f'<div class="mcal-cell-value"{_c}>{_v}</div></div>')

            def _as_num(x):
                try:
                    return float(str(x).replace("%", "").replace(",", "").strip())
                except Exception:
                    return None

            _exp_n, _pub_n = _as_num(ev.get("expected")), _as_num(ev.get("published"))
            if _exp_n is not None and _pub_n is not None:
                _diff = _pub_n - _exp_n
                _sur_col = C_UP if _diff >= 0 else C_DOWN
                _sur_lbl = "高于预期" if _diff > 0 else ("符合预期" if _diff == 0 else "低于预期")
                _surprise = (f'<div class="mcal-surprise" style="border-color:{_sur_col}; color:{_sur_col};">'
                             f'意外差 {_diff:+.2f} · {_sur_lbl}</div>')
                _pub_cell = _mcell("公布值", ev.get("published"), big=True, color=_sur_col)
            else:
                _surprise = '<div class="mcal-surprise" style="border-color:#475569; color:#8B93A7;">尚未公布 · 无意外差</div>'
                _pub_cell = _mcell("公布值", ev.get("published"), big=True)

            st.markdown(f"""
<div class="mcal-detail">
{tier1_banner}
<div class="mcal-meta">事件 · {ev['date']} {ev.get('time','')} · 重要性 {ev.get('importance','—')}</div>
<div class="mcal-title">{ev['region']} · {ev['title']}</div>
<div class="mcal-cells">
{_mcell('前值', ev.get('previous'))}
{_mcell('预期值', ev.get('expected'))}
{_pub_cell}
</div>
{_surprise}
<div class="mcal-src">{ev['detail']} · 来源：{ev['source']}</div>
</div>
""", unsafe_allow_html=True)
            st.markdown("#### 🔗 客观影响链条（规则库生成 · 无方向性判断）")
            st.markdown(f"<div style='background:#171B26; border:1px solid #2B3139; border-radius:12px; padding:16px; font-size:0.9rem; line-height:1.8; color:#D1D4DC;'>{_macro_impact_text(ev['title'])}</div>", unsafe_allow_html=True)
            # V10：动态关联当前关注标的——事件传导链条落到用户正在研究的标的上
            _cur_tk = st.session_state.get("selected_ticker", "")
            if _cur_tk:
                st.caption(f"🎯 当前关注标的：{_cur_tk} —— 上述传导机制同样作用于该标的所处板块（盈利预期/估值分母/资金面三通道），具体弹性取决于其行业属性与财报披露节奏。")
            st.caption("⚠️ 以上为事件类别的客观传导机制描述，非行情预测；数据请以官方发布为准。")
        else:
            st.info("暂无宏观事件数据。")

try:
    render_macro_calendar()
except Exception as e:
    import traceback as _tb
    print("[macro_calendar ERROR]", repr(e))
    _tb.print_exc()
    st.warning(f"宏观大事日历暂时不可用: {type(e).__name__}")

st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

# --- 4.5 （已上移至首屏第一层）---
# V8 战役三：搜索栏/API Key/生成按钮已上移到页面顶部第一层。
# 副作用修复：原顺序下 api_key_input 在快讯模块渲染之后才被赋值，
# 导致「AI 深度客观解读」永远拿到空 Key；上移后该缺陷一并消除。

# 仅在此处解析标的代码；真正的数据采集统一由下方「5. 主界面」段落执行。
# （原先此处提前调用 fetch_all_data，但该函数在本文件更下方才定义，
#   每次运行都会抛 NameError 并弹出"数据采集失败"红色报错。已移除该冗余调用，
#   下游 fetch_all_data 带 st.cache_data 缓存，功能与性能均无损失。）
ticker_input, mapped_name = resolve_ticker(user_ticker_raw)

risk_preference = "稳健型"


def fmt_price_val(val, currency=""):
    """按币种标准化价格显示。

    V12 修正：旧实现为 `if currency in ["USD","$"] or val < 1000: return f"${val}"`,
    那个 `or val < 1000` 会把**任何低于 1000 的 A 股价格都标成美元**
    （招商银行 35.20 元 → "$35.20"）。绝大多数 A 股都在 1000 以下，
    等于全站币种系统性标错，对金融终端属于硬性错误。
    现改为严格按 currency 字段判定，绝不用数值大小猜币种。

    口径：美元前置符号（$120.50）；人民币 / 港币后置单位（1,250.00 元 / 23.50 港元）。
    """
    if not (isinstance(val, (int, float)) and not isinstance(val, bool)):
        return "N/A"
    try:
        if np.isnan(val) or np.isinf(val):
            return "N/A"
    except (TypeError, ValueError):
        return "N/A"
    cur = str(currency or "").strip().upper()
    if cur in ("USD", "$"):
        return f"${val:,.2f}"
    if cur in ("HKD", "HK$"):
        return f"{val:,.2f} 港元"
    if cur in ("CNY", "RMB", "CNH", "¥", "￥"):
        return f"{val:,.2f} 元"
    if cur in ("EUR", "€"):
        return f"€{val:,.2f}"
    if cur in ("JPY", "¥JP"):
        return f"¥{val:,.0f}"
    if not cur:
        # 币种未知时不臆测符号，只给数值——错误的货币符号比没有符号更危险
        return f"{val:,.2f}"
    return f"{val:,.2f} {cur}"

@st.cache_data(ttl=300, show_spinner=False)
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

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_price_history_long(ticker_input, years=3):
    """抓取近N年收盘价，仅用于计算「股价历史分位」这一客观统计指标（不是PE分位，不做估值判断）。
    说明：真正的“PE历史分位”需要历史EPS序列，免费数据源无法可靠获取，
    为避免编造精度，本函数只提供可验证的“股价所处历史区间分位”作为透明替代指标。"""
    try:
        t = yf.Ticker(ticker_input)
        h = t.history(period=f"{years}y")
        if h is None or h.empty:
            return None
        return h[['Close']].dropna()
    except Exception:
        return None

def build_kline_chart(df, ticker_input):
    """构建带 MA/MACD 的交互式 K 线图"""
    df = df.copy()
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA50'] = df['Close'].rolling(50).mean()
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.2, 0.25],
        subplot_titles=[f'{ticker_input} 近 1 年 K 线与均线系统', '', '']
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='#00b865', decreasing_line_color='#ef4444', name='K线'
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(width=1, color='#f59e0b'), name='MA5'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(width=1, color='#3b82f6'), name='MA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(width=1.5, color='#8b5cf6'), name='MA50'), row=1, col=1)

    colors = ['#00b865' if c >= o else '#ef4444' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量', opacity=0.6), row=2, col=1)

    hist_colors = ['#00b865' if v >= 0 else '#ef4444' for v in hist]
    fig.add_trace(go.Bar(x=df.index, y=hist, marker_color=hist_colors, name='MACD柱体', opacity=0.7), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=macd, line=dict(width=1, color='#3b82f6'), name='DIF'), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=signal, line=dict(width=1, color='#f59e0b'), name='DEA'), row=3, col=1)

    fig.update_layout(
        height=580,
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        # V9 P3：t=60 让 subplot_titles 与图例分家；b=40 给下移图例留位
        margin=dict(l=40, r=20, t=60, b=40),
        # V9 P3：图例移到全部副图正下方，不再与 K 线副图标题抢顶部空间
        legend=dict(orientation='h', yanchor='top', y=-0.1, xanchor='center', x=0.5),
        font=dict(family='Inter', size=12)
    )
    return fig

def merge_klines_inclusion(df):
    """缠论第一步：K线包含关系处理。将有包含关系的相邻K线合并，消除噪音，
    再在合并后的K线序列上做顶底分型识别，避免原始K线导致的伪分型。"""
    highs = df['High'].tolist()
    lows = df['Low'].tolist()
    dates = list(df.index)
    if len(highs) < 3:
        return []
    merged = [{'high': highs[0], 'low': lows[0], 'date': dates[0]}]
    direction = 0  # 0=未知, 1=向上处理(取高高), -1=向下处理(取低低)
    for i in range(1, len(highs)):
        h, l, d = highs[i], lows[i], dates[i]
        last = merged[-1]
        is_contain = (h <= last['high'] and l >= last['low']) or (h >= last['high'] and l <= last['low'])
        if is_contain:
            if direction >= 0:
                new_high, new_low = max(h, last['high']), max(l, last['low'])
            else:
                new_high, new_low = min(h, last['high']), min(l, last['low'])
            merged[-1] = {'high': new_high, 'low': new_low, 'date': d}
        else:
            if h > last['high']:
                direction = 1
            elif h < last['high']:
                direction = -1
            merged.append({'high': h, 'low': l, 'date': d})
    return merged


def find_fractals_on_merged(merged):
    """在包含处理后的K线序列上识别顶/底分型，比原始K线三点极值法更可靠。"""
    tops, bottoms = [], []
    for i in range(1, len(merged) - 1):
        if merged[i]['high'] > merged[i-1]['high'] and merged[i]['high'] > merged[i+1]['high']:
            tops.append(merged[i])
        if merged[i]['low'] < merged[i-1]['low'] and merged[i]['low'] < merged[i+1]['low']:
            bottoms.append(merged[i])
    return tops, bottoms


def build_bi_sequence(tops, bottoms):
    """构建"笔"序列：连接相邻的顶/底分型，方向必须交替，取同类型分型中的极值点。
    这是标准缠论"笔"定义的简化实现（未做特征序列分型验证的完整线段构建）。"""
    points = [(t['date'], t['high'], 'top') for t in tops] + [(b['date'], b['low'], 'bottom') for b in bottoms]
    points.sort(key=lambda x: x[0])
    filtered = []
    for p in points:
        if filtered and filtered[-1][2] == p[2]:
            if p[2] == 'top' and p[1] > filtered[-1][1]:
                filtered[-1] = p
            elif p[2] == 'bottom' and p[1] < filtered[-1][1]:
                filtered[-1] = p
        else:
            filtered.append(p)
    bi_list = []
    for i in range(len(filtered) - 1):
        bi_list.append({
            'start_date': filtered[i][0], 'start_price': filtered[i][1],
            'end_date': filtered[i+1][0], 'end_price': filtered[i+1][1],
            'direction': 'up' if filtered[i][2] == 'bottom' else 'down'
        })
    return bi_list


def build_zhongshu_from_bi(bi_list):
    """基于连续3笔的价格区间重叠计算真正的缠论中枢（ZG/ZD），
    而非统计分位数近似。返回最近一个有效中枢（若存在）。"""
    zhongshu_list = []
    for i in range(len(bi_list) - 2):
        b1, b2, b3 = bi_list[i], bi_list[i+1], bi_list[i+2]
        ranges = [(min(b['start_price'], b['end_price']), max(b['start_price'], b['end_price'])) for b in (b1, b2, b3)]
        zd_candidate = max(r[0] for r in ranges)
        zg_candidate = min(r[1] for r in ranges)
        if zg_candidate > zd_candidate:
            zhongshu_list.append({
                'zg': zg_candidate, 'zd': zd_candidate,
                'start_date': b1['start_date'], 'end_date': b3['end_date']
            })
    return zhongshu_list


def analyze_kline_and_chanlun(df):
    """缠论顶底分型、中枢、背驰量化计算（简化版，非完整笔/线段体系）"""
    if df.empty or len(df) < 30:
        return "K线数据不足，无法进行缠论技术分析。"
    df = df.copy()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA50'] = df['Close'].rolling(50).mean()
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    # RSI(14) 真实计算：超买超卖辅助判断
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_latest = rsi.iloc[-1] if not rsi.empty and not pd.isna(rsi.iloc[-1]) else None
    if rsi_latest is not None:
        if rsi_latest >= 70:
            rsi_status = f"RSI(14)={rsi_latest:.1f}，进入超买区间(>=70)"
        elif rsi_latest <= 30:
            rsi_status = f"RSI(14)={rsi_latest:.1f}，进入超卖区间(<=30)"
        else:
            rsi_status = f"RSI(14)={rsi_latest:.1f}，处于中性区间(30-70)"
    else:
        rsi_status = "RSI(14) 数据不足，无法计算"

    # 布林带(20,2) 真实计算：波动率与支撑压力
    boll_mid = df['Close'].rolling(20).mean()
    boll_std = df['Close'].rolling(20).std()
    boll_upper = boll_mid + 2 * boll_std
    boll_lower = boll_mid - 2 * boll_std
    if not boll_upper.empty and not pd.isna(boll_upper.iloc[-1]):
        boll_status = f"布林带(20,2): 上轨={boll_upper.iloc[-1]:.2f}, 中轨={boll_mid.iloc[-1]:.2f}, 下轨={boll_lower.iloc[-1]:.2f}"
    else:
        boll_status = "布林带数据不足，无法计算"

    dates = df.index.strftime('%Y-%m-%d').values
    highs = df['High'].values
    lows = df['Low'].values
    recent_close = df['Close'].iloc[-1]
    pct_1y = ((recent_close - df['Close'].iloc[0]) / df['Close'].iloc[0]) * 100

    top_fractals, bottom_fractals = [], []
    for i in range(1, len(df) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            top_fractals.append((dates[i], highs[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            bottom_fractals.append((dates[i], lows[i]))
    recent_top = top_fractals[-1] if top_fractals else ("无", 0)
    recent_bottom = bottom_fractals[-1] if bottom_fractals else ("无", 0)

    df_60 = df.tail(60)
    zg = df_60['High'].quantile(0.75)
    zd = df_60['Low'].quantile(0.25)

    # ---- 真实缠论结构：K线包含处理 -> 分型 -> 笔 -> 中枢(3笔重叠区间) ----
    zhongshu_note = "笔数不足3笔，无法构建结构化中枢，以下沿用统计分位数近似"
    zg_real, zd_real = None, None
    try:
        merged_k = merge_klines_inclusion(df.tail(120))
        tops_m, bottoms_m = find_fractals_on_merged(merged_k)
        bi_seq = build_bi_sequence(tops_m, bottoms_m)
        zs_list = build_zhongshu_from_bi(bi_seq)
        if zs_list:
            latest_zs = zs_list[-1]
            zg_real, zd_real = latest_zs['zg'], latest_zs['zd']
            zhongshu_note = f"基于最近3笔重叠区间计算(结构化定义): {latest_zs['start_date'].strftime('%Y-%m-%d')} 至 {latest_zs['end_date'].strftime('%Y-%m-%d')}，历史累计识别中枢数={len(zs_list)}"
        elif len(bi_seq) > 0:
            zhongshu_note = f"已识别{len(bi_seq)}笔，但不足3笔重叠形成结构化中枢，以下沿用统计分位数近似"
    except Exception:
        pass
    zg_display = zg_real if zg_real is not None else zg
    zd_display = zd_real if zd_real is not None else zd

    macd_recent = hist.iloc[-1]
    macd_prev_min = hist.tail(30).min()
    if recent_close <= df_60['Low'].min() * 1.03 and macd_recent > macd_prev_min:
        divergence = "底背驰信号（缠论一类买点区间）"
    elif recent_close >= df_60['High'].max() * 0.97 and macd_recent < hist.tail(30).max():
        divergence = "顶背驰信号（潜在回调区）"
    else:
        divergence = "未见背驰，维持区间中枢盘整"

    trend_status = "震荡上行/主升阶段" if pct_1y > 15 else ("震荡下行/回调阶段" if pct_1y < -15 else "近1年宽幅箱体震荡")

    segments = []
    # V10.1：波段图标跟随涨跌语义切换（A股默认红涨绿跌）
    _up_ico, _dn_ico = ('🔴', '🟢') if not st.session_state.get("intl_color_mode", False) else ('🟢', '🔴')
    if len(bottom_fractals) > 0 and len(top_fractals) > 0:
        all_points = [(d, p, 'top') for d, p in top_fractals] + [(d, p, 'bottom') for d, p in bottom_fractals]
        all_points.sort(key=lambda x: x[0])
        for i in range(len(all_points) - 1):
            d1, p1, t1 = all_points[i]
            d2, p2, t2 = all_points[i+1]
            if t1 == 'bottom' and t2 == 'top' and (p2 - p1) / p1 > 0.10:
                segments.append(f"{_up_ico} 上涨: {d1[5:]} ({p1:.2f}) ➔ {d2[5:]} ({p2:.2f}) [+{(p2-p1)/p1*100:.1f}%]")
            elif t1 == 'top' and t2 == 'bottom' and (p1 - p2) / p1 > 0.10:
                segments.append(f"{_dn_ico} 下跌: {d1[5:]} ({p1:.2f}) ➔ {d2[5:]} ({p2:.2f}) [{(p1-p2)/p1*-100:.1f}%]")
    
    segments = segments[-5:]
    segments_html = "".join([f"<div style='background:rgba(255,255,255,0.05); padding:5px 10px; border-radius:5px; margin-bottom:5px; font-size:0.85rem;'>{s}</div>" for s in segments]) if segments else "<div style='opacity:0.6'>近半年未见超10%波段</div>"

    # ---- V10.3：文字技术研判（规则拼接的客观叙述，非主观预测） ----
    try:
        ma20_v = float(df['MA20'].iloc[-1]) if not pd.isna(df['MA20'].iloc[-1]) else None
        ma50_v = float(df['MA50'].iloc[-1]) if not pd.isna(df['MA50'].iloc[-1]) else None
    except Exception:
        ma20_v = ma50_v = None
    _n_parts = []
    _n_parts.append(f"该标的近一年累计涨跌幅 <b>{pct_1y:+.1f}%</b>，整体处于「{trend_status}」格局。")
    if zg_display and zd_display:
        if recent_close > zg_display:
            _pos = f"当前价 <b>{recent_close:.2f}</b> 已站上近60日缠论中枢上沿（{zg_display:.2f}），中枢上沿转化为短期回踩观察位，突破的有效性需后续量能确认"
        elif recent_close < zd_display:
            _pos = f"当前价 <b>{recent_close:.2f}</b> 跌破近60日缠论中枢下沿（{zd_display:.2f}），中枢下沿转为反压位，下方空间打开与否取决于能否快速收复"
        else:
            _pos = f"当前价 <b>{recent_close:.2f}</b> 运行于近60日缠论中枢区间 [{zd_display:.2f}, {zg_display:.2f}] 内部，属典型箱体震荡结构，中枢上下沿分别构成短期压力与支撑参考"
        _n_parts.append(_pos + "。")
    if ma20_v and ma50_v:
        if ma20_v > ma50_v:
            _n_parts.append(f"均线系统呈多头排列迹象（MA20={ma20_v:.2f} 高于 MA50={ma50_v:.2f}），中期趋势动能偏多，MA20 附近构成第一档动态支撑。")
        else:
            _n_parts.append(f"均线系统呈空头排列迹象（MA20={ma20_v:.2f} 低于 MA50={ma50_v:.2f}），中期趋势承压，MA50 附近构成上方动态压力。")
    _n_parts.append(f"动能维度：MACD 最新柱体 {macd_recent:.3f}，{divergence}；{rsi_status}。")
    if '上轨' in boll_status:
        try:
            if recent_close > boll_upper.iloc[-1]:
                _n_parts.append("价格触及布林带上轨上方，短期波动率放大，注意冲高后的均值回归引力")
            elif recent_close < boll_lower.iloc[-1]:
                _n_parts.append("价格跌破布林带下轨，短期超卖特征明显，关注下轨附近的企稳信号")
            else:
                _n_parts.append("价格运行于布林带上下轨之间，波动率处于常态区间")
        except Exception:
            pass
    narrative_html = (
        '<div style="font-size:0.9rem; color:#e2e8f0; font-weight:600; margin:14px 0 8px 0;">📋 技术面综合研判（客观描述 · 非买卖建议）</div>'
        '<div style="background:rgba(11, 17, 32, 0.55); border:1px solid rgba(255,255,255,0.08); '
        'border-radius:10px; padding:14px 16px; font-size:0.85rem; line-height:1.9; color:#D1D4DC;">'
        + "".join(p for p in _n_parts if p)
        + '<div style="font-size:0.72rem; opacity:0.6; margin-top:8px;">以上为量化指标的客观串联描述，全部基于真实K线计算，不构成任何投资建议。</div></div>'
    )

    html = f"""<div style="background:rgba(30, 41, 59, 0.7); padding:20px; border-radius:12px; border:1px solid rgba(255,255,255,0.1); backdrop-filter: blur(10px);">
<h4 style="color:#4B9FFF; margin-bottom:15px; font-size:1.05rem;">【近1年K线量化与缠论指标】</h4>
<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:15px;">
<div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:8px;">
<div style="font-size:0.8rem; color:#94a3b8;">最新收盘 / 趋势</div>
<div style="font-size:1rem; font-weight:600; color:{C_UP if pct_1y>=0 else C_DOWN};">{recent_close:.2f} ({pct_1y:+.2f}%)</div>
<div style="font-size:0.8rem;">{trend_status}</div>
</div>
<div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:8px;">
<div style="font-size:0.8rem; color:#94a3b8;">1年最高 / 最低</div>
<div style="font-size:1rem; font-weight:600;">{df['High'].max():.2f} / {df['Low'].min():.2f}</div>
</div>
<div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:8px;">
<div style="font-size:0.8rem; color:#94a3b8;">近60日中枢轨 (ZG/ZD)</div>
<div style="font-size:1rem; font-weight:600; color:#fbbf24;">{zg_display:.2f} / {zd_display:.2f}</div>
<div style="font-size:0.75rem; opacity:0.7; margin-top:3px;">{zhongshu_note}</div>
</div>
<div style="background:rgba(255,255,255,0.03); padding:10px; border-radius:8px;">
<div style="font-size:0.8rem; color:#94a3b8;">MACD / 辅助判断</div>
<div style="font-size:1rem; font-weight:600;">{macd_recent:.3f}</div>
<div style="font-size:0.75rem; color:{C_UP if '底背驰' in divergence else C_DOWN if '顶背驰' in divergence else '#94a3b8'}; margin-top:3px;">{divergence}</div>
</div>
</div>
<div style="display:flex; gap:10px; margin-bottom:15px; flex-wrap:wrap;">
<span style="background:rgba(56,189,248,0.1); color:#4B9FFF; padding:4px 8px; border-radius:4px; font-size:0.8rem;">均线支撑: MA20={df['MA20'].iloc[-1]:.2f}, MA50={df['MA50'].iloc[-1]:.2f}</span>
<span style="background:rgba(251,191,36,0.1); color:#fbbf24; padding:4px 8px; border-radius:4px; font-size:0.8rem;">{rsi_status}</span>
</div>
<div style="font-size:0.9rem; color:#e2e8f0; font-weight:600; margin-bottom:10px;">📉 波段起止明细 (最近5条)</div>
{segments_html}
{narrative_html}
</div>"""
    return html

# =============================================================================
# 产业链知识库 —— 按 Ticker 代码精确匹配（最高优先级，不依赖 yfinance info 字段）
# =============================================================================
TICKER_CHAIN_DB = {
    # ---- 美股 AI/半导体核心标的 ----
    'NVDA': {
        'up': ['台积电 TSMC (5nm/4nm 晶圆代工)', '三星电子 (HBM3E 高带宽存储)', 'SK海力士 (HBM 供应商)', '阿斯麦 ASML (EUV 光刻机)'],
        'mid_role': 'GPU/AI 加速芯片设计 (数据中心 & 游戏 & 汽车)',
        'down': ['微软 Azure / 谷歌 GCP / 亚马逊 AWS (云厂商)', 'Meta / OpenAI / 字节跳动 (AI 大模型训练)', '特斯拉 (自动驾驶 FSD)', '全球游戏玩家 (GeForce)'],
        'down_note': 'AI 算力需求爆发式增长，NVIDIA 数据中心收入已超过游戏业务成为第一大收入来源，CoWoS 先进封装产能为核心瓶颈'
    },
    'AMD': {
        'up': ['台积电 TSMC (先进制程代工)', '日月光/矽品 (封装测试)', '美光 Micron (DRAM/HBM)'],
        'mid_role': 'CPU/GPU/FPGA 芯片设计 (数据中心 & PC & 嵌入式)',
        'down': ['微软 / 谷歌 / Meta (云数据中心 MI300 系列)', 'PC OEM 厂商 (联想/惠普/戴尔)', '索尼 PS5 / 微软 Xbox (游戏主机定制芯片)'],
        'down_note': 'MI300X 系列 GPU 加速器直接对标 NVIDIA H100，Instinct 产品线在 AI 推理市场份额持续提升'
    },
    'TSM': {
        'up': ['阿斯麦 ASML (EUV 光刻机)', '应用材料 AMAT (CVD/PVD 沉积)', '东京电子 TEL (刻蚀)', '信越化学 (硅晶圆)'],
        'mid_role': '全球最大晶圆代工厂 (3nm/5nm 先进制程)',
        'down': ['苹果 Apple (A/M 系列芯片)', 'NVIDIA (GPU 代工)', '高通 Qualcomm (骁龙芯片)', 'AMD / 联发科 / 博通'],
        'down_note': '全球先进制程代工市占率超 90%，AI 芯片需求推动 CoWoS 先进封装产能持续扩张'
    },
    'AVGO': {
        'up': ['台积电 TSMC (芯片代工)', 'Amkor (封装)', '日本电产 (被动元器件)'],
        'mid_role': '网络/存储/定制 ASIC 芯片设计 & 基础设施软件',
        'down': ['谷歌 TPU (定制 AI 芯片)', '苹果 (Wi-Fi/蓝牙芯片)', '数据中心交换机 (思科/Arista)', '电信运营商 5G 基站'],
        'down_note': '博通 VMware 收购完成后转型为基础设施软件+半导体双引擎，谷歌 TPU 定制 ASIC 为高增长驱动力'
    },
    'INTC': {
        'up': ['阿斯麦 ASML (光刻机)', '应用材料 AMAT', 'Lam Research (刻蚀设备)'],
        'mid_role': 'CPU 设计与 IDM 自有晶圆制造 (Intel Foundry Services)',
        'down': ['PC OEM (联想/惠普/戴尔)', '数据中心 (Xeon 至强)', '美国政府/国防 (CHIPS 法案)'],
        'down_note': 'Intel 18A/20A 制程追赶台积电，IFS 代工业务承接美国本土芯片制造需求'
    },
    'QCOM': {
        'up': ['台积电 TSMC (芯片代工)', '三星 (部分代工)', 'Arm (架构授权)'],
        'mid_role': '移动 SoC 芯片设计 (骁龙) & 5G 基带/射频前端',
        'down': ['三星 / 小米 / OPPO / vivo (安卓手机)', '宝马 / 通用 (汽车座舱芯片)', 'PC 厂商 (骁龙 X Elite 笔记本)'],
        'down_note': '端侧 AI 大模型推理驱动骁龙 8 Gen 3/4 高端芯片升级，汽车/IoT 多元化降低手机依赖'
    },
    'MU': {
        'up': ['应用材料 AMAT (沉积设备)', 'Lam Research (刻蚀设备)', '信越化学 (硅晶圆)'],
        'mid_role': 'DRAM & NAND 存储芯片设计与制造 (IDM)',
        'down': ['NVIDIA / AMD (HBM3E 配套 GPU)', '苹果 / 三星 (手机存储)', '数据中心服务器 (DDR5)'],
        'down_note': 'HBM (高带宽存储) 需求随 AI GPU 出货量同步爆发，美光 HBM3E 产能已被预订至 2025 年底'
    },
    'SMCI': {
        'up': ['NVIDIA (GPU)', 'AMD (CPU/GPU)', '高阶 PCB 供应商', '散热模组/液冷方案商'],
        'mid_role': 'AI 服务器 & 存储系统整机设计与组装',
        'down': ['微软 / Meta / 谷歌 / 亚马逊 (超大规模云厂商)', 'AI 初创企业', '主权 AI 基础设施'],
        'down_note': '超微电脑是 NVIDIA GPU 服务器最大的第三方组装商之一，液冷散热方案为核心差异化竞争力'
    },
    # ---- 美股科技巨头 ----
    'AAPL': {
        'up': ['台积电 TSMC (A/M 系列芯片代工)', '三星 SDI / LG (OLED 屏幕)', '立讯精密 (连接器/组装)', '博通 (Wi-Fi/蓝牙芯片)'],
        'mid_role': 'iPhone / Mac / iPad / Apple Watch / Vision Pro 设计与品牌运营',
        'down': ['全球消费者 (换机周期约 3-4 年)', '运营商渠道 (AT&T/Verizon/中国移动)', 'App Store 开发者生态 (服务收入)'],
        'down_note': '服务业务 (App Store/Apple Music/iCloud) 毛利率超 70%，已成为利润增长第二引擎；Vision Pro 开启空间计算新品类'
    },
    'MSFT': {
        'up': ['NVIDIA (GPU 算力)', 'AMD (CPU/GPU)', '数据中心基础设施 (服务器/光模块)'],
        'mid_role': 'Azure 云计算 & Office 365 & Windows & GitHub Copilot',
        'down': ['全球企业 IT (Office/Teams/Azure)', 'OpenAI 合作伙伴 (Copilot AI 生态)', '游戏玩家 (Xbox/动视暴雪)'],
        'down_note': 'Azure AI 服务收入同比增速超 50%，Copilot 企业版付费用户快速增长，OpenAI 独家云合作伙伴'
    },
    'GOOGL': {
        'up': ['自研 TPU (谷歌 Tensor 芯片)', 'NVIDIA (GPU 训练集群)', '博通 Broadcom (定制 ASIC)'],
        'mid_role': 'Google 搜索 & YouTube 广告 & GCP 云 & Waymo 自动驾驶 & Android',
        'down': ['全球广告主 (搜索/YouTube 广告)', '企业云客户 (GCP)', 'Android 手机生态 (三星/小米)'],
        'down_note': 'Gemini 大模型深度整合搜索与云服务，YouTube 广告收入持续两位数增长，Waymo 商业化落地加速'
    },
    'AMZN': {
        'up': ['NVIDIA / Intel (数据中心芯片)', '自研 Graviton ARM 芯片 & Trainium AI 芯片', '物流基础设施 (机器人/仓储)'],
        'mid_role': 'AWS 云计算 (全球第一) & 电商零售 & Prime 会员 & Alexa',
        'down': ['全球企业 (AWS 云服务)', '消费者 (电商/Prime Video)', '第三方卖家 (FBA 物流)'],
        'down_note': 'AWS 占全球云市场份额 31%，Bedrock 托管式 AI 服务增长迅猛，电商广告业务已成为第三增长极'
    },
    'META': {
        'up': ['NVIDIA (GPU 训练集群, H100/B200)', '博通 (定制 MTIA 芯片)', '数据中心基础设施'],
        'mid_role': 'Facebook / Instagram / WhatsApp 社交广告 & Reality Labs (Quest VR)',
        'down': ['全球广告主 (精准社交广告)', '消费者 (社交/Reels 短视频)', 'VR/AR 开发者生态'],
        'down_note': 'Llama 开源大模型生态持续扩张，Reels 短视频广告变现效率快速提升，AI 驱动广告推荐精准度'
    },
    'NFLX': {
        'up': ['内容制作工作室 (好莱坞/韩国/日本)', '云基础设施 (AWS)', 'CDN 网络'],
        'mid_role': '全球流媒体平台 (原创内容 + 广告套餐)',
        'down': ['全球 2.8 亿付费用户', '广告主 (广告支持套餐)', '内容授权方'],
        'down_note': '广告支持套餐 (含广告低价版) 用户增长强劲，密码共享打击策略转化为付费用户增量'
    },
    'TSLA': {
        'up': ['宁德时代 / 比亚迪 / 松下 (动力电池)', '自研 FSD 芯片 (HW4.0)', '博世 / 英飞凌 (车规级芯片)'],
        'mid_role': '纯电动汽车制造 & 自动驾驶 FSD & 储能 (Megapack) & 人形机器人 (Optimus)',
        'down': ['全球消费者 (Model 3/Y/S/X)', '储能/电力公司 (Megapack 大储)', '未来 Robotaxi 出行平台'],
        'down_note': 'FSD 完全自动驾驶软件订阅为高毛利增长点，Megapack 储能业务装机量同比翻倍，Optimus 人形机器人远期想象空间巨大'
    },
    # ---- A 股核心标的 (按 yfinance ticker 格式) ----
    '600519.SS': {
        'up': ['高粱/小麦种植基地 (贵州/四川)', '包材企业 (玻璃瓶/纸箱/瓶盖)', '酒曲/微生物发酵技术'],
        'mid_role': '贵州茅台：酱香型白酒酿造 & 品牌运营 (飞天/生肖/精品系列)',
        'down': ['经销商/专卖店体系 (全国 2000+ 经销商)', '电商直营 (i茅台/天猫旗舰店)', '商务/宴请/收藏消费场景'],
        'down_note': '飞天茅台出厂价 1169 元，终端市场价约 2500 元，渠道利润丰厚；i茅台 App 直销占比持续提升'
    },
    '300750.SZ': {
        'up': ['天齐锂业/赣锋锂业 (碳酸锂)', '容百科技 (正极材料)', '恩捷股份 (隔膜)', '天赐材料 (电解液)'],
        'mid_role': '宁德时代：动力电池 & 储能电池研发制造 (全球市占率 37%)',
        'down': ['特斯拉 / 宝马 / 奔驰 / 蔚来 / 理想 (新能源车企)', '储能电站运营商', '电动船舶/矿卡'],
        'down_note': '麒麟电池/神行超充电池为技术领先产品，海外产能布局匈牙利/德国工厂，钠离子电池量产在即'
    },
    '002594.SZ': {
        'up': ['比亚迪半导体 (自研 IGBT/SiC)', '比亚迪弗迪电池 (刀片电池垂直整合)', '自研电驱/电控系统'],
        'mid_role': '比亚迪：新能源汽车整车 + 动力电池 + 半导体全产业链垂直整合',
        'down': ['国内消费者 (王朝/海洋/仰望/方程豹系列)', '海外市场 (东南亚/欧洲/南美)', '公交/出租车队'],
        'down_note': '全球新能源汽车销量冠军，刀片电池垂直整合降本优势显著，智能驾驶 "天神之眼" 加速迭代'
    },
    '688981.SS': {
        'up': ['北方华创 (刻蚀/CVD 设备)', '中微公司 (刻蚀设备)', '沪硅产业 (硅片)', '盛美上海 (清洗设备)'],
        'mid_role': '中芯国际：中国大陆最大晶圆代工厂 (14nm/28nm 成熟制程)',
        'down': ['高通 / 联发科 (成熟制程芯片代工)', '兆易创新 / 韦尔股份 (国内设计公司)', '汽车/工业/IoT 芯片需求'],
        'down_note': '美国实体清单限制先进设备进口，聚焦 28nm 及以上成熟制程扩产，国产替代订单持续增加'
    },
    '300502.SZ': {
        'up': ['光芯片供应商 (II-VI/Lumentum)', '高速 DSP 芯片 (博通/Marvell)', '精密光学元器件'],
        'mid_role': '新易盛：高速光模块研发制造 (800G/1.6T 数据中心光模块)',
        'down': ['谷歌 / 亚马逊 / Meta / 微软 (北美云厂商)', '中国移动/电信/联通 (5G 前传)', 'AI 算力集群互联'],
        'down_note': '800G 光模块放量出货，1.6T 产品研发领先，北美头部云厂商为核心客户，AI 算力互联需求爆发'
    },
    '300308.SZ': {
        'up': ['光芯片/EML 激光器', '高速 DSP (博通 Tomahawk)', 'VCSEL/硅光芯片'],
        'mid_role': '中际旭创：全球光模块龙头 (800G/1.6T 数据中心光互联)',
        'down': ['谷歌 / 亚马逊 / Meta / 微软 (全球云厂商)', 'AI 训练集群 (GPU 间高速互联)', '5G 承载网'],
        'down_note': '全球 800G 光模块市占率第一，1.6T LPO 光模块率先送样，受益 AI 算力基建投资周期'
    },
    '002371.SZ': {
        'up': ['高纯靶材/气体/化学品', '精密机械加工', '自研核心零部件'],
        'mid_role': '北方华创：半导体设备龙头 (刻蚀/CVD/PVD/氧化扩散炉)',
        'down': ['中芯国际 / 长江存储 / 华虹半导体 (国内晶圆厂)', '京东方 / 华星光电 (面板厂)', '光伏电池片厂商'],
        'down_note': '国产半导体设备替代率持续提升，刻蚀/薄膜沉积设备进入主流产线验证，光伏设备贡献增量收入'
    },
    '002475.SZ': {
        'up': ['连接器精密模具', '自动化组装产线', '精密金属/塑胶零部件'],
        'mid_role': '立讯精密：消费电子精密制造 (苹果 AirPods/Apple Watch/iPhone 组装)',
        'down': ['苹果 Apple (第一大客户)', '华为 / 小米 (安卓生态)', '汽车 Tier 1 (线束/连接器)'],
        'down_note': '苹果 iPhone 整机组装份额持续提升，汽车线束/连接器业务为第二增长曲线'
    },
    '600036.SS': {
        'up': ['央行货币政策 (MLF/LPR)', '同业资金市场', '债券/票据市场'],
        'mid_role': '招商银行：零售银行之王 (财富管理 & 信用卡 & 个人贷款)',
        'down': ['个人客户 (1.9 亿零售客户)', '小微企业贷款', '私人银行/财富管理客户'],
        'down_note': '零售 AUM 规模超 13 万亿，财富管理手续费收入行业领先，ROE 连续多年保持 15%+'
    },
    '601318.SS': {
        'up': ['再保险公司 (慕尼黑再/瑞士再)', '医疗/汽车服务网络', '投资市场 (权益/固收)'],
        'mid_role': '中国平安：综合金融集团 (保险 + 银行 + 科技)',
        'down': ['个人保险客户 (2.3 亿+)', '企业团险客户', '平安银行/陆金所用户'],
        'down_note': '寿险改革"新模式"推动 NBV 恢复增长，医疗养老生态圈构建中，科技赋能降本增效'
    },
    # ---- 港股核心标的 ----
    '0700.HK': {
        'up': ['云计算基础设施 (自建数据中心)', 'NVIDIA/AMD (GPU 算力)', '内容创作者/游戏开发商'],
        'mid_role': '腾讯控股：社交 (微信/QQ) + 游戏 + 云 + 金融科技',
        'down': ['12 亿微信用户 (社交/支付)', '全球游戏玩家 (王者荣耀/原神代理)', '企业微信/腾讯云客户'],
        'down_note': '视频号广告/小程序电商为新增长引擎，海外游戏收入占比持续提升，混元大模型赋能内部产品'
    },
    '1810.HK': {
        'up': ['高通 (骁龙芯片)', '三星/京东方 (屏幕)', '索尼 (摄像头传感器)'],
        'mid_role': '小米集团：智能手机 + AIoT 生态 + 小米汽车 SU7',
        'down': ['全球消费者 (手机/IoT 设备)', '小米之家线下渠道', '小米汽车车主'],
        'down_note': '小米 SU7 交付量快速爬坡，高端手机份额提升，AIoT 连接设备数超 7 亿台'
    },
    '3690.HK': {
        'up': ['云计算基础设施', '配送骑手网络 (超 700 万骑手)', '商户合作伙伴'],
        'mid_role': '美团：本地生活服务平台 (外卖 + 到店 + 酒旅 + 优选)',
        'down': ['消费者 (外卖/团购/酒店预订)', '餐饮/零售商户', '酒店/旅游服务商'],
        'down_note': '即时零售 (美团闪购) 高速增长，海外业务 (Keeta) 拓展东南亚，AI 提升配送效率'
    },
    'BABA': {
        'up': ['云计算基础设施 (阿里云)', '物流网络 (菜鸟)', '支付系统 (支付宝/蚂蚁)'],
        'mid_role': '阿里巴巴：电商 (淘宝/天猫/1688) + 阿里云 + 本地生活 + 国际电商',
        'down': ['消费者 (淘宝/天猫 9 亿活跃用户)', '品牌商家/中小卖家', '企业云客户 (阿里云)'],
        'down_note': '1688 平源厂货模式增长强劲，阿里云 AI 推理服务收入高速增长，国际电商 (Lazada/AliExpress) 扩张'
    },
    'PDD': {
        'up': ['中国制造业产业带工厂', '物流合作伙伴 (极兔/中通)', '云基础设施'],
        'mid_role': '拼多多：社交电商 (拼多多国内) + 跨境电商 (Temu)',
        'down': ['价格敏感型消费者 (下沉市场)', 'Temu 全球用户 (北美/欧洲/日韩)', '农产品消费者'],
        'down_note': 'Temu 全托管模式快速渗透欧美市场，国内百亿补贴持续获客，利润率远超行业平均'
    },
    'JD': {
        'up': ['品牌供应商 (家电/3C 直采)', '京东物流 (自建仓配网络)', '达达集团 (即时配送)'],
        'mid_role': '京东：自营电商 (家电/3C 优势) + 京东物流 + 京东健康',
        'down': ['品质消费者 (一二线城市)', '企业采购客户', '京东 PLUS 会员'],
        'down_note': '自营供应链物流体验行业领先，京东物流外部客户收入占比持续提升，低价策略拓展下沉市场'
    },
    'BIDU': {
        'up': ['NVIDIA (GPU 算力)', '自研昆仑芯片', '数据中心基础设施'],
        'mid_role': '百度：搜索广告 + 文心一言大模型 + Apollo 自动驾驶 + 百度智能云',
        'down': ['广告主 (搜索/信息流广告)', '萝卜快跑 Robotaxi 乘客', '企业 AI 云客户'],
        'down_note': '文心大模型 API 日调用量突破 5 亿次，萝卜快跑 Robotaxi 在武汉等城市商业化运营'
    },
}

# 产业链知识库：按行业/板块映射上中下游（二级回退）
CHAIN_DB = {
    'Auto Manufacturers': {
        'up': ['宁德时代 (电池)', '博世 (Bosch, 零部件)', '英飞凌 (芯片)'],
        'mid_role': '整车制造 & 智能驾驶',
        'down': ['消费者市场 (换车周期约6-8年)', '出行平台 (Uber/滴滴)', '政府采购/租赁'],
        'down_note': '全球汽车渗透率趋饱和，新能源渗透率快速攀升（中国>40%，欧洲>25%），消费信心与利率水平直接影响购车意愿'
    },
    'Semiconductors': {
        'up': ['阿斯麦 (ASML, 光刻机)', '应用材料 (AMAT, 沉积)', '信越化学 (硅片)'],
        'mid_role': '芯片设计 / 代工制造',
        'down': ['智能手机 (苹果/三星/小米)', '数据中心/AI服务器 (NVIDIA/微软)', '汽车/工业电子'],
        'down_note': 'AI 算力爆发拉动先进制程 (3nm/5nm) 及 HBM 存储供不应求，消费电子复苏带动成熟制程回暖'
    },
    'Semiconductor Equipment & Materials': {
        'up': ['高纯金属与气体', '光学镜片 (蔡司)', '精密机械构件'],
        'mid_role': '半导体设备研发与制造',
        'down': ['晶圆代工厂 (台积电/中芯国际)', '存储芯片厂 (三星/海力士/美光)', 'IDM 厂商 (Intel/TI)'],
        'down_note': '全球晶圆厂资本开支持续高位，国产化替代加速，先进封装 (CoWoS) 设备需求景气度极高'
    },
    'Software—Infrastructure': {
        'up': ['数据中心服务器 (戴尔/浪潮)', '高速光模块', '云算力芯片 (GPU/TPU)'],
        'mid_role': '云计算 & 基础软件/数据库',
        'down': ['企业级 IT 部门', 'SaaS 应用开发者', '互联网与金融机构'],
        'down_note': '生成式 AI 推动企业级云服务从传统 IaaS 向 PaaS/MaaS 深度升级，软件订阅收入年化增速超 20%'
    },
    'Internet Content & Information': {
        'up': ['云计算基础设施', 'GPU 算力 (NVIDIA/AMD)', '内容创作者/开发者'],
        'mid_role': '互联网平台 & 信息服务',
        'down': ['消费者用户 (搜索/社交/购物)', '广告主 (品牌/效果广告)', '企业级 SaaS/云客户'],
        'down_note': 'AI 大模型重塑搜索与推荐引擎，短视频/直播电商成为流量变现核心场景'
    },
    'Internet Retail': {
        'up': ['品牌供应商/工厂', '物流网络 (仓储/配送)', '支付系统'],
        'mid_role': '电商零售平台',
        'down': ['消费者 (线上购物)', '第三方卖家/品牌商', '广告主'],
        'down_note': '即时零售与社交电商持续增长，跨境电商全托管模式加速全球化扩张'
    },
    'Hardware, Tech Supply Chain': {
        'up': ['高阶 PCB 板', '高速光模块 (800G/1.6T)', '电源/散热模组'],
        'mid_role': 'AI 服务器整机集成与封装',
        'down': ['微软 / 谷歌 / 亚马逊 / Meta (云厂商)', 'AI 大模型初创企业', '科研机构与算力中心'],
        'down_note': 'AI算力需求爆发式增长，云厂商资本开支持续上行，数据中心GPU供不应求'
    },
    'Consumer Electronics': {
        'up': ['台积电 (芯片代工)', '三星SDI (屏幕)', '立讯精密 (连接器)'],
        'mid_role': '消费电子品牌研发',
        'down': ['全球消费者', '运营商渠道', '电商平台 (Amazon/京东)'],
        'down_note': '端侧 AI 手机与 XR 设备开启换机新周期，高端产品线份额稳步提升'
    },
    'Beverages—Wineries & Distilleries': {
        'up': ['高粱/小麦供应商', '包材企业 (玻璃瓶/纸箱)', '酒曲/微生物技术'],
        'mid_role': '白酒酿造 & 品牌运营',
        'down': ['经销商/专卖店体系', '电商直营 (天猫/京东)', '商务/宴请消费场景'],
        'down_note': '高端白酒受宏观经济与商务消费驱动，消费升级趋势持续，库存周期约2-3年'
    },
    'Electrical Equipment & Parts': {
        'up': ['碳酸锂 (天齐锂业/赣锋)', '正极材料 (容百科技)', '隔膜 (恩捷股份)'],
        'mid_role': '动力电池/储能制造',
        'down': ['新能源车企 (特斯拉/比亚迪)', '储能电站', '消费电子电池'],
        'down_note': '全球电动车渗透率加速，储能需求受可再生能源装机驱动，锂价波动影响全链利润'
    },
    'Banks—Regional': {
        'up': ['央行货币政策 (MLF/LPR)', '同业资金市场', '债券市场'],
        'mid_role': '商业银行 (存贷款/财富管理)',
        'down': ['个人客户 (储蓄/房贷/消费贷)', '企业客户 (经营贷/贸易融资)', '政府/城投融资'],
        'down_note': '利率下行周期压缩净息差，财富管理与中间业务收入成为转型方向'
    },
    'Insurance—Diversified': {
        'up': ['再保险公司', '医疗/养老服务网络', '投资市场'],
        'mid_role': '综合保险/金融集团',
        'down': ['个人保险客户', '企业团险客户', '理财/资管客户'],
        'down_note': '寿险负债端转型推动 NBV 恢复，养老/健康生态圈构建为长期看点'
    },
    'Communication Equipment': {
        'up': ['光芯片 (II-VI/Lumentum)', '高速 DSP (博通/Marvell)', '精密光学元件'],
        'mid_role': '光通信设备/光模块制造',
        'down': ['云厂商数据中心 (谷歌/AWS/Meta)', '电信运营商 (5G 建设)', 'AI 算力互联'],
        'down_note': '800G/1.6T 光模块需求随 AI 集群扩建爆发，硅光技术为下一代方向'
    },
    'Electronic Components': {
        'up': ['精密模具/自动化设备', '金属/塑胶/陶瓷原材料', '电镀/表面处理'],
        'mid_role': '精密电子零部件制造',
        'down': ['苹果/华为 (消费电子)', '汽车 Tier 1 (线束/连接器)', '5G 基站设备商'],
        'down_note': '消费电子精密制造向汽车电子延伸，智能汽车零部件为第二增长曲线'
    },
}

def build_chain_html(info, ticker):
    """构建产业链定位图：优先按 Ticker 精确匹配，其次按 industry/sector 模糊匹配，无数据时明确提示而非通用描述"""
    sector = info.get('sector', '')
    industry = info.get('industry', '')
    name = info.get('shortName', ticker)

    # 第一优先级：按 Ticker 代码精确查找（不依赖 yfinance 的 industry 字段）
    tk_clean = ticker.upper().replace('.SS', '.SS').replace('.SZ', '.SZ')
    chain = TICKER_CHAIN_DB.get(tk_clean, None)

    # 第二优先级：按 industry 精确匹配
    if chain is None and industry:
        chain = CHAIN_DB.get(industry, None)

    # 第三优先级：按 industry/sector 模糊匹配
    if chain is None and (industry or sector):
        for key in CHAIN_DB:
            if (industry and key.lower() in industry.lower()) or (sector and key.lower() in sector.lower()):
                chain = CHAIN_DB[key]
                break

    # 无数据时：明确提示，彻底禁止通用占位描述
    if chain is None:
        industry_display = industry or '未获取到行业信息'
        return f"""<div style="margin:1.5rem 0; padding:25px; background:rgba(30, 41, 59, 0.7); border-radius:16px; border:1px solid rgba(255,255,255,0.1); backdrop-filter: blur(10px);">
<div style="text-align:center; font-size:1.15rem; font-weight:700; color:#4B9FFF; margin-bottom:1rem;">🌐 {name} 产业链生态定位图谱</div>
<div style="text-align:center; padding:2rem; color:#94a3b8; font-size:0.95rem;">
<div style="font-size:2rem; margin-bottom:1rem;">📭</div>
<div style="margin-bottom:0.5rem;">暂无 <b style="color:#4B9FFF;">{name} ({ticker})</b> 的专属产业链数据</div>
<div style="font-size:0.82rem; opacity:0.7;">行业: {industry_display} | 板块: {sector or '未获取'}</div>
<div style="font-size:0.82rem; opacity:0.6; margin-top:1rem;">本站严格遵循"无专属数据不展示"原则，绝不使用通用描述占位。</div>
</div>
</div>"""

    up_li = ''.join([f'<li style="margin-bottom:6px;">{c}</li>' for c in chain['up']])
    down_li = ''.join([f'<li style="margin-bottom:6px;">{c}</li>' for c in chain['down']])

    return f"""<div style="margin:1.5rem 0; width:100%; padding:25px; background:rgba(30, 41, 59, 0.7); border-radius:16px; border:1px solid rgba(255,255,255,0.1); backdrop-filter: blur(10px); box-shadow: 0 10px 30px rgba(0,0,0,0.2);">
<div style="text-align:center; font-size:1.15rem; font-weight:700; margin-bottom:1.5rem; color:#4B9FFF; letter-spacing:1px;">🌐 {name} 产业链生态定位图谱</div>
<div class="chain-grid">
<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:20px; box-shadow:inset 0 0 20px rgba(0,0,0,0.2);">
<div style="font-size:0.95rem; font-weight:700; color:#94a3b8; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:10px; margin-bottom:15px; display:flex; align-items:center; gap:8px;"><span>🏭</span> <span>上游 (Upstream)</span></div>
<ul style="font-size:0.85rem; padding-left:20px; margin:0; line-height:1.6; color:#e2e8f0;">{up_li}</ul>
</div>
<div class="chain-arrow">➔</div>
<div style="background:linear-gradient(145deg, rgba(56,189,248,0.15) 0%, rgba(14,165,233,0.05) 100%); border:1px solid rgba(56,189,248,0.4); border-radius:12px; padding:20px; box-shadow:0 8px 25px rgba(56,189,248,0.15); display:flex; flex-direction:column; justify-content:center; align-items:center;">
<div style="font-size:0.95rem; font-weight:700; color:#4B9FFF; margin-bottom:12px; letter-spacing:1px;">⚙️ 中游 (Midstream)</div>
<div style="font-size:1.4rem; font-weight:900; color:#ffffff; text-align:center; text-shadow: 0 2px 4px rgba(0,0,0,0.5);">{name}</div>
<div style="font-size:0.88rem; opacity:0.9; margin-top:12px; text-align:center; background:rgba(0,0,0,0.2); padding:6px 12px; border-radius:6px;">{chain['mid_role']}</div>
</div>
<div class="chain-arrow">➔</div>
<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:20px; box-shadow:inset 0 0 20px rgba(0,0,0,0.2);">
<div style="font-size:0.95rem; font-weight:700; color:#94a3b8; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:10px; margin-bottom:15px; display:flex; align-items:center; gap:8px;"><span>🛒</span> <span>下游 (Downstream)</span></div>
<ul style="font-size:0.85rem; padding-left:20px; margin:0; line-height:1.6; color:#e2e8f0;">{down_li}</ul>
</div>
</div>
<div style="text-align:center; font-size:0.82rem; margin-top:1.8rem; color:#94a3b8; background:rgba(0,0,0,0.2); padding:10px; border-radius:8px;">
📌 {chain['down_note']}
</div>
</div>"""


def get_stock_profile(ticker_input, info, mapped_name="", institutional_holders_df=None):
    """V7 战役一：机构/大股东持仓一律走 fundamentals 多接口级联真实抓取。

    级联顺序（A 股）：东财十大流通股东 → 东财十大股东 → 流通股东明细；
    级联顺序（美/港股）：13F institutional_holders → mutualfund_holders → insider_roster。
    任一接口成功即返回真实披露数据并附带来源；全部失败则 names 为空 + 记录失败原因，
    由 UI 层用 st.warning 明示"监管未披露或接口限流，真实数据缺失"，绝不编造占位股东。
    """
    s_name = mapped_name or info.get('shortName') or ticker_input
    pure_code = ticker_input.replace('.SS', '').replace('.SZ', '').replace('.BJ', '').replace('.HK', '')
    is_a_share = ticker_input.endswith(('.SS', '.SZ', '.BJ')) or pure_code.isdigit()

    inst_names, inst_shares, inst_source, inst_error = [], [], "", None
    try:
        res = fetch_institutional_holdings(
            ticker_input, bool(is_a_share), pure_code, info.get('sharesOutstanding')
        )
        inst_names = res.get('names') or []
        inst_shares = res.get('shares') or []
        inst_source = res.get('source') or ""
        inst_error = res.get('error')
    except Exception as e:
        inst_error = f"持仓抓取引擎异常: {type(e).__name__}: {e}"

    # 二次兜底：主流程已缓存的 yfinance 机构持仓表（仍是真实数据，不是编造）
    if not inst_names and institutional_holders_df is not None:
        try:
            # [已内联] from fundamentals import _parse_yf_holder_df
            n2, s2 = _parse_yf_holder_df(institutional_holders_df, info.get('sharesOutstanding'))
            if n2:
                inst_names, inst_shares = n2, s2
                inst_source = "yfinance institutional_holders（主流程缓存，真实 13F 披露）"
                inst_error = None
        except Exception:
            pass

    return {
        'display_name': s_name,
        'sub_sector': info.get('industry') or "行业字段未披露",
        'inst_names': inst_names,
        'inst_shares': inst_shares,
        'inst_source': inst_source,
        'inst_error': inst_error,
        'is_a_share': bool(is_a_share),
        'pure_code': pure_code,
    }

# -------------------------------------------------------------------
# 5. 主界面：标的概览与 5 维基础卡片
# -------------------------------------------------------------------
ticker_input, mapped_name = resolve_ticker(user_ticker_raw)
if mapped_name and mapped_name != ticker_input:
    st.caption(f"💡 自动解析标的名称 **{mapped_name}** → 代码 **{ticker_input}**")

summary_data = "暂无数据"
all_data = None

if ticker_input:
    try:
        with st.spinner(f"正在采集 {ticker_input} 全量多源数据..."):
            all_data = fetch_all_data(ticker_input)
        info = all_data['info']
        hist_1y = all_data.get('hist_1y')

        # 多重容错价格提取（针对美股/A股接口）
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if (current_price is None or current_price == "N/A" or current_price == "无") and hist_1y is not None and not hist_1y.empty:
            current_price = round(float(hist_1y['Close'].iloc[-1]), 2)

        currency = info.get("currency", "")
        if not currency and (ticker_input.endswith(('.SS', '.SZ')) or all_data.get('is_a_share')):
            currency = "元"

        current_price_str = f"{current_price:.2f} {currency}".strip() if isinstance(current_price, (int, float)) else str(current_price or "暂无行情")

        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        pe_str = f"{pe_ratio:.2f}" if isinstance(pe_ratio, (int, float)) else "N/A"

        market_cap = info.get("marketCap")
        if isinstance(market_cap, (int, float)):
            cap_str = f"{market_cap / 1e12:.2f} 万亿" if market_cap >= 1e12 else (f"{market_cap / 1e8:.2f} 亿" if market_cap >= 1e8 else f"{market_cap:,}")
        else:
            cap_str = "N/A"

        rev_growth = info.get("revenueGrowth")
        rev_str = f"{rev_growth * 100:.2f}%" if isinstance(rev_growth, (int, float)) else "N/A"
        industry = info.get("industry") or mapped_name or "N/A"
        sector = info.get("sector") or "N/A"

        summary_data = f"""
        - 代码/名称: {ticker_input} ({info.get('shortName', mapped_name or ticker_input)})
        - 当前价格: {current_price_str}
        - 行业板块: {sector} / {industry}
        - 市盈率 (PE TTM): {pe_str}
        - 总市值: {cap_str}
        - 营收增速: {rev_str}
        - 52周高/低: {info.get('fiftyTwoWeekHigh', 'N/A')} / {info.get('fiftyTwoWeekLow', 'N/A')}
        - 毛利率: {info.get('grossMargins', 'N/A')}
        - ROE: {info.get('returnOnEquity', 'N/A')}
        """

        st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

    except Exception as e:
        st.error(f"⚠️ 无法拉取标的行情数据，请检查网络或代码名称: {e}")

# -------------------------------------------------------------------
# 6. 点击生成数据聚合报告
# -------------------------------------------------------------------
if generate_btn:
    if not api_key_input:
        st.warning("⚠️ 请输入 API 密钥 (智谱清言 ZHIPU_API_KEY 或 OpenAI API Key)")
    elif not all_data or all_data.get('hist_1y') is None:
        st.error("⚠️ 未能成功获取该标的的行情数据（可能是接口限流 Too Many Requests 或代码有误），请稍后重试或更换标的。")
    else:

        status_box = st.status(f"🚀 **正在为 [{ticker_input}] 采集与整理客观数据...**", expanded=True)
        with status_box:
            st.write("🔍 **步骤 1/5: 读取多源新闻快讯...**")
            news_for_prompt = ""
            yf_news = all_data.get('news', []) if all_data else []
            ak_news = all_data.get('ak_news') if all_data else None
            for n in yf_news[:5]:
                news_for_prompt += f"- [{n.get('publisher', '')}] {n.get('title', '')}\n"
            if ak_news is not None and not ak_news.empty:
                for _, row in ak_news.head(5).iterrows():
                    title = row.get('新闻标题', '')
                    source = row.get('文章来源', '东方财富')
                    news_for_prompt += f"- [{source}] {title}\n"
            if not news_for_prompt:
                news_for_prompt = "暂未通过接口读取到近期个股新闻。"
            time.sleep(0.3)

            st.write("📊 **步骤 2/5: 读取近1年 K 线与财务报表数据**")
            chanlun_text = analyze_kline_and_chanlun(all_data['hist_1y'])
            time.sleep(0.3)

            st.write("📈 **步骤 3/5: 缠论技术结构量化计算（简化版）**")
            time.sleep(0.3)

            st.write("🎯 **步骤 4/5: 第三方分析师历史数据与机构持仓解析**")
            analyst_data = ""
            targets = all_data.get('analyst_targets')
            currency = all_data['info'].get('currency', '')
            if isinstance(targets, dict) and targets:
                analyst_data += f"第三方分析师目标价(历史事实): 当前={fmt_price_val(targets.get('current'), currency)}, 均值={fmt_price_val(targets.get('mean'), currency)}, 中位={fmt_price_val(targets.get('median'), currency)}, 最高={fmt_price_val(targets.get('high'), currency)}, 最低={fmt_price_val(targets.get('low'), currency)}\n"
            recs = all_data.get('recommendations')
            if recs is not None and not recs.empty:
                latest = recs.iloc[0]
                analyst_data += f"最新评级人数分布(第三方历史事实): 强烈推荐={latest.get('strongBuy',0)}, 买入={latest.get('buy',0)}, 持有={latest.get('hold',0)}, 卖出={latest.get('sell',0)}\n"
            ak_forecast = all_data.get('ak_forecast')
            if ak_forecast is not None and not ak_forecast.empty:
                analyst_data += f"东方财富盈利预测一致预期(第三方历史事实):\n{ak_forecast.head(5).to_string()}\n"
            inst = all_data.get('institutional_holders')
            if inst is not None and not inst.empty:
                analyst_data += f"机构持仓Top5(第三方历史事实):\n{inst.head(5).to_string()}\n"
            if not analyst_data:
                analyst_data = "暂未读取到第三方分析师预期数据。"
            time.sleep(0.3)

            st.write("📝 **步骤 5/5: 合成客观数据摘要报告...**")
            time.sleep(0.2)

        # ⚠️ v2.0 重新定位：LLM 仅做"客观事实摘要与翻译"，不生成投资评级/目标价/仓位建议。
        prompt = f"""
你是一名严格的财经信息摘要助手。请针对股票 **{ticker_input}**，基于以下真实抓取的客观数据，撰写一份**纯粹事实性摘要报告**。

【核心要求（严格遵守，违反视为任务失败）】
1. 绝对不允许生成任何投资评级（如"买入"/"增持"/"强烈推荐"）、目标价推荐、仓位配置建议。
2. 绝对不允许编造未在下方数据中出现的具体数字（如营收、利润、目标价）。数据缺失时必须明确写"数据缺失"。
3. 新闻摘要只做"客观事实压缩转述"，不做"这对股价意味着什么"的预测性判断；如需分类事件性质，只能用"正面/负面/中性事件描述"这种基于新闻内容本身的客观分类，不能用"利好/利空"这类带交易暗示的词。
4. 所有内容必须标注来源（如"来源：yfinance"/"来源：akshare"/"第三方机构历史观点，非本报告判断"）。

【基础行情与财务数据（真实抓取）】
{summary_data}

【多源新闻快讯（真实抓取）】
{news_for_prompt}

【近1年K线量化与缠论指标（程序计算，非编造）】
{chanlun_text}

【第三方分析师历史数据与机构持仓（真实抓取，历史事实）】
{analyst_data}

---

### 【报告大纲（仅做客观陈述，不做结论性判断）】

#### 一、 基础数据客观摘要
- 1.1 行情与估值数据的客观陈述（严禁编造，缺失写"数据缺失"）
- 1.2 第三方分析师评级人数分布与目标价历史区间（明确标注"第三方历史观点，非本报告判断"）

#### 二、 产业链上下游客观描述
- 2.1 已知的上下游合作方/客户群体（如有真实数据支持）
- 2.2 若无法获取真实产业链数据，请明确写"数据缺失，无法提供具体产业链细节"

#### 三、 主营业务客观描述
- 3.1 主营业务与产品线（基于真实数据，缺失写"数据缺失"）
- 3.2 同行业上市公司列表（仅在能验证真实性时列出，否则写"数据缺失，无法提供可验证的同行对比"）

#### 四、 缠论技术面数据摘要
- 4.1 直接转述程序计算出的顶底分型、中枢区间、MACD背驰结果（不做买卖点推荐）

#### 五、 财务数据客观摘要
- 5.1 财务核心指标客观陈述（严禁编造，缺失写"数据缺失"）
- 5.2 第三方分析师EPS/营收增速预测（标注"第三方历史观点"）

#### 六、 事件与关注变量
- 6.1 已知的真实公司专属事件（如财报日期）
- 6.2 新闻事件性质客观分类（正面/负面/中性事件描述，不做利好利空判断）

**输出要求**: 使用规范 Markdown 格式，语言客观克制，禁止使用任何带有引导性/结论性的投资建议措辞。
"""

        base_url = "https://open.bigmodel.cn/api/paas/v4/"
        if api_key_input.startswith("sk-proj-"):
            base_url = "https://api.openai.com/v1"
        client = OpenAI(api_key=api_key_input, base_url=base_url)

        try:
            response = client.chat.completions.create(
                model="glm-4-flash" if "bigmodel" in base_url else "gpt-4o",
                messages=[
                    {"role": "system", "content": "你是严格的客观信息摘要助手，只做事实性转述，绝不生成投资建议、评级或目标价推荐。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )
            ai_reply = response.choices[0].message.content
            status_box.update(label="✅ **客观数据摘要报告已生成！**", state="complete", expanded=False)

        except Exception as e:
            status_box.update(label="❌ **AI 调用失败**", state="error", expanded=True)
            st.error(f"AI 调用失败: {e}")

if ticker_input and all_data and all_data.get('hist_1y') is not None:
    info = all_data.get('info', {}) or {}

    # ===== V7 战役二：深度基本面穿透指标（EBITDA/现金流含金量/杜邦/研发/PEG）=====
    try:
        adv_metrics = compute_advanced_metrics(all_data)
    except Exception as e:
        adv_metrics = {}
        st.warning(f"⚠️ 深度指标引擎异常，本次仅展示基础数据：{type(e).__name__}")

    # ===== 近 3 年股价分位（真实收盘序列统计，失败即明示缺失）=====
    try:
        pct_info = compute_valuation_percentile(ticker_input, years=3)
    except Exception:
        pct_info = {"price_pct": None, "error": "分位计算引擎异常"}

    # ===== V7 战役三：核心指挥中心（4×N 高密度矩阵，1 秒读盘）=====
    section_bar(
        f"⌘ COMMAND CENTER · {info.get('shortName') or mapped_name or ticker_input} ({ticker_input})",
        "全部字段实时抓取；缺失一律标注「数据缺失」，绝不填充假值 · 不构成投资建议",
    )
    try:
        render_command_center(
            info.get('shortName') or ticker_input, ticker_input, info,
            all_data.get('hist_1y'), pct_info, adv_metrics,
        )
    except Exception as e:
        st.warning(f"⚠️ 仪表盘渲染降级（数据源字段缺失）：{type(e).__name__}: {e}")

    st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

    st.markdown("### 📊 标的综合摘要")
    # V9 P1/P2：三栏布局 [雷达图 | 五维文字诊断 | 分析师评级]，消除右侧空白
    exec_c1, exec_c2, exec_c3 = st.columns([1.2, 1, 1.2], vertical_alignment="top")

    if True:

            # ===== 提前获取股票 Profile（真实机构持仓数据，无编造） =====
            st_prof = get_stock_profile(ticker_input, info, mapped_name, all_data.get('institutional_holders'))
            s_title_name = st_prof['display_name']

            targets = all_data.get('analyst_targets', {})
            targets = targets if isinstance(targets, dict) else {}
            mean_p = targets.get("mean") if isinstance(targets.get("mean"), (int, float)) else None
            high_p = targets.get("high") if isinstance(targets.get("high"), (int, float)) else None
            low_p = targets.get("low") if isinstance(targets.get("low"), (int, float)) else None
            if mean_p is None or high_p is None or low_p is None:
                target_range_str = "暂无数据"
            else:
                target_range_str = f"{fmt_price_val(low_p, currency)} ~ {fmt_price_val(high_p, currency)}"

            # ===== 差异化功能2：五维雷达图评分计算（仅计算一次，全站只渲染一次，避免重复图表） =====
            radar_scores = {'估值': 50, '成长': 50, '动能': 50, '盈利': 50, '财务健康': 50}
            try:
                pe = info.get('trailingPE', 0)
                if pe and pe > 0: radar_scores['估值'] = max(10, min(100, 100 - (pe - 10) * 1.5))
                rev_g = info.get('revenueGrowth', 0)
                if rev_g: radar_scores['成长'] = max(10, min(100, 50 + rev_g * 100))
                recent_close = all_data['hist_1y']['Close'].iloc[-1] if not all_data['hist_1y'].empty else 0
                pct_1y = ((recent_close - all_data['hist_1y']['Close'].iloc[0]) / all_data['hist_1y']['Close'].iloc[0]) * 100 if not all_data['hist_1y'].empty else 0
                radar_scores['动能'] = max(10, min(100, 50 + pct_1y))
                roe = info.get('returnOnEquity', 0)
                if roe: radar_scores['盈利'] = max(10, min(100, 30 + roe * 200))
                debt = info.get('debtToEquity', 0)
                if debt: radar_scores['财务健康'] = max(10, min(100, 100 - debt / 2))
            except Exception:
                pass

            with exec_c1:
                df_radar = pd.DataFrame(dict(r=list(radar_scores.values()), theta=list(radar_scores.keys())))
                fig_radar = px.line_polar(df_radar, r='r', theta='theta', line_close=True, template="plotly_dark")
                fig_radar.update_traces(fill='toself', line_color='#00F2FE', fillcolor='rgba(0, 242, 254, 0.15)')
                fig_radar.update_layout(
                    polar=dict(
                        radialaxis=dict(visible=False, range=[0, 100]),
                        angularaxis=dict(color='#F0F4F8', gridcolor='rgba(255,255,255,0.1)'),
                        bgcolor='rgba(0,0,0,0)'
                    ),
                    margin=dict(l=50, r=50, t=40, b=40),
                    height=420,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig_radar, width="stretch", config={'displayModeBar': False})
                st.caption("📌 五维评分基于真实财务数据的固定映射公式归一化到0-100，客观指标可视化，不代表投资建议。")

            # V12：改用 st.container(border=True) 真正包裹内容。旧版用两次独立的
            # st.markdown 分别输出 <div> 与 </div>，Streamlit 会把每次调用渲染成
            # 各自独立的兄弟节点，浏览器随即把未闭合的 <div> 自动闭合，结果是
            # 渲染出两个高 37px 的空卡片，而正文内容全部落在卡片外面。
            with exec_c2, st.container(border=True):
                st.markdown("#### 🎯 标的五维画像量化诊断")
                st.markdown('<span class="badge-neutral">基于真实财务与行情指标映射的五维归一化解构</span>', unsafe_allow_html=True)
                st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)

                val_score = radar_scores.get('估值', 50)
                gro_score = radar_scores.get('成长', 50)
                mom_score = radar_scores.get('动能', 50)
                pro_score = radar_scores.get('盈利', 50)
                hea_score = radar_scores.get('财务健康', 50)

                val_status = "估值偏高" if val_score < 40 else ("估值合理" if val_score <= 70 else "估值吸引力高")
                gro_status = "成长放缓" if gro_score < 40 else ("稳健成长" if gro_score <= 70 else "强劲高增")
                mom_status = "动能较弱" if mom_score < 40 else ("趋势平稳" if mom_score <= 70 else "强劲上行")
                pro_status = "盈利承压" if pro_score < 40 else ("盈利良好" if pro_score <= 70 else "卓越盈利")
                hea_status = "财务偏紧" if hea_score < 40 else ("财务稳健" if hea_score <= 70 else "极佳杠杆")

                st.markdown(f"""
                * 🏷️ **估值维度**: **{val_score:.0f} / 100** — `{val_status}` <br><span style="font-size:0.8rem; color:#94A3B8;">反映市盈率/市净率相对历史与同业分位数水平</span>
                * 🚀 **成长维度**: **{gro_score:.0f} / 100** — `{gro_status}` <br><span style="font-size:0.8rem; color:#94A3B8;">反映营收与净利润同比增长动能</span>
                * ⚡ **动能维度**: **{mom_score:.0f} / 100** — `{mom_status}` <br><span style="font-size:0.8rem; color:#94A3B8;">反映近 1 年价格趋势与市场相对强弱</span>
                * 💎 **盈利维度**: **{pro_score:.0f} / 100** — `{pro_status}` <br><span style="font-size:0.8rem; color:#94A3B8;">反映 ROE 净资产收益率与毛利水平</span>
                * 🛡️ **健康维度**: **{hea_score:.0f} / 100** — `{hea_status}` <br><span style="font-size:0.8rem; color:#94A3B8;">反映资产负债率与现金流偿债安全边际</span>
                """, unsafe_allow_html=True)

                st.markdown("---")
                avg_score = sum(radar_scores.values()) / 5.0
                st.markdown(f"💡 **五维综合健康指数**: <span style='font-size:1.15rem; font-weight:bold; color:#00F2FE;'>{avg_score:.1f} / 100</span>", unsafe_allow_html=True)

            # ===== V9 P1/P2 右栏：第三方分析师评级分布（原 Tab1 底部独立行，上移填补空白） =====
            with exec_c3, st.container(border=True):
                st.markdown("#### 📊 第三方分析师评级分布")
                st.markdown('<span class="badge-neutral">yfinance 历史评级记录 · 不构成投资建议</span>', unsafe_allow_html=True)
                st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)

                recs_df_top = all_data.get('recommendations')
                # V10 P1：饼图与文字说明 [1,1] 对半均分，垂直居中
                pie_l, pie_r = st.columns([1, 1], vertical_alignment="center")
                with pie_l:
                    if recs_df_top is not None and not recs_df_top.empty:
                        try:
                            latest_r = recs_df_top.iloc[0]
                            vals = [
                                int(latest_r.get('strongBuy', 0) or 0),
                                int(latest_r.get('buy', 0) or 0),
                                int(latest_r.get('hold', 0) or 0),
                                int(latest_r.get('sell', 0) or 0),
                                int(latest_r.get('strongSell', 0) or 0)
                            ]
                            labels = ['强烈买入', '买入', '持有', '卖出', '强烈卖出']
                            # V10：跟随全局涨跌语义色（默认 A 股红涨绿跌）
                            colors = [C_UP, C_UP_DIM, '#FBBF24', C_DOWN_DIM, C_DOWN]
                            df_pie = pd.DataFrame({'Label': labels, 'Value': vals})
                            df_pie = df_pie[df_pie['Value'] > 0]
                            total_analysts = int(df_pie['Value'].sum()) if not df_pie.empty else 0

                            if not df_pie.empty:
                                # V10 P1：hole 提至 0.65，圆环更通透有呼吸感
                                fig_donut = px.pie(df_pie, values='Value', names='Label', hole=0.68,
                                                   color='Label', color_discrete_map=dict(zip(labels, colors)))
                                fig_donut.update_layout(
                                    height=240, margin=dict(l=10, r=10, t=15, b=35),
                                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                    showlegend=True,
                                    legend=dict(orientation="h", yanchor="top", y=-0.12,
                                                xanchor="center", x=0.5, font=dict(size=10)),
                                    annotations=[dict(text=f'{total_analysts} 位<br>分析师', x=0.5, y=0.5,
                                                      font_size=12, showarrow=False,
                                                      font=dict(color='#D1D4DC'))]
                                )
                                fig_donut.update_traces(textinfo='percent', textposition='outside', textfont_size=10,
                                                        hoverinfo='label+value')
                                st.plotly_chart(fig_donut, width="stretch", config={'displayModeBar': False})
                            else:
                                st.info("暂无有效评级人数")
                        except Exception:
                            st.info("评级数据解析异常")
                    else:
                        st.info("暂无评级数据")

                with pie_r:
                    st.markdown(
                        f"""
**第三方目标价历史区间**
- 🎯 最高: {fmt_price_val(high_p, currency) if high_p else 'N/A'}
- ⚖️ 均值: {fmt_price_val(mean_p, currency) if mean_p else 'N/A'}
- 🛡️ 最低: {fmt_price_val(low_p, currency) if low_p else 'N/A'}

<div style="font-size:0.75rem; opacity:0.6; margin-top:0.6rem;">数据来源：yfinance 分析师一致预期（历史事实记录）<br>不构成投资建议</div>
""", unsafe_allow_html=True)

            st.markdown('<div class="spacer-md"></div>', unsafe_allow_html=True)

            tab1, tab2, tab3, tab4 = st.tabs(["🎯 反共识诊断", "📊 财报与估值穿透", "🏛️ 机构与资金追踪", "📰 AI 中性舆情解构"])

            # =====================================================================
            # Tab 1：反共识诊断 —— 分析师评级分布、产业链图谱、主营业务构成、缠论技术摘要
            # =====================================================================
            with tab1:
                st.markdown(f'<div style="text-align:center; font-size:1.2rem; font-weight:800; margin-bottom:1.0rem;">📌 【{s_title_name}】 客观数据总览</div>', unsafe_allow_html=True)
                st.caption("⚠️ 以下均为第三方数据源（yfinance/akshare）的客观历史记录，不构成、也不包含本站任何投资建议、评级、目标价推荐或仓位建议。")

                # V9 P1/P2：分析师评级分布已上移至 Executive Summary 右栏（exec_c3），
                # 此处不再重复渲染，Tab1 直接进入产业链图谱与主营业务构成。
                recs_df_top = all_data.get('recommendations')
                # （评级圆环图已上移至 Executive Summary 右栏）

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")
                st.markdown(build_chain_html(info, ticker_input), unsafe_allow_html=True)

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")
                st.markdown(f"### 🏢 {s_title_name} 主营业务构成", unsafe_allow_html=True)
                st.caption("数据来源标注见下方明细")
                main_comp = all_data.get('main_composition')
                if main_comp is not None and not main_comp.empty:
                    # ==== A 股：akshare 主营构成数据 ====
                    try:
                        c_pie1, c_pie2 = st.columns(2)
                        with c_pie1:
                            df_prod = main_comp[main_comp['分类类型'].str.contains('产品', na=False)] if '分类类型' in main_comp.columns else pd.DataFrame()
                            if not df_prod.empty and '主营构成' in df_prod.columns and '收入比例' in df_prod.columns:
                                df_prod['收入比例数值'] = df_prod['收入比例'].astype(str).str.replace('%', '', regex=False).astype(float)
                                # V12：hole 0.4→0.68 且标签外置带指引线。中文主营名称较长，
                                # 原先 textposition='inside' 在窄扇区里会把文字压成一团。
                                fig_p1 = px.pie(df_prod, values='收入比例数值', names='主营构成', hole=0.68, title="按产品分类营收占比", color_discrete_sequence=px.colors.sequential.Teal)
                                fig_p1.update_traces(textinfo='label+percent', textposition='outside',
                                                     textfont=dict(size=10), automargin=True, showlegend=False)
                                fig_p1.update_layout(margin=dict(t=40, b=30, l=40, r=40), height=330, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', uniformtext=dict(minsize=9, mode='hide'))
                                st.plotly_chart(fig_p1, width="stretch")
                            else:
                                st.info("暂无按产品分类数据")

                        with c_pie2:
                            df_reg = main_comp[main_comp['分类类型'].str.contains('地区', na=False)] if '分类类型' in main_comp.columns else pd.DataFrame()
                            if not df_reg.empty and '主营构成' in df_reg.columns and '收入比例' in df_reg.columns:
                                df_reg['收入比例数值'] = df_reg['收入比例'].astype(str).str.replace('%', '', regex=False).astype(float)
                                fig_p2 = px.pie(df_reg, values='收入比例数值', names='主营构成', hole=0.68, title="按地区分类营收占比", color_discrete_sequence=px.colors.sequential.Purp)
                                fig_p2.update_traces(textinfo='label+percent', textposition='outside',
                                                     textfont=dict(size=10), automargin=True, showlegend=False)
                                fig_p2.update_layout(margin=dict(t=40, b=30, l=40, r=40), height=330, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', uniformtext=dict(minsize=9, mode='hide'))
                                st.plotly_chart(fig_p2, width="stretch")
                            else:
                                st.info("暂无按地区分类数据")

                        with st.expander("查看原始数据明细"):
                            comp_cols = [c for c in main_comp.columns if c in ['报告期', '分类类型', '主营构成', '主营收入', '收入比例', '主营利润', '利润比例', '主营成本', '成本比例']]
                            st.dataframe(main_comp[comp_cols] if comp_cols else main_comp, width="stretch")
                            st.caption("📌 数据来源：akshare stock_zygc_em（主营构成）。")
                    except Exception:
                        st.info("⚠️ 主营构成数据格式解析异常，暂不展示，避免误导。")
                else:
                    # ==== 美股/港股：从 yfinance 季度利润表 + 业务概要提取 ====
                    us_biz_shown = False
                    try:
                        # 1. 尝试从季度利润表获取收入/利润关键行
                        qis = all_data.get('quarterly_income_stmt')
                        ais = all_data.get('income_stmt')
                        fin_stmt = qis if (qis is not None and not qis.empty) else ais
                        if fin_stmt is not None and not fin_stmt.empty:
                            # 提取关键财务行（收入/成本/毛利/运营利润/净利）
                            key_rows = ['Total Revenue', 'Cost Of Revenue', 'Gross Profit',
                                        'Operating Income', 'Operating Expense', 'Net Income',
                                        'EBITDA', 'Research And Development']
                            available_rows = [r for r in key_rows if r in fin_stmt.index]
                            if available_rows:
                                display_df = fin_stmt.loc[available_rows].head(4)  # 最近4期
                                # 格式化列名为日期字符串
                                display_df.columns = [str(c.date()) if hasattr(c, 'date') else str(c) for c in display_df.columns]
                                # 格式化数值为亿/万
                                def fmt_fin_num(v):
                                    if pd.isna(v): return 'N/A'
                                    v = float(v)
                                    if abs(v) >= 1e9: return f"{v/1e9:.2f}B"
                                    if abs(v) >= 1e6: return f"{v/1e6:.1f}M"
                                    return f"{v:,.0f}"
                                display_formatted = display_df.applymap(fmt_fin_num)
                                # 行名中英文映射
                                row_name_map = {
                                    'Total Revenue': '📊 总营收 (Revenue)',
                                    'Cost Of Revenue': '💰 营业成本 (COGS)',
                                    'Gross Profit': '📈 毛利 (Gross Profit)',
                                    'Operating Income': '🏢 营业利润 (Operating Income)',
                                    'Operating Expense': '📋 营业费用 (OpEx)',
                                    'Net Income': '💵 净利润 (Net Income)',
                                    'EBITDA': '📐 EBITDA',
                                    'Research And Development': '🔬 研发支出 (R&D)',
                                }
                                display_formatted.index = [row_name_map.get(r, r) for r in display_formatted.index]
                                is_quarterly = qis is not None and not qis.empty
                                period_label = '季度' if is_quarterly else '年度'
                                st.markdown(f"#### 📊 {s_title_name} 近期{period_label}利润表关键指标 <span style='font-size:0.75rem; opacity:0.6;'>来源: yfinance</span>", unsafe_allow_html=True)
                                st.dataframe(display_formatted, width="stretch")

                                # 如果有多期总营收，绘制营收趋势柱状图
                                if 'Total Revenue' in fin_stmt.index:
                                    rev_series = fin_stmt.loc['Total Revenue'].dropna().head(8)
                                    if len(rev_series) >= 2:
                                        rev_df = pd.DataFrame({
                                            'Period': [str(c.date()) if hasattr(c, 'date') else str(c) for c in rev_series.index],
                                            'Revenue': [float(v)/1e9 for v in rev_series.values]
                                        })
                                        rev_df = rev_df.iloc[::-1]  # 按时间正序
                                        fig_rev = px.bar(rev_df, x='Period', y='Revenue',
                                                        title=f"{s_title_name} {period_label}营收趋势 (单位: 十亿 {info.get('currency', 'USD')})",
                                                        color_discrete_sequence=['#00b865'])
                                        fig_rev.update_layout(
                                            height=280, template='plotly_dark',
                                            margin=dict(l=10, r=10, t=40, b=10),
                                            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                            xaxis_title='', yaxis_title='Revenue (B)'
                                        )
                                        st.plotly_chart(fig_rev, width="stretch")
                                us_biz_shown = True
                    except Exception:
                        pass

                    # 2. 展示公司业务概要（longBusinessSummary）
                    try:
                        biz_summary = info.get('longBusinessSummary', '')
                        if biz_summary and len(biz_summary) > 50:
                            st.markdown(f"#### 📝 {s_title_name} 业务概要 <span style='font-size:0.75rem; opacity:0.6;'>来源: yfinance</span>", unsafe_allow_html=True)
                            st.markdown(f'<div style="background:rgba(20,24,33,0.5); padding:15px; border-radius:10px; border:1px solid rgba(255,255,255,0.05); font-size:0.88rem; line-height:1.7; color:#e2e8f0;">{biz_summary}</div>', unsafe_allow_html=True)
                            us_biz_shown = True
                    except Exception:
                        pass

                    # 3. 展示行业/板块分类
                    try:
                        sector_val = info.get('sector', '')
                        industry_val = info.get('industry', '')
                        employees = info.get('fullTimeEmployees', '')
                        website = info.get('website', '')
                        if sector_val or industry_val:
                            meta_items = []
                            if sector_val: meta_items.append(f"<b>板块:</b> {sector_val}")
                            if industry_val: meta_items.append(f"<b>细分行业:</b> {industry_val}")
                            if employees: meta_items.append(f"<b>全职员工:</b> {employees:,}" if isinstance(employees, int) else f"<b>全职员工:</b> {employees}")
                            if website: meta_items.append(f"<b>官网:</b> <a href='{website}' style='color:#4B9FFF;'>{website}</a>")
                            meta_html = " &nbsp;|&nbsp; ".join(meta_items)
                            st.markdown(f'<div style="background:rgba(0,242,254,0.05); padding:10px 15px; border-radius:8px; border:1px solid rgba(0,242,254,0.15); font-size:0.85rem; color:#94a3b8; margin-top:0.8rem;">{meta_html}</div>', unsafe_allow_html=True)
                            us_biz_shown = True
                    except Exception:
                        pass

                    if not us_biz_shown:
                        st.info(f"⚠️ 暂无 {s_title_name} 的业务构成数据（可能是 yfinance 接口限流），请稍后重试。")

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")
                c4_a, c4_b = st.columns([0.95, 1.05])
                with c4_a:
                    st.markdown("### 📈 缠论技术面数据摘要", unsafe_allow_html=True)
                    st.caption("⚠️ 简化版分型/中枢识别 + RSI + BOLL，非买卖点建议")
                    chanlun_text_ui = analyze_kline_and_chanlun(all_data['hist_1y']) if all_data and all_data.get('hist_1y') is not None else "暂无K线数据"
                    st.markdown(chanlun_text_ui, unsafe_allow_html=True)
                    st.caption("📌 以上数据均基于真实K线计算得出，非AI编造。")
                with c4_b:
                    if not all_data['hist_1y'].empty:
                        # V7 战役三：TradingView 级专业图 —— 多均线(含 MA120/MA250 牛熊分界)
                        # + 成交量副图 + MACD + RSI 四轨同屏
                        kline_fig = build_pro_kline_chart(all_data['hist_1y'], ticker_input, height=660)
                        st.plotly_chart(kline_fig, width="stretch", config={'displayModeBar': False})
                        st.caption("📌 MA120/MA250 为长周期牛熊分界参考线，均为真实收盘价滚动均值，非买卖信号。")



            with tab2:
                st.markdown(f'<div style="text-align:center; font-size:1.2rem; font-weight:800; margin-bottom:0.6rem;">📊 【{s_title_name}】 财报与估值穿透</div>', unsafe_allow_html=True)
                st.caption("⚠️ 以下均为第三方数据源的客观历史记录与统计计算，不构成估值结论或投资建议。")

                st.markdown("#### 📐 股价历史区间分位（近3年，客观统计）")
                hist_long = fetch_price_history_long(ticker_input, years=3)
                if hist_long is not None and len(hist_long) >= 30:
                    closes = hist_long['Close']
                    cur_c = closes.iloc[-1]
                    pct_rank = float((closes < cur_c).mean() * 100)
                    st.markdown(f"""
                    <div class="percentile-track"><div class="percentile-marker" style="left:{pct_rank:.1f}%;"></div></div>
                    <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:#94A3B8;">
                        <span>近3年最低</span><span>近3年最高</span>
                    </div>
                    <div style="text-align:center; margin-top:0.6rem; font-size:0.95rem;">
                        当前价格处于近3年股价区间的第 <b style="color:#00F2FE; font-size:1.1rem;">{pct_rank:.0f}</b> 百分位
                    </div>
                    """, unsafe_allow_html=True)
                    st.caption("⚠️ 这是「股价」在其自身近3年历史区间中的相对位置，不是「PE估值」的历史分位。严谨的PE历史分位需要完整历史EPS序列，免费数据源无法可靠获取，为避免用假精度误导用户，本站不提供编造的PE分位数字。")
                else:
                    st.info("暂无足够的近3年历史价格数据，无法计算区间分位。")

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("#### 🧮 核心财务 KPI")

                def kpi_card(label, value):
                    return f'<div class="kpi-neon-card"><div class="kpi-neon-label">{label}</div><div class="kpi-neon-value">{value}</div></div>'

                eps_ttm = info.get('trailingEps')
                rev_growth_val = info.get('revenueGrowth')
                net_margin_kpi = info.get('profitMargins') or info.get('netMargins')
                roe_kpi = info.get('returnOnEquity')

                k1, k2 = st.columns(2)
                with k1:
                    st.markdown(kpi_card("EPS (TTM)", f"{eps_ttm:.2f}" if isinstance(eps_ttm, (int, float)) else "N/A"), unsafe_allow_html=True)
                with k2:
                    st.markdown(kpi_card("营收增速", f"{rev_growth_val*100:.2f}%" if isinstance(rev_growth_val, (int, float)) else "N/A"), unsafe_allow_html=True)
                st.markdown('<div class="spacer-sm"></div>', unsafe_allow_html=True)
                k3, k4 = st.columns(2)
                with k3:
                    st.markdown(kpi_card("净利率 (TTM)", f"{net_margin_kpi*100:.2f}%" if isinstance(net_margin_kpi, (int, float)) else "N/A"), unsafe_allow_html=True)
                with k4:
                    st.markdown(kpi_card("ROE", f"{roe_kpi*100:.2f}%" if isinstance(roe_kpi, (int, float)) else "N/A"), unsafe_allow_html=True)

                # =====================================================================
                # V8 战役三：投行级现金流扩军 + 盈利惊喜历史，横向双列填满右侧空白
                # =====================================================================
                st.markdown('<div class="spacer-sm"></div>', unsafe_allow_html=True)
                section_bar("💸 现金流与资本开支穿透 · 盈利惊喜历史",
                            "CAPEX / FCF 取自现金流量表真实科目；EPS Beat/Miss 取自 yfinance 财报日历")
                try:
                    extra_fin = compute_capex_fcf(all_data)
                except Exception:
                    extra_fin = {}
                try:
                    eps_rows = compute_earnings_surprises(all_data, n=4)
                except Exception:
                    eps_rows = []

                def _m8(v):
                    return f"{v/1e8:,.2f}亿" if isinstance(v, (int, float)) else "数据缺失"

                # V10.3 P5：改为顶部对齐——卡片与图表上沿齐平（居中会让卡片悬在半空显得错位）
                ex_c1, ex_c2 = st.columns([1, 1.2], vertical_alignment="top")
                with ex_c1:
                    _capex = extra_fin.get('capex')
                    _fcf = extra_fin.get('fcf')
                    _ocf2 = extra_fin.get('ocf')
                    _c2o = extra_fin.get('capex_to_ocf')
                    render_kpi_grid([
                        dict(label="经营性现金流 (TTM)", value=_m8(_ocf2),
                             sub="现金流量表经营活动净额",
                             value_direction=("up" if (_ocf2 or 0) > 0 else "down") if _ocf2 is not None else None),
                        dict(label="资本支出 CAPEX", value=_m8(_capex),
                             sub="购建固定/无形资产等现金流出"),
                        dict(label="自由现金流 FCF", value=_m8(_fcf),
                             sub=extra_fin.get('fcf_note') or "报表未披露且无法推算",
                             value_direction=("up" if (_fcf or 0) > 0 else "down") if _fcf is not None else None),
                        dict(label="CAPEX / 经营现金流", value=(f"{_c2o*100:.1f}%" if _c2o is not None else "数据缺失"),
                             sub=("重资产扩张期" if (_c2o or 0) >= 0.5 else "现金流可覆盖资本开支") if _c2o is not None else "口径数据缺失",
                             direction=("down" if (_c2o or 0) >= 0.5 else "up") if _c2o is not None else "neutral"),
                    ], cols=2)
                with ex_c2:
                    _is_usd = bool(all_data.get('info', {}).get('currency') in ["USD", "$"])
                    fig_eps = build_eps_surprise_chart(eps_rows, height=300, is_usd=_is_usd)
                    if fig_eps is not None:
                        st.plotly_chart(fig_eps, width="stretch", config={'displayModeBar': False})
                        tags = []
                        for r in eps_rows:
                            if r.get('beat') is None:
                                lbl, col = "无预期基准", C_NEUTRAL
                            elif r['beat']:
                                lbl, col = "BEAT 超预期", C_UP
                            else:
                                lbl, col = "MISS 不及预期", C_DOWN
                            sp = f"{r['surprise_pct']:+.1f}%" if r.get('surprise_pct') is not None else "—"
                            tags.append(
                                f'<span style="display:inline-block; margin:2px 5px 2px 0; padding:2px 8px;'
                                f' border:1px solid {col}; border-radius:5px; font-size:0.72rem;'
                                f' color:{col}; font-weight:700;">{r["period"]} · {lbl} {sp}</span>')
                        st.html("<div>" + "".join(tags) + "</div>")
                    else:
                        st.warning("⚠️ yfinance 财报日历未返回 EPS 预期/实际数据（接口限流或该标的无覆盖），"
                                   "盈利惊喜历史真实数据缺失，不做任何填充。")

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")

                def fnum(v, pct=False, money=False):
                    if v is None or (isinstance(v, float) and np.isnan(v)):
                        return "N/A"
                    try:
                        if pct:
                            return f"{float(v)*100:.2f}%"
                        if money:
                            v = float(v)
                            return f"{v/1e8:.2f}亿" if abs(v) >= 1e8 else f"{v:,.0f}"
                        return str(v)
                    except Exception:
                        return "N/A"

                qf = all_data.get('quarterly_financials')
                rev_now = rev_prev = np_now = np_prev = None
                report_quarter = "N/A"
                if qf is not None and not qf.empty:
                    try:
                        cols = list(qf.columns)
                        report_quarter = str(cols[0].date()) if hasattr(cols[0], 'date') else str(cols[0])
                        if 'Total Revenue' in qf.index:
                            rev_now = qf.loc['Total Revenue'].iloc[0]
                            if len(cols) > 1: rev_prev = qf.loc['Total Revenue'].iloc[1]
                        for key in ['Net Income', 'Net Income Common Stockholders']:
                            if key in qf.index:
                                np_now = qf.loc[key].iloc[0]
                                if len(cols) > 1: np_prev = qf.loc[key].iloc[1]
                                break
                    except Exception:
                        pass

                gross_margin = info.get('grossMargins')
                net_margin = info.get('profitMargins') or info.get('netMargins')
                roe = info.get('returnOnEquity')
                debt_ratio = info.get('debtToEquity')
                fcf = info.get('freeCashflow')

                rev_trend = "N/A"
                if isinstance(rev_now, (int, float)) and isinstance(rev_prev, (int, float)) and rev_prev != 0:
                    rev_trend = f"{(rev_now-rev_prev)/abs(rev_prev)*100:+.1f}% QoQ"
                np_trend = "N/A"
                if isinstance(np_now, (int, float)) and isinstance(np_prev, (int, float)) and np_prev != 0:
                    np_trend = f"{(np_now-np_prev)/abs(np_prev)*100:+.1f}% QoQ"

                st.markdown(f"#### 财务核心数据 <span style='font-size:0.75rem; opacity:0.6;'>数据来源: yfinance | 最新季度: {report_quarter}</span>", unsafe_allow_html=True)
                
                # P7 扩展指标解析
                rd_now = rd_prev = None
                if qf is not None and not qf.empty and 'Research And Development' in qf.index:
                    rd_now = qf.loc['Research And Development'].iloc[0]
                    if len(qf.columns) > 1: rd_prev = qf.loc['Research And Development'].iloc[1]
                elif qf is not None and not qf.empty and 'ResearchAndDevelopment' in qf.index:
                    rd_now = qf.loc['ResearchAndDevelopment'].iloc[0]
                    if len(qf.columns) > 1: rd_prev = qf.loc['ResearchAndDevelopment'].iloc[1]

                op_inc_now = op_inc_prev = None
                if qf is not None and not qf.empty and 'Operating Income' in qf.index:
                    op_inc_now = qf.loc['Operating Income'].iloc[0]
                    if len(qf.columns) > 1: op_inc_prev = qf.loc['Operating Income'].iloc[1]
                elif qf is not None and not qf.empty and 'OperatingIncome' in qf.index:
                    op_inc_now = qf.loc['OperatingIncome'].iloc[0]
                    if len(qf.columns) > 1: op_inc_prev = qf.loc['OperatingIncome'].iloc[1]

                qcf = all_data.get('quarterly_cashflow')
                op_cf_now = op_cf_prev = None
                if qcf is not None and not qcf.empty and 'Operating Cash Flow' in qcf.index:
                    op_cf_now = qcf.loc['Operating Cash Flow'].iloc[0]
                    if len(qcf.columns) > 1: op_cf_prev = qcf.loc['Operating Cash Flow'].iloc[1]
                elif qcf is not None and not qcf.empty and 'OperatingCashFlow' in qcf.index:
                    op_cf_now = qcf.loc['OperatingCashFlow'].iloc[0]
                    if len(qcf.columns) > 1: op_cf_prev = qcf.loc['OperatingCashFlow'].iloc[1]

                qbs = all_data.get('quarterly_balance_sheet')
                debt_to_assets = None
                if qbs is not None and not qbs.empty:
                    try:
                        total_assets = None
                        for k in ['Total Assets', 'TotalAssets']:
                            if k in qbs.index:
                                total_assets = qbs.loc[k].iloc[0]
                                break
                        total_debt = None
                        for k in ['Total Debt', 'TotalDebt', 'Total Liabilities Net Minor Interest', 'TotalLiabilitiesNetMinorInterest']:
                            if k in qbs.index:
                                total_debt = qbs.loc[k].iloc[0]
                                break
                        if total_assets and total_debt:
                            debt_to_assets = total_debt / total_assets
                    except Exception:
                        pass

                def fmt_trend(now_val, prev_val):
                    if isinstance(now_val, (int, float)) and isinstance(prev_val, (int, float)) and prev_val != 0:
                        chg = (now_val - prev_val) / abs(prev_val) * 100
                        cls = "trend-up" if chg >= 0 else "trend-down"
                        return f'<span class="{cls}">{chg:+.1f}% QoQ</span>'
                    return '<span class="trend-neutral">—</span>'

                def make_card(label, value_str, trend_html):
                    # V9 P4：HTML 必须顶格（无前导缩进）——Markdown 会把 >=4 空格缩进的
                    # 行当代码块渲染，导致 <div class="fin-card"> 以纯文本泄露到页面上。
                    return (
                        '<div class="fin-card">'
                        f'<div class="fin-label">{label}</div>'
                        f'<div class="fin-value">{value_str}</div>'
                        f'<div class="fin-trend">{trend_html}</div>'
                        '</div>'
                    )

                cards_html = (
                    '<div class="financial-grid">'
                    + "".join([
                        make_card("📊 营业收入 (Revenue)", fnum(rev_now, money=True), fmt_trend(rev_now, rev_prev)),
                        make_card("💵 净利润 (Net Income)", fnum(np_now, money=True), fmt_trend(np_now, np_prev)),
                        make_card("🏢 营业利润 (Operating Income)", fnum(op_inc_now, money=True), fmt_trend(op_inc_now, op_inc_prev)),
                        make_card("🔬 研发投入 (R&D)", fnum(rd_now, money=True), fmt_trend(rd_now, rd_prev)),
                        make_card("💸 经营性现金流 (OCF)", fnum(op_cf_now, money=True), fmt_trend(op_cf_now, op_cf_prev)),
                        make_card("🌊 自由现金流 (FCF)", fnum(fcf, money=True), '<span class="trend-neutral">—</span>'),
                        make_card("📈 毛利率 (Gross Margin)", fnum(gross_margin, pct=True), '<span class="trend-neutral">—</span>'),
                        make_card("📊 净利率 (Net Margin)", fnum(net_margin, pct=True), '<span class="trend-neutral">—</span>'),
                        make_card("🧬 ROE (净资产收益率)", fnum(roe, pct=True), '<span class="trend-neutral">—</span>'),
                        make_card("🛡️ 资产负债率 (Debt/Assets)", fnum(debt_to_assets, pct=True), '<span class="trend-neutral">—</span>'),
                    ])
                    + '</div>'
                )
                st.markdown(cards_html, unsafe_allow_html=True)
                st.caption("📌 双向/客观财报指标展示系统，N/A 表示接口未返回对应披露项。")

                # =====================================================================
                # V7 战役二：盈利质量 / 杜邦 / 研发 / PEG 深度穿透（全部实时计算）
                # =====================================================================
                st.markdown("---")
                section_bar("🔬 深度基本面穿透 · 盈利质量 / 杜邦引擎 / 前瞻性",
                            f"口径：{adv_metrics.get('period_note') or '数据缺失'} · 来源 yfinance 报表原始科目实时计算")

                def _pct(v):
                    return f"{v*100:.2f}%" if isinstance(v, (int, float)) else "数据缺失"

                def _x(v, digits=2):
                    return f"{v:.{digits}f}x" if isinstance(v, (int, float)) else "数据缺失"

                def _money_cn(v):
                    if not isinstance(v, (int, float)):
                        return "数据缺失"
                    return f"{v/1e8:,.2f}亿" if abs(v) >= 1e8 else f"{v:,.0f}"

                ocf_r = adv_metrics.get('ocf_to_ni')
                peg_v = adv_metrics.get('peg')
                rd_r = adv_metrics.get('rd_to_revenue')
                gap_v = (adv_metrics.get('ocf') - adv_metrics.get('net_income')) \
                    if (adv_metrics.get('ocf') is not None and adv_metrics.get('net_income') is not None) else None

                render_kpi_grid([
                    dict(label="EBITDA (TTM)", value=_money_cn(adv_metrics.get('ebitda')),
                         sub=adv_metrics.get('ebitda_note') or "报表未披露且无法由营业利润+折旧摊销推算"),
                    dict(label="EBITDA 利润率", value=_pct(adv_metrics.get('ebitda_margin')),
                         sub="EBITDA / 营业总收入", value_direction="accent" if adv_metrics.get('ebitda_margin') else None),
                    dict(label="经营性现金流 (OCF)", value=_money_cn(adv_metrics.get('ocf')),
                         sub="现金流量表经营活动净额"),
                    dict(label="OCF / 净利润", value=_x(ocf_r),
                         sub=adv_metrics.get('earnings_quality_label') or "现金流或净利润缺失",
                         direction=("up" if (ocf_r or 0) >= 1 else "down") if ocf_r else "neutral",
                         value_direction=("up" if (ocf_r or 0) >= 1 else "down") if ocf_r else None),
                    dict(label="现金流-利润差额", value=_money_cn(gap_v),
                         sub=("现金流优于账面利润" if (gap_v or 0) >= 0 else "现金流弱于账面利润") if gap_v is not None else "数据缺失",
                         direction=("up" if (gap_v or 0) >= 0 else "down") if gap_v is not None else "neutral"),
                    dict(label="净利率 (杜邦因子①)", value=_pct(adv_metrics.get('net_margin')),
                         sub="净利润 / 营业总收入"),
                    dict(label="总资产周转率 (因子②)", value=_x(adv_metrics.get('asset_turnover')),
                         sub="营收 / 平均总资产"),
                    dict(label="权益乘数 (因子③)", value=_x(adv_metrics.get('equity_multiplier')),
                         sub="平均总资产 / 股东权益（杠杆）"),
                    dict(label="ROE (杜邦推算)", value=_pct(adv_metrics.get('roe_dupont')),
                         sub=f"报表口径 ROE {_pct(adv_metrics.get('roe_reported'))}",
                         value_direction="accent" if adv_metrics.get('roe_dupont') else None),
                    dict(label="研发投入 (TTM)", value=_money_cn(adv_metrics.get('rd')),
                         sub="利润表 Research And Development"),
                    dict(label="研发费用率", value=_pct(rd_r),
                         sub=("研发强度高" if (rd_r or 0) >= 0.10 else "研发强度中低") if rd_r else "接口未披露研发科目",
                         value_direction="accent" if rd_r else None),
                    dict(label="PEG (PE / 增速)", value=(f"{peg_v:.2f}" if peg_v else "数据缺失"),
                         sub=(adv_metrics.get('peg_source') or "一致预期增速缺失，拒绝用假设增速凑数"),
                         direction=("up" if (peg_v or 99) < 1 else "down") if peg_v else "neutral",
                         value_direction=("up" if (peg_v or 99) < 1 else "down") if peg_v else None),
                ], cols=4)

                if adv_metrics.get('eps_growth_3y'):
                    st.caption(f"📌 PEG 分母使用的前瞻 EPS 一致预期年化增速 = "
                               f"{adv_metrics['eps_growth_3y']*100:.2f}%（{adv_metrics.get('peg_source')}）；"
                               f"PEG 仅为客观倍数计算，不构成估值结论。")
                else:
                    st.warning("⚠️ 未能取得任何真实的前瞻 EPS 一致预期增速（接口限流或该标的无覆盖），"
                               "因此 PEG 明确留空 —— 本站拒绝用假设增速编造 PEG。")

                dp_c1, dp_c2 = st.columns(2)
                with dp_c1:
                    fig_dp = build_dupont_chart(adv_metrics)
                    if fig_dp is not None:
                        st.plotly_chart(fig_dp, width="stretch", config={'displayModeBar': False})
                    else:
                        st.warning("⚠️ 杜邦拆解所需的资产负债表科目缺失（接口未返回总资产/股东权益），真实数据缺失，不做推测填充。")
                with dp_c2:
                    fig_q = build_quality_bridge_chart(adv_metrics)
                    if fig_q is not None:
                        st.plotly_chart(fig_q, width="stretch", config={'displayModeBar': False})
                    else:
                        st.warning("⚠️ 经营性现金流或净利润科目缺失，无法做利润含金量对比，真实数据缺失。")

                # ---------- 同行业估值基准（动态成分股中位数，非写死常量） ----------
                st.markdown("---")
                section_bar("🏭 同行业实时估值基准", "成分股倍数中位数动态拉取 · 无真实同业数据即明示缺失")
                bench = None
                try:
                    bench = fetch_industry_benchmark(
                        ticker_input,
                        industry_key=info.get('industryKey', '') or '',
                        industry_name=info.get('industry', '') or '',
                        is_a_share=bool(all_data.get('is_a_share')),
                        pure_code=all_data.get('pure_code', '') or '',
                    )
                except Exception as e:
                    st.warning(f"⚠️ 同业基准抓取异常：{type(e).__name__}: {e}")
                if bench:
                    cur_pe = sf(info.get('trailingPE')) or sf(info.get('forwardPE'))
                    cur_pb = sf(info.get('priceToBook'))
                    cur_ps = sf(info.get('priceToSalesTrailing12Months'))
                    def _gap_card(name, cur, ref):
                        if cur is None or ref is None:
                            return dict(label=f"{name} 水位差", value="数据缺失",
                                        sub="本标的或同业该口径真实数据缺失")
                        g = (cur - ref) / ref * 100
                        return dict(label=f"{name} 水位差", value=f"{g:+.1f}%",
                                    sub=f"本标的 {cur:.2f}x  /  同业中位 {ref:.2f}x",
                                    direction="down" if g >= 0 else "up",
                                    value_direction="down" if g >= 0 else "up")
                    render_kpi_grid([
                        _gap_card("PE", cur_pe, bench.get('pe')),
                        _gap_card("PB", cur_pb, bench.get('pb')),
                        _gap_card("PS", cur_ps, bench.get('ps')),
                        dict(label="同业样本量", value=f"{bench.get('peer_count', 0)} 家",
                             sub=bench.get('source', '')),
                    ], cols=4)
                    # V8：横向进度条直观呈现【本标的】与【同业中位】的折溢价空间
                    render_gap_bars([
                        ("PE 水位差", cur_pe, bench.get('pe')),
                        ("PB 水位差", cur_pb, bench.get('pb')),
                        ("PS 水位差", cur_ps, bench.get('ps')),
                    ])
                    st.caption("📌 进度条中轴为同业实时中位数；向右(红)代表相对溢价，向左(绿)代表相对折价；"
                               "纯倍数比较，不构成买卖建议。")
                    peers = bench.get('peers')
                    if peers is not None and hasattr(peers, 'empty') and not peers.empty:
                        with st.expander("查看同业成分股原始倍数明细（真实抓取）"):
                            st.dataframe(peers, width="stretch")
                else:
                    st.warning("⚠️ 同行业成分股估值基准真实数据缺失（行业分类未匹配或行情接口限流）。"
                               "本站不使用 PE=20x 这类写死常量兜底，因此此处留空。")

            # =====================================================================
            # Tab 3：机构与资金追踪 —— 十大流通股东持仓（此前误挂在tab1）+ 机构调研记录
            # =====================================================================
            with tab3:
                st.markdown(f"### 🏛️ 【{s_title_name}】 机构持仓与资金追踪 <span style='font-size:0.75rem; opacity:0.6;'>公开披露信息聚合</span>", unsafe_allow_html=True)

                has_inst = bool(st_prof['inst_names'] and st_prof['inst_shares'])
                if has_inst:
                    shares_v = st_prof['inst_shares']
                    fig_inst = go.Figure(go.Bar(
                        x=shares_v, y=st_prof['inst_names'], orientation='h',
                        marker_color=[C_ACCENT if i == 0 else C_NEUTRAL for i in range(len(shares_v))],
                        text=[f"{v}%" for v in shares_v], textposition='outside',
                        textfont=dict(size=11, color=C_TEXT),
                    ))
                    fig_inst.update_layout(
                        height=max(240, 30 * len(shares_v) + 90), template='plotly_dark',
                        margin=dict(l=8, r=70, t=32, b=8),
                        title=dict(text=f"{s_title_name} 前十大股东/机构持股比例 (%)", font=dict(size=12), x=0.01),
                        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
                        xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False,
                    )
                    st.plotly_chart(fig_inst, width="stretch", config={'displayModeBar': False})
                    st.caption(f"📌 数据来源：{st_prof.get('inst_source') or '公开披露接口'}（真实抓取，非编造）。")
                else:
                    st.warning("⚠️ 监管未披露或接口限流，真实数据缺失 —— 该标的的机构/十大股东持仓无法获取。"
                               "本站绝不使用虚构股东名单或占位图表。")
                    if st_prof.get('inst_error'):
                        with st.expander("查看各接口降级尝试的失败明细（便于排查）"):
                            st.code(str(st_prof['inst_error']))

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")
                st.markdown("#### 🔎 机构调研记录")
                if all_data.get('is_a_share'):
                    surveys = {}
                    try:
                        surveys = fetch_institution_surveys(all_data.get('pure_code') or ticker_input[:6], days=120)
                    except Exception as e:
                        surveys = {"df": None, "error": f"{type(e).__name__}: {e}"}
                    df_jgdy = surveys.get('df')
                    if df_jgdy is not None and hasattr(df_jgdy, 'empty') and not df_jgdy.empty:
                        col_date = next((c for c in df_jgdy.columns if '日期' in str(c) or '时间' in str(c)), None)
                        col_org = next((c for c in df_jgdy.columns if '机构' in str(c) or '对象' in str(c) or '接待' in str(c)), None)
                        col_people = next((c for c in df_jgdy.columns if '人员' in str(c) or '调研人' in str(c)), None)
                        df_display = pd.DataFrame()
                        df_display['调研日期'] = df_jgdy[col_date].astype(str) if col_date else df_jgdy.iloc[:, 0].astype(str)
                        if col_org:
                            df_display['调研机构/接待对象'] = df_jgdy[col_org].astype(str)
                        if col_people:
                            df_display['参与人员'] = df_jgdy[col_people].astype(str)
                        st.dataframe(df_display.head(50), width="stretch")
                        st.caption(f"📌 数据来源：{surveys.get('source')}")
                    else:
                        st.warning("⚠️ 监管未披露或接口限流，真实数据缺失 —— 未取得该标的近 120 日机构调研记录。")
                        if surveys.get('error'):
                            with st.expander("查看接口降级尝试明细"):
                                st.code(str(surveys['error']))
                else:
                    st.info("ℹ️ 机构调研记录为 A 股监管强制披露类别，港股/美股无完全对应开源接口，此项不适用于当前标的。")
                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)

            # =====================================================================
            # Tab 4：AI 中性舆情解构 —— 新闻事件性质客观分类（不变）
            # =====================================================================
            with tab4:
                # V10.1：标题与副标题分两行，杜绝挤成一行
                st.markdown("## 📰 近期新闻事件性质客观分类", unsafe_allow_html=True)
                st.caption("基于新闻标题关键词的客观事件性质分类，非对股价走势的预测")
                n_col1, n_col2 = st.columns(2)
                with n_col1:
                    st.markdown("#### 🟢 正面性质事件描述")
                    positive_kw = ['增长', '突破', '上涨', '创新高', '超预期', '合作', '获批', '中标', 'beat', 'surge', 'rally', 'upgrade', 'growth']
                    found_positive = False
                    all_news_items = []

                    yf_news = all_data.get('news', []) if all_data else []
                    ak_news = all_data.get('ak_news') if all_data else None

                    for n in yf_news[:8]:
                        all_news_items.append({'title': n.get('title', ''), 'source': n.get('publisher', '')})
                    if ak_news is not None and not ak_news.empty:
                        for _, row in ak_news.head(10).iterrows():
                            all_news_items.append({'title': row.get('新闻标题', ''), 'source': row.get('文章来源', '东方财富')})
                    for item in all_news_items:
                        t = item['title'].lower()
                        if any(kw in t for kw in positive_kw):
                            st.markdown(f'<div class="news-positive"><div class="news-title">📈 {item["title"]}</div><div class="news-meta">来源: {item["source"]} | 事件性质：正面描述（非预测）</div></div>', unsafe_allow_html=True)
                            found_positive = True
                    if not found_positive:
                        st.markdown('<div class="news-positive"><div class="news-title">暂未识别到明确正面性质事件</div></div>', unsafe_allow_html=True)
                with n_col2:
                    st.markdown("#### 🔴 负面性质事件描述")
                    negative_kw = ['下跌', '下滑', '亏损', '风险', '减持', '处罚', '调查', '下调', 'decline', 'fall', 'risk', 'downgrade', 'miss', 'loss']
                    found_negative = False
                    for item in all_news_items:
                        t = item['title'].lower()
                        if any(kw in t for kw in negative_kw):
                            st.markdown(f'<div class="news-negative"><div class="news-title">📉 {item["title"]}</div><div class="news-meta">来源: {item["source"]} | 事件性质：负面描述（非预测）</div></div>', unsafe_allow_html=True)
                            found_negative = True
                    if not found_negative:
                        st.markdown('<div class="news-neutral"><div class="news-title">暂未识别到明确负面性质事件</div></div>', unsafe_allow_html=True)

    # --- 4.6 众包财务预测 (Crowdsourcing) 与相对估值计算器 (UGC Forecasts) ---
    st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
    try:
        # [已内联] from crowdsource_agent import get_crowdsource_ui
        tk_for_crowd, _ = resolve_ticker(user_ticker_raw)
        get_crowdsource_ui(api_key_input, tk_for_crowd, all_data)
    except Exception as e:
        st.error(f"众包预测组件加载失败: {e}")

    st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
    st.markdown("---")
    st.caption("⚠️ 免责声明：本工具仅做公开数据的客观聚合与可视化展示，所有内容（包括AI生成的摘要文字）均不构成、也不应被理解为投资建议、评级或目标价推荐。投资有风险，请独立判断并自行承担决策后果。\n")
