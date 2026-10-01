"""tools/build_snapshot.py · 在本地构建数据快照与可读数据集

用法（在项目根目录执行）
    python tools/build_snapshot.py

产出
    data/snapshots/<代码>/all_data.pkl   个股全量数据包（网页在云端被限流时使用）
    data/snapshots/<代码>/bench.pkl      同行业估值基准
    data/snapshots/<代码>/track.pkl      分析师目标价记分卡结果
    data/snapshots/meta.json             构建日期与每只股票的摘要
    data/scorecard_calls.csv             全部已计分的机构观点，一行一条，可直接用 Excel 打开
    data/buy_rating_returns.csv          全部买入类评级发布后 12 个月的股价涨跌幅

必须在本地运行：云端服务器会被 Yahoo 限流，取不到完整数据。
"""
import datetime
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import market_data  # noqa: E402
import scorecard  # noqa: E402
import snapshot  # noqa: E402


def main():
    built_at = datetime.date.today().isoformat()
    summary, all_calls, all_buys = {}, [], []
    for tk in snapshot.UNIVERSE:
        print(f"[{tk}] 取数中…", flush=True)
        row = {}

        data = market_data.fetch_all_data(tk)
        if snapshot.looks_rate_limited(data):
            print(f"  ! {tk} 公司资料被限流，本只跳过 all_data 快照")
            row["all_data"] = False
        else:
            snapshot.save(tk, "all_data", data)
            row["all_data"] = True
        info = data.get("info") or {}

        bench = market_data.fetch_industry_benchmark(
            tk, info.get("industryKey", ""), info.get("industry", ""), False, tk)
        if bench:
            snapshot.save(tk, "bench", bench)
        row["bench_peers"] = int(bench["peer_count"]) if bench else 0

        track = scorecard.fetch_analyst_track_record(tk)
        if track.get("ok"):
            snapshot.save(tk, "track", track)
            calls = track["calls"].copy()
            calls.insert(0, "ticker", tk)
            all_calls.append(calls)
            row.update(n_scored=track["n_scored"], n_pending=track["n_pending"],
                       n_firms=track["n_firms"], hit_rate=round(track["hit_rate"], 1),
                       median_abs_err=round(track["median_abs_err"], 1),
                       window=list(track["span"]))
        else:
            row["track_error"] = track.get("reason")

        buys = scorecard.buy_rating_returns(tk)
        if not buys.empty:
            buys.insert(0, "ticker", tk)
            all_buys.append(buys)
            row.update(n_buy_ratings=len(buys),
                       buy_rose_share=round(float((buys["ret"] > 0).mean() * 100), 1),
                       buy_median_ret=round(float(buys["ret"].median() * 100), 1))

        summary[tk] = row
        print(f"  {row}")
        time.sleep(2)          # 放慢节奏，避免本机也触发限流

    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    if all_calls:
        pd.concat(all_calls).to_csv(data_dir / "scorecard_calls.csv", index=False,
                                    encoding="utf-8-sig", float_format="%.4f")
    if all_buys:
        pd.concat(all_buys).to_csv(data_dir / "buy_rating_returns.csv", index=False,
                                   encoding="utf-8-sig", float_format="%.4f")
    snapshot.SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snapshot.META_FILE.write_text(json.dumps(
        {"built_at": built_at, "universe": snapshot.UNIVERSE, "tickers": summary},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("完成:", built_at)


if __name__ == "__main__":
    main()
