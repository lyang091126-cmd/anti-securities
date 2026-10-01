"""scorecard.py · 分析师目标价准确度记分卡（本项目的核心算法）

问题
    卖方分析师给出的目标价，12 个月后到底兑现了没有？

对外函数
    fetch_analyst_track_record(ticker, horizon=252)
        回测某只股票全部带目标价的历史机构观点，返回命中率、中位绝对误差、
        已计分 / 未满期条数、样本区间，以及逐条明细 DataFrame。
    summarize_firm_accuracy(calls, min_calls=8)
        按机构汇总命中率，样本少于 min_calls 的机构不进榜。
    buy_rating_returns(ticker, horizon=252)
        付费功能「分析师战绩总结」的原型：每条买入类评级发布后 horizon 个交易日的
        股价涨跌幅，以及同期是否上涨。

评测
    evals/ 目录下的脚本直接调用本文件的函数，验证拆股折算、分红口径与命中规则。
"""
import numpy as np
import pandas as pd
import yfinance as yf


# ===========================================================================
# 分析师目标价准确度追踪（Analyst Call Accuracy Tracker）
# ---------------------------------------------------------------------------
# 本终端的核心主张：不预测，只检验别人预测得准不准。
#
# 口径定义（必须显式声明，否则"命中率"是无意义的数字）：
#   · 样本      = yfinance upgrades_downgrades 中带目标价的历史机构观点
#   · 评分时点  = 观点发布日 + HORIZON 个交易日（默认 252 ≈ 12 个月，
#                 对应卖方目标价惯用的 12 个月前瞻期）
#   · 命中定义  = 终点判定，而非"期间是否触及过"。
#                 看多观点（目标价 ≥ 发布日股价）：H 日后股价 ≥ 目标价 → 命中
#                 看空观点（目标价 < 发布日股价）：H 日后股价 ≤ 目标价 → 命中
#   · 绝对误差  = |H日实际股价 − 目标价| / 目标价
#   · 未满 H 个交易日的观点一律不计分（避免用未完成的观点凑样本）
#
# 价格口径：取 auto_adjust=False 的 Close（只做拆股调整、不做分红调整），
#   与机构发布目标价时看到的真实股价一致；分红调整价会把老股价压低数个百分点。
#
# ⚠️ 拆股陷阱（本项目实测发现并修正的第二个静默失败）：
#   yfinance 的历史价格是**复权后**的，但 upgrades_downgrades 里的目标价是
#   机构**当时按未拆股价格发布**的原值。NVDA 2024-06-10 做了 10:1 拆股，
#   拆股前的目标价是 1100~1350，而同期复权价只有约 106——直接相比会把
#   拆股前的每一条观点都误判为惨败。实测：不修正时 NVDA 命中率 16.4%、
#   中位误差 80.6%；按发布日之后的累计拆股比例折算目标价后，回到 73.8% / 46.5%。
#   对照组 MSFT（2003 年后未拆股）修正前后均为 56.9%，纹丝不动，
#   证明该修正只作用于真正发生过拆股的标的。
# ===========================================================================
ANALYST_TRACK_HORIZON = 252     # 交易日；约 12 个月
ANALYST_TRACK_MIN_CALLS = 8     # 机构榜单入榜门槛，样本太少的命中率无统计意义


def fetch_analyst_track_record(ticker: str, horizon: int = ANALYST_TRACK_HORIZON,
                               fix_splits: bool = True, dividend_adjusted: bool = False):
    """回测某标的的历史机构目标价命中情况。

    fix_splits / dividend_adjusted 两个开关只供 evals/ 做对照实验，网页始终用默认值：
    折算拆股、不做分红调整。

    返回 dict(ok=True, calls=DataFrame, ...) 或 dict(ok=False, reason=...)。
    绝不在数据缺失时返回编造的统计量——reason 会说明到底缺什么。
    """
    try:
        tk = yf.Ticker(ticker)
        ud = tk.upgrades_downgrades
    except Exception as e:
        return {"ok": False, "reason": f"分析师观点接口调用失败：{type(e).__name__}"}
    if ud is None or not isinstance(ud, pd.DataFrame) or ud.empty:
        return {"ok": False, "reason": "该市场无历史机构观点覆盖"}

    try:
        # auto_adjust=False：Close 列只按拆股调整、不按分红调整。
        # 默认的 auto_adjust=True 还会做分红调整，把历史股价压低
        # （MSFT 2019-06-03 真实收盘 119.84，默认口径给 112.31，低了 6.3%），
        # 而机构目标价按真实股价发布，从不含分红调整——会系统性多判"未中"。
        px = tk.history(period="10y", auto_adjust=dividend_adjusted)["Close"]
        splits = tk.splits
    except Exception as e:
        return {"ok": False, "reason": f"历史价格接口调用失败：{type(e).__name__}"}
    if px is None or px.empty:
        return {"ok": False, "reason": "历史价格序列为空，无法定位观点发布日股价"}

    px = px.copy()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    ud = ud.copy()
    ud.index = pd.to_datetime(ud.index).tz_localize(None)
    ud = ud.sort_index()
    if splits is not None and len(splits):
        splits = splits.copy()
        splits.index = pd.to_datetime(splits.index).tz_localize(None)

    if "currentPriceTarget" not in ud.columns:
        return {"ok": False, "reason": "该标的的机构观点不含目标价字段"}
    d = ud[ud["currentPriceTarget"].notna() & (ud["currentPriceTarget"] > 0)]
    if d.empty:
        return {"ok": False, "reason": "历史机构观点中没有任何带目标价的记录"}

    rows, n_pending = [], 0
    for dt, r in d.iterrows():
        prior = px.index[px.index <= dt]
        if len(prior) == 0:
            continue
        dt0 = prior[-1]
        i = px.index.get_loc(dt0)
        if i + horizon >= len(px):
            n_pending += 1          # 观点尚未满 horizon，不计分
            continue
        tgt = float(r["currentPriceTarget"])
        # 折算拆股：把当时发布的原始目标价换算到与复权价同一口径
        if fix_splits and splits is not None and len(splits) and (splits.index > dt0).any():
            factor = float(splits[splits.index > dt0].prod())
            if factor > 0:
                tgt = tgt / factor
        p0, pH = float(px.iloc[i]), float(px.iloc[i + horizon])
        if p0 <= 0 or tgt <= 0:
            continue
        bullish = tgt >= p0
        rows.append({
            "firm": str(r.get("Firm") or "未署名"),
            "date": dt0.strftime("%Y-%m-%d"),
            "price_at_call": p0,
            "target": tgt,
            "price_at_horizon": pH,
            "bullish": bullish,
            "hit": bool(pH >= tgt) if bullish else bool(pH <= tgt),
            "abs_err_pct": abs(pH - tgt) / tgt * 100.0,
        })

    if not rows:
        return {"ok": False,
                "reason": f"有 {n_pending} 条观点尚未满 {horizon} 个交易日，暂无可计分样本"}
    calls = pd.DataFrame(rows)
    return {
        "ok": True,
        "calls": calls,
        "n_scored": len(calls),
        "n_pending": n_pending,
        "n_firms": int(calls["firm"].nunique()),
        "hit_rate": float(calls["hit"].mean() * 100),
        "median_abs_err": float(calls["abs_err_pct"].median()),
        "horizon": horizon,
        "span": (calls["date"].min(), calls["date"].max()),
    }


def summarize_firm_accuracy(calls: pd.DataFrame, min_calls: int = ANALYST_TRACK_MIN_CALLS):
    """按机构汇总命中率；样本数低于门槛的机构不进榜（小样本命中率无意义）。"""
    if calls is None or calls.empty:
        return pd.DataFrame()
    g = calls.groupby("firm").agg(
        样本数=("hit", "size"),
        命中率=("hit", "mean"),
        中位绝对误差=("abs_err_pct", "median"),
    )
    g = g[g["样本数"] >= min_calls]
    if g.empty:
        return g
    g["命中率"] = (g["命中率"] * 100).round(1)
    g["中位绝对误差"] = g["中位绝对误差"].round(1)
    return g.sort_values("命中率", ascending=False)


BUY_GRADES = {"buy", "strong buy", "outperform", "overweight", "market outperform",
              "sector outperform", "positive", "accumulate", "add"}


def buy_rating_returns(ticker: str, horizon: int = ANALYST_TRACK_HORIZON):
    """付费功能原型：机构给出买入类评级后，股价在 horizon 个交易日后的表现。

    返回 DataFrame[firm, date, grade, ret]，ret 为小数收益率（0.25 = 涨 25%）。
    价格口径与记分卡一致：只做拆股调整、不做分红调整的收盘价。
    """
    tk = yf.Ticker(ticker)
    ud = tk.upgrades_downgrades
    if ud is None or ud.empty or "ToGrade" not in ud.columns:
        return pd.DataFrame(columns=["firm", "date", "grade", "ret"])
    px = tk.history(period="10y", auto_adjust=False)["Close"]
    px.index = pd.to_datetime(px.index).tz_localize(None)
    ud = ud.copy()
    ud.index = pd.to_datetime(ud.index).tz_localize(None)
    ud = ud.sort_index()
    rows = []
    for dt, r in ud[ud["ToGrade"].astype(str).str.lower().isin(BUY_GRADES)].iterrows():
        prior = px.index[px.index <= dt]
        if len(prior) == 0:
            continue
        i = px.index.get_loc(prior[-1])
        if i + horizon >= len(px):
            continue
        rows.append({"firm": str(r.get("Firm") or "未署名"),
                     "date": prior[-1].strftime("%Y-%m-%d"),
                     "grade": str(r["ToGrade"]),
                     "ret": float(px.iloc[i + horizon] / px.iloc[i] - 1)})
    return pd.DataFrame(rows, columns=["firm", "date", "grade", "ret"])
