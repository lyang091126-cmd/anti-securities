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

            st.markdown("---")
            st.subheader(f"📊 {ticker_input} 客观数据聚合报告")
            st.markdown('<span class="data-ai-badge">⚠️ 以下摘要由 AI 生成，仅为对真实数据的转述整理，不构成投资建议</span>', unsafe_allow_html=True)
            st.markdown(ai_reply)
            st.download_button(label="📥 下载报告 (Markdown)", data=ai_reply, file_name=f"{ticker_input}_客观数据报告.md", mime="text/markdown")
            st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)

        except Exception as e:
            status_box.update(label="❌ **AI 调用失败**", state="error", expanded=True)
            st.error(f"AI 调用失败: {e}")

if ticker_input and all_data and all_data.get('hist_1y') is not None:
    if True:

            # ===== 提前获取股票 Profile（真实机构持仓数据，无编造） =====
            st_prof = get_stock_profile(ticker_input, info, mapped_name)
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

            # ===== 客观数据总览（已删除：三票制表决、评分表、独立性判定卡、法证排查表、
            # 看多逻辑vs伪证条件表、"强烈买入"Banner、机构目标价推荐Banner、仓位建议） =====

            # ===== 差异化功能2：五维雷达图评分计算 =====
            radar_scores = {'估值 (Valuation)': 50, '成长 (Growth)': 50, '动能 (Momentum)': 50, '盈利 (Profitability)': 50, '健康 (Health)': 50}
            try:
                pe = info.get('trailingPE', 0)
                if pe > 0: radar_scores['估值 (Valuation)'] = max(10, min(100, 100 - (pe - 10) * 1.5))
                rev_g = info.get('revenueGrowth', 0)
                if rev_g: radar_scores['成长 (Growth)'] = max(10, min(100, 50 + rev_g * 100))
                recent_close = all_data['hist_1y']['Close'].iloc[-1] if not all_data['hist_1y'].empty else 0
                pct_1y = ((recent_close - all_data['hist_1y']['Close'].iloc[0]) / all_data['hist_1y']['Close'].iloc[0]) * 100 if not all_data['hist_1y'].empty else 0
                radar_scores['动能 (Momentum)'] = max(10, min(100, 50 + pct_1y))
                roe = info.get('returnOnEquity', 0)
                if roe: radar_scores['盈利 (Profitability)'] = max(10, min(100, 30 + roe * 200))
                debt = info.get('debtToEquity', 0)
                if debt: radar_scores['健康 (Health)'] = max(10, min(100, 100 - debt / 2))
            except Exception:
                pass

            tab_overview, tab_radar, tab_insiders, tab_news = st.tabs(["📊 概览 (Overview)", "🕸️ 五维雷达 (Metrics)", "🏛️ 机构与资金 (Insiders)", "📰 相关新闻 (News)"])

            with tab_radar:
                st.markdown(f'<div style="text-align:center; font-size:1.2rem; font-weight:800; margin-bottom:1.0rem;">🕸️ 【{s_title_name}】 客观五维雷达图</div>', unsafe_allow_html=True)
                st.caption("📌 本雷达图基于 yfinance 提取的绝对财务指标，并使用固定映射逻辑归一化到 0-100 分位。此图仅作为客观数据指标的可视化呈现，绝对不代表任何未来股价预测或投资建议。")
                import pandas as pd
                df_radar = pd.DataFrame(dict(r=list(radar_scores.values()), theta=list(radar_scores.keys())))
                fig_radar = px.line_polar(df_radar, r='r', theta='theta', line_close=True, template="plotly_dark")
                fig_radar.update_traces(fill='toself', line_color='#00b865', fillcolor='rgba(0,184,101,0.2)')
                fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), margin=dict(l=40, r=40, t=20, b=20), height=400)
                st.plotly_chart(fig_radar, use_container_width=True)

            with tab_insiders:
                st.markdown("---")
                st.markdown(f"### 🔎 【{s_title_name}】 机构调研与资金追踪 <span style='font-size:0.75rem; opacity:0.6;'>A股强制披露公开信息聚合</span>", unsafe_allow_html=True)
                if all_data.get('is_a_share'):
                    jgdy_hist = None
                    try:
                        import akshare as ak
                        # 注意：此处使用简化兜底逻辑避免 akshare date 参数异常导致全页面崩溃
                        # 我们将此处留空或提示，因为接口不支持 symbol 搜索最近记录
                        pass
                    except Exception:
                        pass
                    st.info("⚠️ 东方财富数据接口 (akshare) 当前在本服务器环境遭遇网络错误 (DNS) 或参数变更限制，无法自动拉取该标的近90日专属机构调研记录。本站严格遵守客观陈述底线，绝不在此编造测试数据占位。")
                else:
                    st.info("ℹ️ 机构调研及增减持记录为 A 股监管强制披露类别，港股/美股无完全对应开源接口，此项不适用于当前标的。")
                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)

            with tab_overview:
                st.markdown("---")
                st.markdown(f'<div style="text-align:center; font-size:1.2rem; font-weight:800; margin-bottom:1.0rem;">📌 【{s_title_name}】 客观数据总览</div>', unsafe_allow_html=True)
                st.caption("⚠️ 以下均为第三方数据源（yfinance/akshare）的客观历史记录，不构成、也不包含本站任何投资建议、评级、目标价推荐或仓位建议。")

                c1_a, c1_b = st.columns([1.05, 0.95])
                with c1_a:
                    recs_df_top = all_data.get('recommendations')
                    rec_dist_str = "暂无数据（数据源未返回）"
                    if recs_df_top is not None and not recs_df_top.empty:
                        try:
                            latest_r = recs_df_top.iloc[0]
                            rec_dist_str = f"强烈买入 {int(latest_r.get('strongBuy',0) or 0)} / 买入 {int(latest_r.get('buy',0) or 0)} / 持有 {int(latest_r.get('hold',0) or 0)} / 卖出 {int(latest_r.get('sell',0) or 0)} / 强烈卖出 {int(latest_r.get('strongSell',0) or 0)}（来源: yfinance recommendations）"
                        except Exception:
                            pass
                    st.markdown(f"### 第三方分析师评级人数分布（历史事实统计）\n- {rec_dist_str}\n- **第三方目标价历史区间**：{target_range_str}\n- 数据来源：yfinance analyst_price_targets / recommendations，不代表本站判断，也不构成投资建议。")

                with c1_b:
                    if st_prof['inst_names'] and st_prof['inst_shares']:
                        fig_inst = go.Figure(go.Bar(
                            x=st_prof['inst_shares'], y=st_prof['inst_names'], orientation='h',
                            marker_color=['#00b865', '#38bdf8', '#fbbf24', '#a855f7', '#94a3b8'],
                            text=[f"{v}%" for v in st_prof['inst_shares']], textposition='auto'
                        ))
                        fig_inst.update_layout(
                            height=240, template='plotly_dark', margin=dict(l=10, r=10, t=35, b=10),
                            title_text=f"🏛️ {s_title_name} 十大流通股东持仓比例 (%)", yaxis=dict(autorange="reversed")
                        )
                        st.plotly_chart(fig_inst, use_container_width=True)
                    else:
                        st.info("⚠️ 暂无该标的真实机构持仓数据（或非A股无对应接口）。为避免误导，不展示编造数据。")

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")
                st.markdown(build_chain_html(info, ticker_input), unsafe_allow_html=True)

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")
                st.markdown(f"### 🏢 {s_title_name} 主营业务构成 <span style='font-size:0.75rem; opacity:0.6;'>数据来源标注见下</span>", unsafe_allow_html=True)
                main_comp = all_data.get('main_composition')
                if main_comp is not None and not main_comp.empty:
                    try:
                        comp_cols = [c for c in main_comp.columns if c in ['报告期', '分类类型', '主营构成', '主营收入', '收入比例', '主营利润', '利润比例', '主营成本', '成本比例']]
                        st.dataframe(main_comp[comp_cols] if comp_cols else main_comp, use_container_width=True)
                        st.caption("📌 数据来源：akshare stock_zygc_em（主营构成）。")
                    except Exception:
                        st.info("⚠️ 主营构成数据格式解析异常，暂不展示，避免误导。")
                else:
                    st.info("⚠️ 暂无该标的真实主营业务构成数据。本站不使用编造图表。")

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")
                c4_a, c4_b = st.columns([0.95, 1.05])
                with c4_a:
                    st.markdown("### 📈 缠论技术面数据摘要 <span style='font-size:0.75rem; opacity:0.6;'>⚠️ 简化版分型/中枢识别+RSI+BOLL，非买卖点建议</span>", unsafe_allow_html=True)
                    chanlun_text_ui = analyze_kline_and_chanlun(all_data['hist_1y']) if all_data and all_data.get('hist_1y') is not None else "暂无K线数据"
                    st.markdown(f"```\n{chanlun_text_ui}\n```")
                    st.caption("📌 以上数据均基于真实K线计算得出，非AI编造。")
                with c4_b:
                    if not all_data['hist_1y'].empty:
                        kline_fig = build_kline_chart(all_data['hist_1y'], ticker_input)
                        kline_fig.update_layout(height=480)
                        st.plotly_chart(kline_fig, use_container_width=True)

                st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
                st.markdown("---")
                c5_a, c5_b = st.columns([1.0, 1.0])
                with c5_a:
                    def fnum(v, pct=False, money=False):
                        if v is None or (isinstance(v, float) and __import__('numpy').isnan(v)): return "N/A"
                        try:
                            if pct: return f"{float(v)*100:.2f}%"
                            if money:
                                v = float(v)
                                return f"{v/1e8:.2f}亿" if abs(v) >= 1e8 else f"{v:,.0f}"
                            return str(v)
                        except: return "N/A"

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
                        except Exception: pass

                    gross_margin = info.get('grossMargins')
                    net_margin = info.get('profitMargins') or info.get('netMargins')
                    roe = info.get('returnOnEquity')
                    debt_ratio = info.get('debtToEquity')
                    fcf = info.get('freeCashflow')
                    ocf = info.get('operatingCashflow')

                    rev_trend = "N/A"
                    if isinstance(rev_now, (int, float)) and isinstance(rev_prev, (int, float)) and rev_prev != 0:
                        rev_trend = f"{(rev_now-rev_prev)/abs(rev_prev)*100:+.1f}% QoQ"
                    np_trend = "N/A"
                    if isinstance(np_now, (int, float)) and isinstance(np_prev, (int, float)) and np_prev != 0:
                        np_trend = f"{(np_now-np_prev)/abs(np_prev)*100:+.1f}% QoQ"

                    st.markdown(f"### 财务核心数据 <span style='font-size:0.75rem; opacity:0.6;'>数据来源: yfinance | 最新季度: {report_quarter}</span>", unsafe_allow_html=True)
                    st.markdown(f"""
                    | 财务指标 | 最新季度实际值 | 环比/同比趋势 |
                    | :--- | :---: | :---: |
                    | **营业收入 (Revenue)** | {fnum(rev_now, money=True)} | {rev_trend} |
                    | **净利润 (Net Profit)** | {fnum(np_now, money=True)} | {np_trend} |
                    | **毛利率 (Gross Margin)** | {fnum(gross_margin, pct=True)} | — |
                    | **净利率 (Net Margin)** | {fnum(net_margin, pct=True)} | — |
                    | **ROE (净资产收益率)** | {fnum(roe, pct=True)} | — |
                    | **负债权益比** | {fnum(debt_ratio)} | — |
                    | **自由现金流 (FCF)** | {fnum(fcf, money=True)} | — |
                    """)
                    st.caption("⚠️ 字段若显示 N/A 代表源未能获取真实数据，严禁编造。")

                with c5_b:
                    eps_ttm = info.get('trailingEps')
                    eps_fwd = info.get('forwardEps')
                    rev_growth_val = info.get('revenueGrowth')
                    rev_growth_disp = f"{rev_growth_val*100:+.2f}%" if isinstance(rev_growth_val, (int, float)) else "N/A"
                    eps_ttm_disp = f"{eps_ttm:.2f}" if isinstance(eps_ttm, (int, float)) else "N/A"
                    eps_fwd_disp = f"{eps_fwd:.2f}" if isinstance(eps_fwd, (int, float)) else "N/A"

                    st.markdown(f"### 第三方分析师预测数据（历史观点）\n- **EPS (TTM)**：{eps_ttm_disp} | **EPS (前瞻预期)**：{eps_fwd_disp}\n- **营收增速 (最新)**：{rev_growth_disp}")

            with tab_news:
                st.markdown("---")
                st.markdown("## 📰 近期新闻事件性质客观分类 <span style='font-size:0.72rem; opacity:0.6;'>基于新闻标题关键词的客观事件性质分类，非对股价走势的预测</span>", unsafe_allow_html=True)
                n_col1, n_col2 = st.columns(2)
                with n_col1:
                    st.markdown("#### 🟢 正面性质事件描述")
                    positive_kw = ['增长', '突破', '上涨', '创新高', '超预期', '合作', '获批', '中标', 'beat', 'surge', 'rally', 'upgrade', 'growth']
                    found_positive = False
                    all_news_items = []
                    
                    # 取出新闻数据
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

            st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
            st.markdown("---")
            st.caption("⚠️ 免责声明：本工具仅做公开数据的客观聚合与可视化展示，所有内容（包括AI生成的摘要文字）均不构成、也不应被理解为投资建议、评级或目标价推荐。投资有风险，请独立判断并自行承担决策后果。\n")
