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
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from src.agent.graph import build_graph
from src.agent.state import AgentState

logger = logging.getLogger(__name__)


def _check_prerequisites(args: argparse.Namespace) -> None:
    """Fail fast with a clear message before invoking the expensive graph."""
    from src.agent.llm import _load_dotenv

    _load_dotenv()

    missing = []
    for var in ("DATAINSIGHT_LLM_MODEL", "DATAINSIGHT_LLM_API_KEY", "DATAINSIGHT_LLM_BASE_URL"):
        if not os.environ.get(var):
            missing.append(var)

    if missing:
        env_file = Path(".env")
        if not env_file.exists():
            print(
                f"[ERROR] Missing configuration: {', '.join(missing)}\n"
                f"\n  No .env file found. Create one by copying the template:\n"
                f"    copy .env.example .env\n"
                f"  Then edit .env with your API key and model settings.",
                file=sys.stderr,
            )
        else:
            print(
                f"[ERROR] .env file exists but missing: {', '.join(missing)}\n"
                f"  Edit .env and add the missing values.",
                file=sys.stderr,
            )
        sys.exit(1)

    print(f"  LLM model : {os.environ['DATAINSIGHT_LLM_MODEL']}")
    print(f"  Base URL  : {os.environ['DATAINSIGHT_LLM_BASE_URL']}")
    if Path(".env").exists():
        print("  Config    : .env file")
    print()

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
    parser.add_argument(
        "--save-intermediates",
        "-s",
        action="store_true",
        help="Save all intermediate artifacts (audit reports, generated scripts, etc.)",
    )
    return parser


def _print_report(report: str) -> None:
    print()
    print("=" * 72)
    print(report)
    print("=" * 72)


def _save_intermediates(state: AgentState, output_dir: str) -> None:
    """Save all intermediate artifacts to a directory for inspection."""
    import json as _json

    os.makedirs(output_dir, exist_ok=True)

    artifacts: list[tuple[str, str]] = []

    if state.data_profile:
        artifacts.append(
            (
                "data_profile.json",
                _json.dumps(state.data_profile.model_dump(), ensure_ascii=False, indent=2),
            )
        )
    if state.cleaning_insights:
        artifacts.append(("cleaning_insights.md", state.cleaning_insights))
    if state.analysis_intent:
        artifacts.append(
            (
                "analysis_intent.json",
                _json.dumps(state.analysis_intent.model_dump(), ensure_ascii=False, indent=2),
            )
        )
    if state.execution_plan:
        artifacts.append(
            (
                "execution_plan.json",
                _json.dumps(state.execution_plan.model_dump(), ensure_ascii=False, indent=2),
            )
        )

    exec_result = state.execution_result or {}
    if exec_result:
        if "parsed_output" in exec_result:
            artifacts.append(
                (
                    "execution_result.json",
                    _json.dumps(exec_result["parsed_output"], ensure_ascii=False, indent=2),
                )
            )
        for i, attempt in enumerate(exec_result.get("attempts", [])):
            code = attempt.get("code", "")
            err = attempt.get("error", "")
            content = f"# Attempt {i + 1}\n# Error: {err}\n\n{code}" if code else err
            artifacts.append((f"script_attempt_{i + 1}.py", content))
        if "script_path" in exec_result:
            script_path = exec_result["script_path"]
            if os.path.exists(script_path):
                try:
                    with open(script_path, encoding="utf-8") as src_f:
                        artifacts.append(("final_script.py", src_f.read()))
                except OSError:
                    pass
        if "stdout" in exec_result:
            artifacts.append(("execution_stdout.txt", exec_result["stdout"]))

    if state.error:
        artifacts.append(("error.txt", state.error))

    # Copy chart images from sandbox output_dir to intermediates
    charts_src_dir = exec_result.get("output_dir", "")
    if charts_src_dir and os.path.isdir(charts_src_dir):
        import shutil as _shutil

        charts_dst_dir = os.path.join(output_dir, "charts")
        os.makedirs(charts_dst_dir, exist_ok=True)
        chart_count = 0
        for fname in sorted(os.listdir(charts_src_dir)):
            if fname.lower().endswith(".png"):
                src = os.path.join(charts_src_dir, fname)
                dst = os.path.join(charts_dst_dir, fname)
                try:
                    _shutil.copy2(src, dst)
                    chart_count += 1
                except OSError:
                    pass
        if chart_count:
            print(f"  Charts saved to: {charts_dst_dir}/ ({chart_count} image(s))")

    for filename, content in artifacts:
        filepath = os.path.join(output_dir, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(str(content))
        except OSError as e:
            print(f"  [WARNING] Could not save {filename}: {e}", file=sys.stderr)

    print(f"\nIntermediate artifacts saved to: {output_dir}/")
    for filename, _ in artifacts:
        print(f"  - {filename}")


_STAGE_LABELS: dict[str, str] = {
    "data_track": "Stage 1a — Data Profile",
    "business_track": "Stage 1b — Business Analysis",
    "decision_match": "Stage 2  — Data-Business Alignment",
    "execution": "Stage 3  — Sandbox Execution",
    "report_gen": "Stage 4  — Report Assembly",
}


def _run_graph(
    state: AgentState, graph: CompiledStateGraph[AgentState, Any, AgentState, AgentState]
) -> AgentState:
    """Run the graph with streaming progress display."""
    seen: set[str] = set()
    state_out = state.model_dump()

    for chunk in graph.stream(state, stream_mode="updates"):
        for node_name in chunk:
            if node_name in _STAGE_LABELS:
                is_retry = node_name in seen
                tag = " (retry)" if is_retry else ""
                print(f"  [{_STAGE_LABELS[node_name]}]{tag}")
                seen.add(node_name)

            if isinstance(chunk[node_name], dict):
                state_out = {**state_out, **chunk[node_name]}

    return AgentState(**state_out)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    _check_prerequisites(args)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    output_path = args.output or f"{args.file_path.rsplit('.', 1)[0]}_analysis_report.md"

    graph = build_graph()

    state = AgentState(
        file_path=args.file_path,
        user_requirement=args.requirement,
    )

    print(f"\nDataInsight analyzing: {args.file_path}")
    print(f"Requirement: {args.requirement}")
    print("Running 4-stage pipeline...\n")

    # First run
    try:
        state = _run_graph(state, graph)
    except Exception as e:
        print(f"\n[FATAL] Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)

    report = state.final_report
    if report:
        _print_report(report)
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\nReport saved to: {output_path}")
        except OSError as e:
            print(f"\n[WARNING] Could not save report: {e}", file=sys.stderr)
    else:
        error = state.error or "Unknown error"
        print(f"\n[ERROR] Report generation failed: {error}", file=sys.stderr)

    if args.save_intermediates:
        intermediates_dir = output_path.replace(".md", "_intermediates")
        _save_intermediates(state, intermediates_dir)

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
        state = state.model_copy(update={"feedback": feedback})

        try:
            state = _run_graph(state, graph)
        except Exception as e:
            print(f"\n[FATAL] Iteration failed: {e}", file=sys.stderr)
            sys.exit(1)

        report = state.final_report
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
            error = state.error or "Unknown error"
            print(f"\n[ERROR] Report revision failed: {error}", file=sys.stderr)

        if args.save_intermediates:
            intermediates_dir = output_path.replace(".md", "_intermediates")
            _save_intermediates(state, intermediates_dir)


if __name__ == "__main__":
    main()
