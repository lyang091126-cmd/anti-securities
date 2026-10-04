# -*- coding: utf-8 -*-
"""扫描"函数/模块名被后续赋值污染"的全部冲突点（V8 战役一根因定位）。"""
import ast
from pathlib import Path

P = Path(__file__).resolve().parent / "Anti Securities Report.py"
src = P.read_text(encoding="utf-8")
tree = ast.parse(src)

# 1) 收集所有顶层 def 名 与 import 绑定名
func_names, import_names = {}, {}
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        func_names.setdefault(n.name, n.lineno)
    elif isinstance(n, ast.Import):
        for a in n.names:
            import_names.setdefault(a.asname or a.name.split(".")[0], n.lineno)
    elif isinstance(n, ast.ImportFrom):
        for a in n.names:
            import_names.setdefault(a.asname or a.name, n.lineno)

# 2) 找出任意位置（含 with/if/for 内部）对这些名字的赋值 -> 变量污染
print("=== 函数名被赋值覆盖（'str' object is not callable 类崩溃根因）===")
hits = 0
for n in ast.walk(tree):
    targets = []
    if isinstance(n, ast.Assign):
        targets = n.targets
    elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
        targets = [n.target]
    for t in targets:
        if isinstance(t, ast.Name) and t.id in func_names:
            print(f"  L{n.lineno}: '{t.id}' 被赋值覆盖（函数定义于 L{func_names[t.id]}）")
            hits += 1
if not hits:
    print("  无")

# 3) datetime 绑定冲突：同一文件里 import datetime 与 from datetime import datetime 并存
print("\n=== datetime 绑定方式冲突（'module datetime has no attribute now' 根因）===")
mod_style, from_style = [], []
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        for a in n.names:
            if a.name == "datetime" and not a.asname:
                mod_style.append(n.lineno)
    elif isinstance(n, ast.ImportFrom) and n.module == "datetime":
        for a in n.names:
            if a.name == "datetime":
                from_style.append(n.lineno)
print(f"  import datetime          -> 行 {mod_style}")
print(f"  from datetime import ... -> 行 {from_style}")
if mod_style and from_style:
    print("  [!!] 两种绑定并存，后出现者覆盖前者，裸用 datetime.now()/timedelta() 必崩")

# 4) 定位裸用 datetime.now( / timedelta( / datetime( 的行（需改成 datetime.datetime.*）
print("\n=== 需要改写的裸调用位置 ===")
for i, line in enumerate(src.splitlines(), 1):
    s = line.strip()
    if s.startswith("#"):
        continue
    for pat in ("datetime.now(", "timedelta(", "datetime.strptime("):
        if pat in line and f"datetime.{pat}" not in line and f"_dt.{pat}" not in line:
            print(f"  L{i}: {s[:110]}")
            break
