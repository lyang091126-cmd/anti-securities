"""evals/eval_split_fix.py · 价格口径对照实验（联网，约 3 分钟）

用法（项目根目录）
    python evals/eval_split_fix.py

问题
    记分卡比较的是"机构当年发布的目标价"和"12 个月后的股价"。Yahoo 的历史股价默认
    同时做了拆股和分红调整，目标价却是发布时的原值。口径不一致，命中率就会失真。

实验
    对 snapshot.UNIVERSE 中每只股票，用三种口径各算一次命中率：
      A  不折算拆股 + 分红调整价   （Yahoo 默认口径，最初版本的做法）
      B  折算拆股   + 分红调整价
      C  折算拆股   + 只做拆股调整（现行口径）
    样本期内从未拆股的股票是天然对照组：A 与 B 必须完全相同；
    若对照组也变了，说明折算逻辑误伤了不该动的股票。

产出
    evals/results/split_fix_eval.csv，并在终端打印表格与判定。
"""
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import scorecard  # noqa: E402
import snapshot  # noqa: E402


def main() -> int:
    rows = []
    for tk in snapshot.UNIVERSE:
        a = scorecard.fetch_analyst_track_record(tk, fix_splits=False, dividend_adjusted=True)
        b = scorecard.fetch_analyst_track_record(tk, fix_splits=True, dividend_adjusted=True)
        c = scorecard.fetch_analyst_track_record(tk, fix_splits=True, dividend_adjusted=False)
        if not (a["ok"] and b["ok"] and c["ok"]):
            print(f"{tk}: 取数失败，跳过")
            continue
        first_call = pd.Timestamp(c["span"][0])
        sp = yf.Ticker(tk).splits
        sp.index = pd.to_datetime(sp.index).tz_localize(None)
        n_splits = int((sp.index > first_call).sum())
        rows.append({
            "ticker": tk, "splits_in_window": n_splits,
            "group": "对照组" if n_splits == 0 else "拆股组",
            "A_hit_raw": round(a["hit_rate"], 1), "B_hit_split_fixed": round(b["hit_rate"], 1),
            "C_hit_current": round(c["hit_rate"], 1),
            "C_median_err": round(c["median_abs_err"], 1), "C_scored": c["n_scored"],
        })
        print(rows[-1], flush=True)

    df = pd.DataFrame(rows)
    out = ROOT / "evals" / "results"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "split_fix_eval.csv", index=False, encoding="utf-8-sig")
    print("\n" + df.to_string(index=False))

    ctrl = df[df["group"] == "对照组"]
    ok = bool((ctrl["A_hit_raw"] == ctrl["B_hit_split_fixed"]).all())
    moved = df[df["group"] == "拆股组"]
    print(f"\n对照组 {len(ctrl)} 只，折算前后命中率完全相同：{'是' if ok else '否'}")
    print(f"拆股组 {len(moved)} 只，折算后命中率平均变化 "
          f"{(moved['B_hit_split_fixed'] - moved['A_hit_raw']).mean():+.1f} 个百分点")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
