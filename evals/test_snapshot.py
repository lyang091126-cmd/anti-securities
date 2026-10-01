"""evals/test_snapshot.py · 云端限流时改读快照的切换逻辑

验证
    1. 限流特征识别：公司资料字段全空 → 判为限流；有任一字段 → 判为正常
    2. 正常数据原样返回，不会被快照覆盖
    3. 限流且有快照 → 返回快照，并带上构建日期，供页面提示用户
    4. 限流但没有快照（例如 A 股）→ 原样返回空数据，不拿别的股票顶替
    5. 仓库里的快照覆盖全部演示股票，且日期可读
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import snapshot  # noqa: E402

LIMITED = {"info": {"currentPrice": 180.0, "marketCap": 4.4e12}}   # 只剩 fast_info 补的字段
HEALTHY = {"info": {"industryKey": "semiconductors", "longName": "NVIDIA Corporation"}}


def test_rate_limit_detection():
    assert snapshot.looks_rate_limited(LIMITED)
    assert snapshot.looks_rate_limited({})
    assert not snapshot.looks_rate_limited(HEALTHY)


def test_healthy_data_passes_through():
    assert snapshot.fallback_all_data("NVDA", HEALTHY) is HEALTHY


def test_limited_data_uses_dated_snapshot():
    out = snapshot.fallback_all_data("NVDA", LIMITED)
    assert out is not LIMITED
    assert out["_snapshot_date"] == snapshot.snapshot_date() != ""
    assert out["info"].get("industryKey"), "快照本身必须是未被限流的完整数据"


def test_no_snapshot_means_no_substitution():
    assert snapshot.fallback_all_data("600519.SS", LIMITED) is LIMITED


def test_snapshot_covers_universe():
    for tk in snapshot.UNIVERSE:
        for kind in ("all_data", "track"):
            assert snapshot.load(tk, kind) is not None, (tk, kind)
