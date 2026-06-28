"""DataInsight CLI — Progressive Data Analysis AI Agent.

Usage:
    python -m src <file_path> <requirement>
    python -m src sales.csv "Why did Q2 revenue drop by 15%?"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import cast

from src.agent.graph import build_graph
from src.agent.state import AgentState

logger = logging.getLogger(__name__)

_REQUIRED_ENV_VARS = ["DATAINSIGHT_LLM_MODEL", "DATAINSIGHT_LLM_API_KEY"]


def _check_prerequisites(args: argparse.Namespace) -> None:
    """Fail fast with a clear message before invoking the expensive graph."""
    missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        print(
            f"[ERROR] Missing environment variables: {', '.join(missing)}\n"
            f"  Set them before running:\n"
            f"    export DATAINSIGHT_LLM_MODEL=\"gpt-4o\"\n"
            f"    export DATAINSIGHT_LLM_API_KEY=\"sk-...\"\n"
            f"  Or for other providers:\n"
            f"    export DATAINSIGHT_LLM_BASE_URL=\"https://api.deepseek.com/v1\"",
            file=sys.stderr,
        )
        sys.exit(1)

    if not Path(args.file_path).exists():
        print(f"[ERROR] File not found: {args.file_path}", file=sys.stderr)
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datainsight",
        description="DataInsight — Progressive Data Analysis AI Agent",
    )
    parser.add_argument(
        "file_path",
        help="Path to a CSV or Excel (.xlsx/.xls) file",
    )
    parser.add_argument(
        "requirement",
        help="Natural-language analysis requirement (e.g. 'Why did Q2 sales drop?')",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output Markdown file path (default: <input>_analysis_report.md)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def _print_report(report: str) -> None:
    print()
    print("=" * 72)
    print(report)
    print("=" * 72)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    _check_prerequisites(args)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    output_path = args.output or f"{args.file_path.rsplit('.', 1)[0]}_analysis_report.md"

    graph = build_graph()

    state: AgentState = {
        "file_path": args.file_path,
        "user_requirement": args.requirement,
    }

    print(f"\nDataInsight analyzing: {args.file_path}")
    print(f"Requirement: {args.requirement}")
    print("Running 4-stage pipeline...\n")

    # First run
    try:
        result = graph.invoke(state)
        state = cast(AgentState, result)
    except Exception as e:
        print(f"\n[FATAL] Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)

    report = state.get("final_report", "")
    if report:
        _print_report(report)
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\nReport saved to: {output_path}")
        except OSError as e:
            print(f"\n[WARNING] Could not save report: {e}", file=sys.stderr)
    else:
        error = state.get("error", "Unknown error")
        print(f"\n[ERROR] Report generation failed: {error}", file=sys.stderr)

    # In-session iteration loop
    while True:
        print()
        try:
            feedback = input("Feedback (Enter to exit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not feedback:
            break

        print("Revising analysis based on feedback...\n")
        state["feedback"] = feedback

        try:
            result = graph.invoke(state)
            state = cast(AgentState, result)
        except Exception as e:
            print(f"\n[FATAL] Iteration failed: {e}", file=sys.stderr)
            sys.exit(1)

        report = state.get("final_report", "")
        if report:
            _print_report(report)
            output_path = output_path.replace(".md", "_revised.md")
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"\nRevised report saved to: {output_path}")
            except OSError as e:
                print(f"\n[WARNING] Could not save report: {e}", file=sys.stderr)
        else:
            error = state.get("error", "Unknown error")
            print(f"\n[ERROR] Report revision failed: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
