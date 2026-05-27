"""代码语言推断 _detect_code_language 单元测试。"""

import pytest

from src.services.chunking_service import ChunkingService


@pytest.mark.unit
def test_empty_text() -> None:
    assert ChunkingService._detect_code_language("") == ""


@pytest.mark.unit
def test_fence_python() -> None:
    code = "```python\ndef foo():\n    pass\n```"
    assert ChunkingService._detect_code_language(code) == "Python"


@pytest.mark.unit
def test_fence_javascript() -> None:
    code = "```javascript\nfunction foo() {\n    return 1;\n}\n```"
    assert ChunkingService._detect_code_language(code) == "Javascript"


@pytest.mark.unit
def test_fence_sh_to_shell() -> None:
    code = "```sh\necho hello\n```"
    assert ChunkingService._detect_code_language(code) == "Shell"


@pytest.mark.unit
def test_fence_plain_ignored() -> None:
    code = "```text\njust text\n```"
    assert ChunkingService._detect_code_language(code) == ""


@pytest.mark.unit
def test_shebang_python() -> None:
    code = "#!/usr/bin/env python\nprint('hello')"
    assert ChunkingService._detect_code_language(code) == "Python"


@pytest.mark.unit
def test_shebang_bash() -> None:
    code = "#!/bin/bash\necho hello"
    assert ChunkingService._detect_code_language(code) == "Shell"


@pytest.mark.unit
def test_fingerprint_python() -> None:
    code = "\n".join([
        "import os",
        "class MyClass:",
        "    def __init__(self):",
        "        self.x = 1",
    ])
    assert ChunkingService._detect_code_language(code) == "Python"


@pytest.mark.unit
def test_fingerprint_go() -> None:
    code = "\n".join([
        "package main",
        "import (",
        '    "fmt"',
        ")",
        "func main() {",
        '    fmt.Println("hello")',
        "}",
    ])
    assert ChunkingService._detect_code_language(code) == "Go"


@pytest.mark.unit
def test_fingerprint_sql() -> None:
    code = "SELECT * FROM users WHERE id = 1;"
    assert ChunkingService._detect_code_language(code) == "SQL"


@pytest.mark.unit
def test_fingerprint_rust() -> None:
    code = "\n".join([
        "fn main() {",
        "    let mut x = 1;",
        "    println!(\"hello\");",
        "}",
    ])
    assert ChunkingService._detect_code_language(code) == "Rust"


@pytest.mark.unit
def test_fingerprint_html() -> None:
    code = "<!DOCTYPE html>\n<html>\n<div class=\"main\">\n<script src=\"app.js\"></script>\n</html>"
    assert ChunkingService._detect_code_language(code) == "HTML"


@pytest.mark.unit
def test_unknown_language() -> None:
    code = "xyzzy plugh\nThis is not real code."
    assert ChunkingService._detect_code_language(code) == ""
