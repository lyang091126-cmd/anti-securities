import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import akshare as ak
from datetime import datetime, timedelta
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
                    turnover = row['成交额(亿元'] if '成交额(亿元' in row else row.get('成交额(亿元)')
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
            st.plotly_chart(fig_etf, use_container_width=True, key="macro_etf_barchart")
            
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
            end_date_trend = datetime.now()
            start_date_trend = end_date_trend - timedelta(days=45)
            
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
                cutoff_date = datetime(2026, 1, 1)
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
                
                st.plotly_chart(fig_trend, use_container_width=True, key=f"flow_trend_{etf_tk}")
            else:
                st.info("暂无足够的历史日线数据来估算资金流趋势。")
        except Exception as e:
            st.info(f"资金流量趋势计算暂缓: {e}")

        st.markdown("---")
        st.markdown("### 🗺️ 全市场行业主力资金净流入热力图 (Treemap)")
        st.caption("方块大小代表资金活跃度(净额绝对值)，红色代表净流入，绿色代表净流出。点击可下钻或悬停查看详情。")
        
        df_sector = fetch_sector_fund_flow()
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
                st.plotly_chart(fig_tree, use_container_width=True, key="macro_treemap")
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
                t_date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
                try:
                    res_dict = ak.get_cffex_rank_table(date=t_date)
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
