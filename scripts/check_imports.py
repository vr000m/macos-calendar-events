"""R14 helper for check_readonly.sh: PyObjC may be imported only by the adapter.

Usage: python -I scripts/check_imports.py <src-dir> <adapter-file>

Imports are found by parsing each ``*.py`` file under ``src-dir`` with ``ast``, so every
spelling counts: ``import os, EventKit``, ``x = 1; import objc``, backslash continuations,
submodules (``import Foundation.NSDate``), ``from AppKit import ...``, and
``__import__("EventKit")`` / ``importlib.import_module("EventKit")`` with a literal name.
Only ``adapter-file`` is exempt. Relative imports (``from . import x``) are local modules.

Exit: 0 clean, 1 PyObjC imported elsewhere (one ``path:line: source`` line each),
2 a file can't be read or parsed (it was not checked, so it can't pass).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BANNED = frozenset({"EventKit", "Foundation", "AppKit", "objc"})


def _banned(name: object) -> bool:
    return isinstance(name, str) and name.split(".")[0] in BANNED


def _dynamic_name(call: ast.Call) -> object:
    func = call.func
    named = isinstance(func, ast.Name) and func.id in ("__import__", "import_module")
    if not (named or (isinstance(func, ast.Attribute) and func.attr == "import_module")):
        return None
    if call.args and isinstance(call.args[0], ast.Constant):
        return call.args[0].value
    return None


def _imported_names(node: ast.AST) -> list[object]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        return [node.module]
    if isinstance(node, ast.Call):
        return [_dynamic_name(node)]
    return []


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_imports.py <src-dir> <adapter-file>", file=sys.stderr)
        return 2
    src, adapter = Path(argv[0]), Path(argv[1]).resolve()
    hits: list[str] = []
    errors: list[str] = []
    for path in sorted(src.rglob("*.py")):
        if path.resolve() == adapter:
            continue
        try:
            text = path.read_bytes().decode("utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError, ValueError) as exc:
            errors.append(f"{path}: cannot be parsed ({type(exc).__name__})")
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if any(_banned(name) for name in _imported_names(node)):
                lineno = getattr(node, "lineno", 0)
                hits.append(f"{path}:{lineno}: {lines[lineno - 1].strip()}")
    for line in errors + hits:
        print(line)
    return 2 if errors else 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
