from __future__ import annotations

import ast
import re

# ---------------------------------------------------------------------------
# Regex patterns — catch dangerous calls regardless of import method
# ---------------------------------------------------------------------------
_BANNED_PATTERNS: list[str] = [
    # Network exfiltration
    r"requests\.",
    r"urllib",
    r"socket\.",
    r"http\.client",
    r"http\.server",
    r"ftplib\.",
    r"telnetlib\.",
    r"smtplib\.",
    r"imaplib\.",
    r"poplib\.",
    # Subprocess / shell execution
    r"subprocess\.",
    r"os\.system\(",
    r"os\.popen\(",
    r"os\.exec",
    r"os\.spawn",
    # File system destruction
    r"os\.remove\(",
    r"os\.unlink\(",
    r"os\.rmdir\(",
    r"os\.removedirs\(",
    r"shutil\.rmtree",
    r"shutil\.move\(",
    r"shutil\.copy",
    r"\.unlink\(",          # pathlib.Path(...).unlink()
    r"os\.chmod\(",
    r"os\.chown\(",
    # Arbitrary code execution
    r"\beval\(",
    r"\bexec\(",
    r"\bcompile\(",
    r"__import__\(",
    # Unsafe serialization
    r"ctypes\.",
    r"pickle\.",
    r"marshal\.",
]

# ---------------------------------------------------------------------------
# Import names — AST-level exact match
# ---------------------------------------------------------------------------
_BANNED_IMPORTS: set[str] = {
    # Network
    "requests",
    "urllib",
    "urllib.request",
    "urllib.error",
    "http",
    "http.client",
    "http.server",
    "ftplib",
    "telnetlib",
    "smtplib",
    "imaplib",
    "poplib",
    "socket",
    "ssl",
    "websockets",
    "aiohttp",
    # Process / execution
    "subprocess",
    "os",
    "shutil",
    "pty",
    "signal",
    # Serialization
    "pickle",
    "marshal",
    "shelve",
    # C extensions / arbitrary code
    "ctypes",
    "code",
    "codeop",
    "importlib",
}


class _ImportScanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name in _BANNED_IMPORTS:
                self.violations.append(f"banned import: {alias.name}")
            # Also check top-level package of dotted imports
            top = alias.name.split(".")[0]
            if top in _BANNED_IMPORTS and top != alias.name:
                self.violations.append(f"banned import: {alias.name} (top-level: {top})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module and node.module in _BANNED_IMPORTS:
            self.violations.append(f"banned import from: {node.module}")
        if node.module:
            top = node.module.split(".")[0]
            if top in _BANNED_IMPORTS and top != node.module:
                self.violations.append(f"banned import from: {node.module} (top-level: {top})")
        self.generic_visit(node)


def check_static(code: str) -> tuple[bool, str]:
    """Scan LLM-generated code for dangerous constructs before execution.

    Returns (True, "") if safe, (False, reason) if rejected.
    """
    # Layer 1 — AST import scan
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Code has syntax error (refusing to execute): {e}"

    scanner = _ImportScanner()
    scanner.visit(tree)
    if scanner.violations:
        return False, "Banned imports: " + "; ".join(scanner.violations)

    # Layer 2 — Regex pattern scan (catches eval, __import__, dynamic calls)
    for pattern in _BANNED_PATTERNS:
        if re.search(pattern, code):
            return False, f"Banned pattern: {pattern}"

    return True, ""
