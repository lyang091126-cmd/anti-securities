"""
terminal_ui.py — V7 「彭博化」终端 UI 引擎
================================================================================
战役三专用模块：高密度 Grid 布局 + 暗黑专业质感 + 语义化色彩规范。

对外能力：
  inject_terminal_css()          全局极窄边距 + 卡片化视觉系统（一次性注入）
  render_command_center()        顶部 4×N 数据仪表盘矩阵（含估值分位迷你进度条）
  render_kpi_grid()             通用高密度 KPI 卡片矩阵
  build_pro_kline_chart()        专业级 K 线：多均线(含 MA120/MA250 牛熊线)+量+MACD+RSI
  build_dupont_chart()           杜邦三因子驱动引擎瀑布/矩阵图
  build_scenario_chart()         估值推演多情景（悲观/中性/乐观）靶心区间图
  build_quality_bridge_chart()   经营性现金流 vs 净利润 利润含金量对比图

色彩语义（严格执行，全站唯一来源 fundamentals 常量）：
  上涨/流入/低估 → C_UP   下跌/流出/高估 → C_DOWN   中性/标签 → C_NEUTRAL
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from fundamentals import (
    C_UP, C_UP_DIM, C_DOWN, C_DOWN_DIM, C_NEUTRAL, C_NEUTRAL_DIM,
    C_ACCENT, C_WARN, C_TEXT, sf,
)

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
    background: rgba(19,23,34,0.92);
    border: 1px solid rgba(255,255,255,0.07);
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
    background: linear-gradient(160deg, rgba(24,29,42,0.96) 0%, rgba(15,18,27,0.96) 100%);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 10px;
    padding: 0.62rem 0.8rem;
    box-shadow: 0 2px 10px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.03);
    display: flex; flex-direction: column; justify-content: space-between;
    min-height: 82px;
}}
.tcard:hover {{ border-color: rgba(0,242,254,0.28); }}
.tcard-label {{
    font-size: 0.7rem; font-weight: 600; letter-spacing: 0.4px;
    color: {C_NEUTRAL}; text-transform: uppercase; margin-bottom: 4px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.tcard-value {{
    font-size: 1.22rem; font-weight: 800; color: {C_TEXT};
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
        margin=dict(l=8, r=8, t=28, b=8), paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
        hovermode="x unified", bargap=0.05,
        legend=dict(orientation="h", y=1.06, x=0, font=dict(size=9), bgcolor="rgba(0,0,0,0)"),
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
    return fig


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
    return fig


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
    return fig
