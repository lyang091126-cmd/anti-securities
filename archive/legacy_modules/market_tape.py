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
            valid_news.append(item) # 解析失败暂保留

    # 按照时间倒序排序
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
