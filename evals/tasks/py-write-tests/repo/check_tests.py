import ast, pathlib, sys
p = pathlib.Path("test_stats.py")
if not p.exists():
    sys.exit("test_stats.py missing")
tree = ast.parse(p.read_text())
tests = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]
src = p.read_text()
ok = len(tests) >= 3 and "median" in src and "mean" in src and ("assertRaises" in src or "raises" in src)
sys.exit(0 if ok else f"only {len(tests)} tests / missing coverage")
