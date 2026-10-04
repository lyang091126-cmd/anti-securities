# -*- coding: utf-8 -*-
"""V8 重构补丁：战役一(致命 Bug) + 战役二(TradingView 视觉) + 战役三(数据扩军/排序)。
每条 patch 都带断言，未命中即抛错，杜绝静默漏改。"""
import re, shutil
from pathlib import Path

P = Path(__file__).resolve().parent / "Anti Securities Report.py"
shutil.copy2(P, P.with_name("Anti Securities Report_pre_v8.py"))
src = P.read_text(encoding="utf-8")
applied = []


def sub(tag, old, new, count=1):
    global src
    n = src.count(old)
    assert n >= 1, f"[FAIL] {tag}: 未找到锚点"
    src = src.replace(old, new, count)
    applied.append(f"[OK] {tag} (命中 {n} 处，替换 {count} 处)")


# ===========================================================================
# 战役一 · 1) card_html 变量名污染（'str' object is not callable 根因）
# ===========================================================================
sub("B1-card_html 变量污染",
    """            card_html = f'<div class="market-card{hot_cls}">{hot_badge}<div class="market-flag">{icon}</div><div class="market-name">{region_label} · {idx_name}</div><div class="market-index">{price_fmt}</div><div class="{chg_cls}">{chg_sign}{chg:.2f}%</div>{sector_html}</div>'
            st.markdown(card_html, unsafe_allow_html=True)""",
    """            # ⚠️ V8 战役一：此变量原名 card_html，与 terminal_ui 的 card_html() 函数同名，
            # 单文件合并后把函数覆盖成字符串，导致 render_kpi_grid 内
            # "".join(card_html(**c) ...) 抛 TypeError: 'str' object is not callable。
            # 现重命名为 market_card_template，彻底解除命名冲突。
            market_card_template = f'<div class="market-card{hot_cls}">{hot_badge}<div class="market-flag">{icon}</div><div class="market-name">{region_label} · {idx_name}</div><div class="market-index">{price_fmt}</div><div class="{chg_cls}">{chg_sign}{chg:.2f}%</div>{sector_html}</div>'
            st.markdown(market_card_template, unsafe_allow_html=True)""")

# ===========================================================================
# 战役一 · 2) API 容错：except 分支一律返回同类型空数据，杜绝 None 二次崩溃
# ===========================================================================
for tag, key in [("recommendations", "recommendations"), ("earnings_dates", "earnings_dates"),
                 ("quarterly_financials", "quarterly_financials"),
                 ("quarterly_income_stmt", "quarterly_income_stmt"), ("income_stmt", "income_stmt"),
                 ("quarterly_cashflow", "quarterly_cashflow"), ("cashflow", "cashflow"),
                 ("quarterly_balance_sheet", "quarterly_balance_sheet"),
                 ("balance_sheet", "balance_sheet"), ("growth_estimates", "growth_estimates"),
                 ("earnings_estimate", "earnings_estimate")]:
    sub(f"B2-容错空表 {tag}",
        f"""    except Exception:
        data['{key}'] = None""",
        f"""    except Exception:
        # V8 战役一：失败返回空 DataFrame（而非 None），避免下游 .empty/.get 二次崩溃
        data['{key}'] = pd.DataFrame()""")

sub("B2-容错空表 institutional_holders",
    """    except Exception:
        data['institutional_holders'] = None""",
    """    except Exception:
        data['institutional_holders'] = pd.DataFrame()""")
sub("B2-容错空字典 analyst_targets",
    """    except Exception:
        data['analyst_targets'] = None""",
    """    except Exception:
        data['analyst_targets'] = {}""")
sub("B2-容错空表 A股附加字段",
    """    else:
        data['ak_news'] = None
        data['ak_forecast'] = None
        data['ak_info'] = None""",
    """    else:
        data['ak_news'] = pd.DataFrame()
        data['ak_forecast'] = pd.DataFrame()
        data['ak_info'] = pd.DataFrame()""")
sub("B2-宏观 ETF 列名拼写错误",
    """                    turnover = row['成交额(亿元'] if '成交额(亿元' in row else row.get('成交额(亿元)')""",
    """                    # V8：原代码列名漏写右括号（'成交额(亿元'），恒为 False 走兜底；已修正
                    turnover = row.get('成交额(亿元)') or 0.0""")

# ===========================================================================
# 战役二 · TradingView 深海蓝灰配色系统（全局唯一色彩来源）
# ===========================================================================
sub("U1-色彩常量升级",
    '''C_UP = "#00E676"        # 上涨 / 资金流入 / 低估
C_UP_DIM = "#00b865"
C_DOWN = "#FF4B4B"      # 下跌 / 资金流出 / 高估
C_DOWN_DIM = "#ef4444"
C_NEUTRAL = "#8B93A7"   # 中性 / 标签 / 说明
C_NEUTRAL_DIM = "#64748B"
C_ACCENT = "#00F2FE"    # 强调（终端青）
C_WARN = "#FBBF24"
C_TEXT = "#F0F4F8"
C_BG_CARD = "rgba(19, 23, 34, 0.92)"
C_BORDER = "rgba(255, 255, 255, 0.07)"''',
    '''# V8 视觉规范：对齐 TradingView 深海蓝灰质感，废弃纯黑底与刺眼纯红纯绿
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
C_BG_APP = "#131722"    # 全局背景（深海军蓝，非纯黑）
C_BG_PANEL = "#171B26"
C_BG_CARD = "#1E222D"   # 卡片底
C_BORDER = "#2B3139"    # 分隔边框''')

sub("U2-终端 CSS 深海蓝灰化",
    """<style>
/* ---------- 全局空间感：极窄边距，最大化数据密度 ---------- */
.block-container {{""",
    """<style>
/* ---------- V8 全局底色：深海军蓝，彻底废弃纯黑 ---------- */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
    background: {C_BG_APP} !important;
}}
[data-testid="stHeader"] {{ background: {C_BG_APP} !important; }}
body, p, span, div, li {{ color: {C_TEXT}; }}

/* ---------- 全局空间感：极窄边距，最大化数据密度 ---------- */
.block-container {{""")

sub("U3-metric 卡片底色",
    """div[data-testid="stMetric"] {{
    background: rgba(19,23,34,0.92);
    border: 1px solid rgba(255,255,255,0.07);""",
    """div[data-testid="stMetric"] {{
    background: {C_BG_CARD};
    border: 1px solid {C_BORDER};""")

sub("U4-tcard 卡片底色",
    """.tcard {{
    background: linear-gradient(160deg, rgba(24,29,42,0.96) 0%, rgba(15,18,27,0.96) 100%);
    border: 1px solid rgba(255,255,255,0.07);""",
    """.tcard {{
    background: {C_BG_CARD};
    border: 1px solid {C_BORDER};""")

sub("U5-tcard hover 与主数值配色",
    """.tcard:hover {{ border-color: rgba(0,242,254,0.28); }}""",
    """.tcard:hover {{ border-color: {C_ACCENT}; box-shadow: 0 2px 14px rgba(41,98,255,0.18); }}""")
sub("U6-tcard 主数值文字色",
    """    font-size: 1.22rem; font-weight: 800; color: {C_TEXT};""",
    """    font-size: 1.22rem; font-weight: 800; color: {C_TEXT_STRONG};""")

sub("U7-主文件 fin-card 卡片底色",
    """    .fin-card {
        background: #0A0D14 !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;""",
    """    .fin-card {
        background: #1E222D !important;
        border: 1px solid #2B3139 !important;""")
sub("U8-涨跌语义色统一(fin-trend)",
    """    .trend-up {
        color: #ef4444 !important;
    }
    .trend-down {
        color: #00b865 !important;
    }""",
    """    /* V8 语义统一：上行=专业沉稳绿 #26A69A，下行=专业警示红 #EF5350 */
    .trend-up {
        color: #26A69A !important;
    }
    .trend-down {
        color: #EF5350 !important;
    }""")
sub("U9-全球市场卡片配色",
    """    .market-card {
        background: rgba(22, 27, 38, 0.75) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;""",
    """    .market-card {
        background: #1E222D !important;
        border: 1px solid #2B3139 !important;""")
sub("U10-市场涨跌色",
    """    .market-chg-up { color: #00E676; font-size: 0.82rem; font-weight: 600; }
    .market-chg-down { color: #FF4B4B; font-size: 0.82rem; font-weight: 600; }""",
    """    .market-chg-up { color: #26A69A; font-size: 0.82rem; font-weight: 600; }
    .market-chg-down { color: #EF5350; font-size: 0.82rem; font-weight: 600; }""")
sub("U11-新闻情绪条配色",
    """    .news-positive { border-left: 4px solid #00b865; background: rgba(0,184,101,0.06);""",
    """    .news-positive { border-left: 4px solid #26A69A; background: rgba(38,166,154,0.08);""")
sub("U12-新闻负面条配色",
    """    .news-negative { border-left: 4px solid #ef4444; background: rgba(239,68,68,0.06);""",
    """    .news-negative { border-left: 4px solid #EF5350; background: rgba(239,83,80,0.08);""")
sub("U13-分位进度条配色",
    """        background: linear-gradient(90deg, #00b865 0%, #fbbf24 50%, #ef4444 100%);""",
    """        background: linear-gradient(90deg, #26A69A 0%, #FF9800 50%, #EF5350 100%);""")
sub("U14-kpi 霓虹卡片改深海蓝灰",
    """    .kpi-neon-card {
        background: rgba(22, 27, 38, 0.75); border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px; padding: 1rem; text-align: center; height: 100%;
    }
    .kpi-neon-label { font-size: 0.78rem; color: #94A3B8; margin-bottom: 0.4rem; }
    .kpi-neon-value { font-size: 1.6rem; font-weight: 900; color: #00F2FE; text-shadow: 0 0 12px rgba(0,242,254,0.35); }""",
    """    .kpi-neon-card {
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
    .gapbar-val { flex:0 0 168px; font-size:0.78rem; font-weight:700; text-align:right; }""")

# ===========================================================================
# 战役三 · 深度财务扩军：CAPEX / FCF / 盈利惊喜（Beat-Miss）+ 水位差进度条
# ===========================================================================
sub("D1-新增财务扩军计算与图表引擎",
    "def _resolve_forward_growth(all_data: dict):",
    '''CAPEX_KEYS = ["Capital Expenditure", "CapitalExpenditure", "Capital Expenditures",
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


def _resolve_forward_growth(all_data: dict):''')

sub("D2-新增 EPS 惊喜图与水位差进度条渲染器",
    """# ============================================================================
# ▼▼▼ 内联模块：macro_capital.py""",
    '''# ===========================================================================
# 8. V8：EPS 盈利惊喜（Beat/Miss）柱状图 —— 用于填补右侧物理空白
# ===========================================================================
def build_eps_surprise_chart(rows, height=300):
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
        margin=dict(l=8, r=8, t=34, b=8), paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
        title=dict(text="盈利惊喜历史 · EPS 预期 vs 实际（Beat / Miss）",
                   font=dict(size=12), x=0.01),
        legend=dict(orientation="h", y=1.14, x=0, font=dict(size=9)),
        yaxis=dict(title="EPS", title_font=dict(size=9), gridcolor="rgba(255,255,255,0.05)"),
        xaxis=dict(tickfont=dict(size=9)),
    )
    return fig


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
# ▼▼▼ 内联模块：macro_capital.py''')

# ---- Tab2：右侧空白填充（CAPEX/FCF 卡片 + EPS 惊喜图 + 近四季 EPS） ----
sub("D3-Tab2 高密度双列补白",
    """                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")

                def fnum(v, pct=False, money=False):""",
    """                # =====================================================================
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

                ex_c1, ex_c2 = st.columns([1, 1.2])
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
                    fig_eps = build_eps_surprise_chart(eps_rows, height=300)
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

                def fnum(v, pct=False, money=False):""")

# ---- 同业估值基准区加入水位差进度条 ----
sub("D4-估值水位差进度条可视化",
    """                    st.caption("📌 高于同业中位数以 Crimson Red 标注（相对高估），低于以 Neon Green 标注（相对低估）；"
                               "纯倍数比较，不构成买卖建议。")""",
    """                    # V8：横向进度条直观呈现【本标的】与【同业中位】的折溢价空间
                    render_gap_bars([
                        ("PE 水位差", cur_pe, bench.get('pe')),
                        ("PB 水位差", cur_pb, bench.get('pb')),
                        ("PS 水位差", cur_ps, bench.get('ps')),
                    ])
                    st.caption("📌 进度条中轴为同业实时中位数；向右(红)代表相对溢价，向左(绿)代表相对折价；"
                               "纯倍数比较，不构成买卖建议。")""")

# ===========================================================================
# 战役三 · 全局渲染顺序：搜索栏提到首屏（同时修复快讯模块拿不到 API Key 的缺陷）
# ===========================================================================
SETTINGS_BLOCK = """# --- 4.5 设置行（从宏观切入微观的过渡，物理对称级对齐） ---
set_c1, set_c2, set_c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
with set_c1:
    user_ticker_raw = st.text_input("代码 / 简称 (例如 AAPL, 600519.SS)", value=st.session_state.selected_ticker)
with set_c2:
    api_key_input_val = st.text_input("API 密钥 (必填)", value=api_key_input, type="password", key="api_key_state")
    api_key_input = api_key_input_val
with set_c3:
    generate_btn = st.button("🚀 生成研报", key="btn_main_generate", width="stretch")
"""
assert SETTINGS_BLOCK in src, "[FAIL] 未找到设置行区块"
src = src.replace(SETTINGS_BLOCK, """# --- 4.5 （已上移至首屏第一层）---
# V8 战役三：搜索栏/API Key/生成按钮已上移到页面顶部第一层。
# 副作用修复：原顺序下 api_key_input 在快讯模块渲染之后才被赋值，
# 导致「AI 深度客观解读」永远拿到空 Key；上移后该缺陷一并消除。
""", 1)

sub("L1-搜索栏上移至首屏",
    '''st.caption("⚠️ 本终端仅做客观公开数据聚合与可视化，绝不生成任何投资评级、目标价推荐或仓位建议。")''',
    '''st.caption("⚠️ 本终端仅做客观公开数据聚合与可视化，绝不生成任何投资评级、目标价推荐或仓位建议。")

# -------------------------------------------------------------------
# 第一层：标的搜索栏 + API Key + 生成按钮（V8 全局渲染顺序重排：置于首屏）
# -------------------------------------------------------------------
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = "NVDA"

set_c1, set_c2, set_c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
with set_c1:
    user_ticker_raw = st.text_input("🔎 标的代码 / 简称 (例如 AAPL, 600519.SS, 贵州茅台)",
                                    value=st.session_state.selected_ticker)
with set_c2:
    api_key_input_val = st.text_input("API 密钥 (必填)", value=api_key_input,
                                      type="password", key="api_key_state")
    api_key_input = api_key_input_val
with set_c3:
    generate_btn = st.button("🚀 生成研报", key="btn_main_generate", width="stretch")

st.markdown('<div class="spacer-sm"></div>', unsafe_allow_html=True)''')

sub("L2-移除热门标的处的重复初始化",
    """if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = "NVDA"

display_stocks = hot_stocks_list[:8]""",
    """# （selected_ticker 初始化已随搜索栏一并上移至首屏第一层）
display_stocks = hot_stocks_list[:8]""")

P.write_text(src, encoding="utf-8")
print("\n".join(applied))
print(f"\n共应用 {len(applied)} 组补丁；备份：Anti Securities Report_pre_v8.py")
