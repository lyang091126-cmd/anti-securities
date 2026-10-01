"""snapshot.py · 数据快照：云端被 Yahoo 限流时的真实数据备份

为什么需要
    本地运行时 Yahoo 接口一切正常；但部署在 Streamlit Community Cloud 时，
    多个应用共用同一批出口 IP，Yahoo 对公司资料类接口（基本信息、财报、
    分析师评级与目标价、机构观点）频繁返回 YFRateLimitError，页面大面积显示缺失。
    行情 K 线类接口不受影响。

做法
    tools/build_snapshot.py 在本地对 UNIVERSE 中的股票各取一次完整数据，
    原样存入 data/snapshots/<代码>/<种类>.pkl，并在 data/snapshots/meta.json 记录构建日期。
    网页取数时，若实时结果呈现限流特征，则改读快照，页面明确提示"快照数据，截至某日"。
    快照是某一天的真实接口返回值，不做任何改写。

对外函数
    looks_rate_limited(all_data)   判断实时数据包是否被限流
    load(ticker, kind)             读取快照；kind ∈ {"all_data", "bench", "track"}
    save(ticker, kind, obj)        写入快照（仅构建脚本调用）
    fallback_all_data(ticker, live) 实时数据被限流且有快照时返回快照，否则原样返回
    snapshot_date()                快照构建日期字符串
"""
import json
import os
import pickle
from pathlib import Path

SNAP_DIR = Path(__file__).resolve().parent / "data" / "snapshots"
META_FILE = SNAP_DIR / "meta.json"

# 演示与评测用的美股样本：默认首页 NVDA，README 结果表中的 MSFT / AAPL，
# 外加几只分析师覆盖最密集的大市值股票。
UNIVERSE = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "JPM"]
KINDS = ("all_data", "bench", "track")

# 这几个字段只由 Yahoo 的公司资料接口提供；全部缺失即说明该接口被限流。
_YF_PROFILE_KEYS = ("industryKey", "totalRevenue", "priceToBook", "longName")


def _path(ticker: str, kind: str) -> Path:
    return SNAP_DIR / str(ticker).upper() / f"{kind}.pkl"


def snapshot_date() -> str:
    try:
        return json.loads(META_FILE.read_text(encoding="utf-8")).get("built_at", "")
    except Exception:
        return ""


def save(ticker: str, kind: str, obj) -> None:
    p = _path(ticker, kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(obj, f, protocol=4)


def load(ticker: str, kind: str):
    """读取快照并打上 _snapshot_date 标记；没有快照返回 None。
    快照文件由本仓库的构建脚本生成，属于可信来源。"""
    p = _path(ticker, kind)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            obj = pickle.load(f)
    except Exception:
        return None
    if isinstance(obj, dict):
        obj = dict(obj)
        obj["_snapshot_date"] = snapshot_date()
    return obj


def forced() -> bool:
    """本地预览云端行为：设置环境变量 ANTI_FORCE_SNAPSHOT=1，所有个股数据一律走快照。"""
    return os.environ.get("ANTI_FORCE_SNAPSHOT") == "1"


def looks_rate_limited(all_data) -> bool:
    if forced():
        return True
    info = (all_data or {}).get("info") or {}
    return not any(info.get(k) for k in _YF_PROFILE_KEYS)


def fallback_all_data(ticker: str, live: dict) -> dict:
    if looks_rate_limited(live):
        snap = load(ticker, "all_data")
        if snap is not None:
            return snap
    return live
