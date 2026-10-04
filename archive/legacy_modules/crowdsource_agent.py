import streamlit as st
import json
import os
import numpy as np
import pandas as pd
import plotly.express as px

# V7：同业估值基准动态引擎 + 彭博化 UI 组件
from fundamentals import fetch_industry_benchmark, sf, C_UP, C_DOWN, C_NEUTRAL, C_ACCENT
from terminal_ui import render_kpi_grid, section_bar, build_scenario_chart

def get_crowdsource_ui(api_key, ticker, all_data=None):
    if not ticker:
        return
        
    st.markdown("---")
    st.markdown(f"## 🧮 【{ticker}】估值模型及财务推演计算器")
    st.markdown("<div style='font-size:0.85rem; opacity:0.8; margin-bottom:1rem;'>基于同行业估值水平与未来业绩预期，全自动多维推演并展示个股相对合理股价与估值水位差。</div>", unsafe_allow_html=True)
    
    # 提取客观基础财务指标
    info = all_data.get('info', {}) if all_data else {}
    price = info.get('currentPrice') or info.get('regularMarketPrice') or 1.0
    mcap = info.get('marketCap')
    currency = info.get('currency', 'USD')
    is_usd = currency in ['USD', '$']
    unit_lbl = "亿美元" if is_usd else "亿元"
    price_lbl = "$" if is_usd else "元"
    
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
    calc_c1, calc_c2 = st.columns([1, 1.2])
    
    with calc_c1:
        st.write("#### 1. 预测财务指标")
        
        # P2: 新增标的选择输入框
        target_ticker = st.text_input(
            "选择需要预测的标的代码/简称 (按回车确认)", 
            value=st.session_state.get('selected_ticker', ticker), 
            key="crowd_target_ticker_input"
        )
        def resolve_tk(t):
            t = t.strip().upper()
            if t.isdigit() and len(t) == 6:
                if t.startswith(('60', '68', '90', '51')):
                    return f"{t}.SS"
                elif t.startswith(('00', '30', '20', '15')):
                    return f"{t}.SZ"
                elif t.startswith(('8', '4', '92')):
                    return f"{t}.BJ"
            return t

        resolved_target = resolve_tk(target_ticker) if target_ticker else ""
        if resolved_target and resolved_target != st.session_state.get('selected_ticker', ticker):
            st.session_state.selected_ticker = resolved_target
            st.rerun()
            
        pred_rev = st.number_input(f"预测营业收入 ({unit_lbl})", min_value=0.0, value=float(def_rev) if def_rev > 0 else 100.0, step=10.0, key="calc_pred_rev")
        pred_net_inc = st.number_input(f"预测净利润 ({unit_lbl})", min_value=0.0, value=float(def_net_inc) if def_net_inc > 0 else 15.0, step=2.0, key="calc_pred_net_inc")
        pred_net_assets = st.number_input(f"预测净资产 ({unit_lbl})", min_value=0.0, value=float(def_net_assets) if def_net_assets > 0 else 60.0, step=5.0, key="calc_pred_net_assets")
        
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
            dict(label="推演合理股价区间", value=f"{price_lbl}{min_p:,.2f} ~ {price_lbl}{max_p:,.2f}",
                 sub=f"当前实际股价 {price_lbl}{price:,.2f}", value_direction="accent"),
            dict(label="推演目标市值区间", value=f"{min_m:,.2f}亿 ~ {max_m:,.2f}亿",
                 sub=f"{curr_zh} · 股本基准 {shares_in_100m:.2f} 亿股"),
            dict(label="PE 法推演价",
                 value=(f"{price_lbl}{pe_price:,.2f}" if pe_price > 0 else "同业 PE 缺失"),
                 sub=(f"预测净利 × 同业 PE {ref_pe:.2f}x" if ref_pe else "无真实同业 PE，不推演")),
            dict(label="PB 法推演价",
                 value=(f"{price_lbl}{pb_price:,.2f}" if pb_price > 0 else "同业 PB 缺失"),
                 sub=(f"预测净资产 × 同业 PB {ref_pb:.2f}x" if ref_pb else "无真实同业 PB，不推演")),
            dict(label="PS 法推演价",
                 value=(f"{price_lbl}{ps_price:,.2f}" if ps_price > 0 else "同业 PS 缺失"),
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
                            except:
                                pass
                    existing_data.append(parsed_data)
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(existing_data, f, ensure_ascii=False, indent=2)
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
                c3_s.metric("一致预期合理股价 (中位数)", f"{price_lbl}{med_prc:.2f}")
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
                st.plotly_chart(fig_hist, width="stretch", key=f"crowd_price_hist_{ticker}")
            
            with st.expander("💬 查看大家的核心逻辑提炼 (最新10条)"):
                for idx, lg in enumerate(reversed(logics[-10:])):
                    st.markdown(f"- **玩家 {len(logics)-idx}**: {lg}")
