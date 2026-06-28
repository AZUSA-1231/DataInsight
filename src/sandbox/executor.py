from __future__ import annotations

import subprocess
import sys
from typing import NamedTuple


class SandboxResult(NamedTuple):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


DEFAULT_TIMEOUT = 120


def run_script(
    script_path: str,
    args: list[str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> SandboxResult:
    """Execute a Python script in a subprocess sandbox.

    Args:
        script_path: Absolute or relative path to the Python script.
        args: Positional arguments passed to the script.
        timeout_seconds: Max wall-clock seconds before the process is killed.

    Returns:
        SandboxResult with captured stdout, stderr, exit code, and timeout flag.
    """
    cmd = [sys.executable, script_path]
    if args:
        cmd.extend(args)

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
        return SandboxResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return SandboxResult(
            stdout=stdout,
            stderr=stderr
            + f"\n[Sandbox] Process timed out after {timeout_seconds}s",
            exit_code=-1,
            timed_out=True,
        )
