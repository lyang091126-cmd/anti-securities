"""evals/test_scorecard.py · 记分卡核心算法的离线单元测试

不联网。用一只人工构造的"假股票"替换 yfinance，价格与机构观点都是手工设定的，
每条观点该判命中还是未中，事先就能手算出来，再与程序结果比对。

覆盖的规则
    1. 看多观点：12 个月后价格 >= 目标价才算命中
    2. 看空观点：12 个月后价格 <= 目标价才算命中
    3. 未满 252 个交易日的观点不计分，单独计入 n_pending
    4. 目标价为 0 的脏数据被剔除
    5. 拆股折算：拆股前发布的目标价要除以之后的拆股比例，否则会被误判
    6. 买入评级收益：评级发布后 252 个交易日的涨跌幅计算正确
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scorecard  # noqa: E402

H = scorecard.ANALYST_TRACK_HORIZON          # 252
DAYS = pd.bdate_range("2020-01-01", periods=600)


class _FakeTicker:
    def __init__(self, prices, calls, splits):
        self._px, self._calls, self._splits = prices, calls, splits

    @property
    def upgrades_downgrades(self):
        return self._calls

    @property
    def splits(self):
        return self._splits

    def history(self, period="10y", auto_adjust=True):
        return pd.DataFrame({"Close": self._px})


def _install(prices, calls, splits=None):
    fake = _FakeTicker(prices, calls, splits if splits is not None else pd.Series(dtype=float))
    scorecard.yf = type("FakeYF", (), {"Ticker": staticmethod(lambda t: fake)})


def _calls(rows):
    """rows: [(第几个交易日, 机构, 目标价, 评级)]"""
    return pd.DataFrame(
        {"Firm": [r[1] for r in rows], "currentPriceTarget": [r[2] for r in rows],
         "ToGrade": [r[3] for r in rows]},
        index=[DAYS[r[0]] for r in rows])


def test_hit_rules_and_pending():
    # 前 300 天价格 100，之后 200
    px = pd.Series([100.0] * 300 + [200.0] * 300, index=DAYS)
    _install(px, _calls([
        (10, "A", 150, "Buy"),     # 看多，第 262 天价格 100 < 150 → 未中
        (100, "B", 150, "Buy"),    # 看多，第 352 天价格 200 >= 150 → 命中
        (50, "C", 80, "Sell"),     # 看空，第 302 天价格 200 > 80 → 未中
        (400, "D", 150, "Buy"),    # 400 + 252 超出序列 → 未满期，不计分
        (20, "E", 0, "Buy"),       # 目标价 0 → 剔除
    ]))
    r = scorecard.fetch_analyst_track_record("FAKE")
    assert r["ok"], r
    got = dict(zip(r["calls"]["firm"], r["calls"]["hit"]))
    assert got == {"A": False, "B": True, "C": False}, got
    assert r["n_scored"] == 3 and r["n_pending"] == 1, (r["n_scored"], r["n_pending"])
    assert abs(r["hit_rate"] - 100 / 3) < 1e-9, r["hit_rate"]


def test_split_adjustment():
    # 第 200 天 10 拆 1。复权后价格前 300 天 100、之后 160。
    # 第 50 天的机构按当时未拆股价格 1000 发布目标价 1500，折算后为 150。
    px = pd.Series([100.0] * 300 + [160.0] * 300, index=DAYS)
    calls = _calls([(50, "A", 1500, "Buy")])
    splits = pd.Series([10.0], index=[DAYS[200]])

    _install(px, calls, splits)
    fixed = scorecard.fetch_analyst_track_record("FAKE", fix_splits=True)
    assert fixed["calls"]["target"].iloc[0] == 150 and bool(fixed["calls"]["hit"].iloc[0]), fixed["calls"]

    _install(px, calls, splits)
    raw = scorecard.fetch_analyst_track_record("FAKE", fix_splits=False)
    assert raw["calls"]["target"].iloc[0] == 1500 and not bool(raw["calls"]["hit"].iloc[0]), raw["calls"]


def test_no_split_after_call_means_no_change():
    # 拆股发生在观点之前：目标价不该被再折算一次
    px = pd.Series([100.0] * 600, index=DAYS)
    _install(px, _calls([(250, "A", 120, "Buy")]), pd.Series([10.0], index=[DAYS[100]]))
    r = scorecard.fetch_analyst_track_record("FAKE")
    assert r["calls"]["target"].iloc[0] == 120, r["calls"]


def test_no_coverage_is_reported_not_faked():
    px = pd.Series([100.0] * 600, index=DAYS)
    _install(px, pd.DataFrame())
    r = scorecard.fetch_analyst_track_record("FAKE")
    assert r["ok"] is False and "无历史机构观点覆盖" in r["reason"], r


def test_buy_rating_returns():
    px = pd.Series([100.0] * 300 + [130.0] * 300, index=DAYS)
    _install(px, _calls([(100, "A", 150, "Buy"), (60, "B", 90, "Sell"), (420, "C", 150, "Buy")]))
    r = scorecard.buy_rating_returns("FAKE")
    # 只有 A：买入类且已满期；B 是卖出评级，C 未满期
    assert list(r["firm"]) == ["A"], r
    assert abs(r["ret"].iloc[0] - 0.30) < 1e-9, r


def test_firm_league_threshold():
    calls = pd.DataFrame({"firm": ["X"] * 8 + ["Y"] * 3,
                          "hit": [True] * 6 + [False] * 2 + [True] * 3,
                          "abs_err_pct": [10.0] * 11})
    g = scorecard.summarize_firm_accuracy(calls, min_calls=8)
    assert list(g.index) == ["X"], g          # Y 只有 3 条，不进榜
    assert g.loc["X", "命中率"] == 75.0, g
