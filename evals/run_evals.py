"""evals/run_evals.py · 运行全部离线单元测试

用法（项目根目录）
    python evals/run_evals.py

依次加载 evals/test_*.py，执行其中每个 test_ 开头的函数，打印通过 / 失败。
不依赖 pytest；每个测试文件都重新加载项目模块，避免前一个文件的替身数据影响后一个。
联网的评测（eval_*.py）单独运行，见 evals/README.md。
"""
import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))


def main() -> int:
    passed = failed = 0
    for f in sorted(HERE.glob("test_*.py")):
        for name in ("scorecard", "llm_cost", "snapshot", "report_prompt"):
            if name in sys.modules:
                importlib.reload(sys.modules[name])
        mod = importlib.import_module(f.stem)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            try:
                getattr(mod, name)()
                passed += 1
                print(f"PASS  {f.stem}.{name}")
            except Exception:
                failed += 1
                print(f"FAIL  {f.stem}.{name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
