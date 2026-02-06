from __future__ import annotations

import py_compile


def test_py_compile_entrypoints():
    py_compile.compile('assistant.py', doraise=True)
    py_compile.compile('gpbt.py', doraise=True)

