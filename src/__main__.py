"""DataInsight CLI — Progressive Data Analysis AI Agent.

Usage:
    python -m src <file_path> <requirement>
    python -m src sales.csv "Why did Q2 revenue drop by 15%?"
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from src.agent.graph import build_graph
from src.agent.state import AgentState

logger = logging.getLogger(__name__)

_REQUIREMENT_MAX_LENGTH = 2000
_FEEDBACK_MAX_LENGTH = 1000
_ALLOWED_EXTENSIONS: set[str] = {".csv", ".xlsx", ".xls"}

# Strip existing unit_N_ prefix from chart filenames to avoid double-prefixing
_RE_UNIT_PREFIX = re.compile(r"^unit\d+_")

# Prompt injection delimiters — stripped from user input
_INJECTION_DELIMITERS = re.compile(
    r"```|"
    r"---|===|"
    r"### SYSTEM|### USER|### ASSISTANT|"
    r"<\|im_start\|>|<\|im_end\|>|"
    r"<\|system\|>|<\|user\|>|<\|assistant\|>|"
    r"\[INST\]|\[/INST\]|"
    r"<<SYS>>|<</SYS>>",
    re.IGNORECASE,
)


def _sanitize_user_input(text: str, max_len: int) -> str:
    """Strip prompt injection delimiters, control characters, truncate."""
    text = _INJECTION_DELIMITERS.sub(" ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def _validate_file_path(file_path: str) -> Path:
    """Resolve, validate extension, and reject path traversal."""
    path = Path(file_path).resolve()
    ext = path.suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        print(
            f"[ERROR] Unsupported file type: {ext}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not path.exists():
        print(f"[ERROR] File not found: {path}", file=sys.stderr)
        sys.exit(1)
    cwd = Path.cwd().resolve()
    try:
        path.relative_to(cwd)
    except ValueError:
        print(f"[ERROR] File must be within current working directory: {cwd}", file=sys.stderr)
        sys.exit(1)
    return path


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

    _validate_file_path(args.file_path)


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
    if state.analysis_intent:
        artifacts.append(
            (
                "analysis_intent.json",
                _json.dumps(state.analysis_intent.model_dump(), ensure_ascii=False, indent=2),
            )
        )
    if state.plan:
        artifacts.append(
            (
                "plan.json",
                _json.dumps(state.plan.model_dump(), ensure_ascii=False, indent=2),
            )
        )
    # Per-unit analysis results
    an_result = state.analysis_result or {}
    unit_results = an_result.get("unit_results", [])
    if unit_results:
        # Summary JSON of all unit results
        summary = []
        for ur in unit_results:
            summary.append({
                "unit_id": ur.get("unit_id"),
                "status": ur.get("status"),
                "charts": ur.get("charts", []),
                "insights": ur.get("insights", []),
                "statistics": ur.get("statistics", {}),
                "error": ur.get("error"),
                "retry_count": ur.get("retry_count"),
            })
        artifacts.append(
            ("analysis_results.json", _json.dumps(summary, ensure_ascii=False, indent=2))
        )
        # Per-unit scripts and stdout
        for ur in unit_results:
            uid = ur.get("unit_id", "unknown")
            scripts = ur.get("scripts", [])
            for i, sp in enumerate(scripts):
                if os.path.exists(sp):
                    try:
                        with open(sp, encoding="utf-8") as src_f:
                            artifacts.append((f"unit_{uid}_script_{i + 1}.py", src_f.read()))
                    except OSError:
                        pass
            stdout = ur.get("stdout", "")
            if stdout:
                artifacts.append((f"unit_{uid}_stdout.txt", stdout))

    # Legacy analysis_result shape (backward compat during transition)
    if not unit_results and an_result:
        if "parsed_output" in an_result:
            artifacts.append(
                (
                    "execution_result.json",
                    _json.dumps(an_result["parsed_output"], ensure_ascii=False, indent=2),
                )
            )
        for i, attempt in enumerate(an_result.get("attempts", [])):
            code = attempt.get("code", "")
            err = attempt.get("error", "")
            content = f"# Attempt {i + 1}\n# Error: {err}\n\n{code}" if code else err
            artifacts.append((f"script_attempt_{i + 1}.py", content))
        if "script_path" in an_result:
            script_path = an_result["script_path"]
            if os.path.exists(script_path):
                try:
                    with open(script_path, encoding="utf-8") as src_f:
                        artifacts.append(("final_script.py", src_f.read()))
                except OSError:
                    pass
        if "stdout" in an_result:
            artifacts.append(("execution_stdout.txt", an_result["stdout"]))

    if state.error:
        artifacts.append(("error.txt", state.error))

    # Copy chart images from per-unit output dirs to intermediates
    import shutil as _shutil

    charts_dst_dir = os.path.join(output_dir, "charts")
    chart_count = 0
    if unit_results:
        for ur in unit_results:
            src_dir = ur.get("output_dir", "")
            if src_dir and os.path.isdir(src_dir):
                for fname in sorted(os.listdir(src_dir)):
                    if fname.lower().endswith(".png"):
                        src = os.path.join(src_dir, fname)
                        dst = os.path.join(charts_dst_dir, f"unit_{ur.get('unit_id')}_{fname}")
                        os.makedirs(charts_dst_dir, exist_ok=True)
                        try:
                            _shutil.copy2(src, dst)
                            chart_count += 1
                        except OSError:
                            pass
    else:
        # Legacy: single output_dir
        charts_src_dir = an_result.get("output_dir", "")
        if charts_src_dir and os.path.isdir(charts_src_dir):
            os.makedirs(charts_dst_dir, exist_ok=True)
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
    "planner": "Stage 2  — Plan Generation",
    "preprocessing": "Stage 3a — Data Cleaning",
    "analysis": "Stage 3b — Analysis Execution",
    "report_gen": "Stage 4  — Report Assembly",
}


def _run_graph(
    state: AgentState,
    graph: CompiledStateGraph[AgentState, Any, AgentState, AgentState],
    config: dict[str, Any] | None = None,
) -> AgentState:
    """Run the graph with streaming progress display.

    When ``config`` includes ``interrupt_before``, the graph pauses before
    the specified nodes — the caller is responsible for resuming from the
    returned state.
    """
    seen: set[str] = set()
    state_out = state.model_dump()

    stream_kwargs: dict[str, Any] = {"stream_mode": "updates"}
    if config:
        stream_kwargs["config"] = config

    for chunk in graph.stream(state, **stream_kwargs):
        for node_name in chunk:
            if node_name in _STAGE_LABELS:
                is_retry = node_name in seen
                tag = " (retry)" if is_retry else ""
                print(f"  [{_STAGE_LABELS[node_name]}]{tag}")
                seen.add(node_name)

            if isinstance(chunk[node_name], dict):
                state_out = {**state_out, **chunk[node_name]}

    return AgentState(**state_out)


def _display_plan(plan: object) -> None:
    """Display the Plan as a formatted table for user review."""
    from src.agent.state import Plan

    if not isinstance(plan, Plan):
        print("  [WARNING] No structured Plan available.")
        return

    print()
    print("=" * 72)
    print("  ANALYSIS PLAN — Review before execution")
    print("=" * 72)

    # Cleaning unit
    c = plan.cleaning
    print("\n  [Cleaning] (unit 0)")
    print(f"    Purpose : {c.purpose}")
    print(f"    Cautious: {c.cautious}")

    # Analysis units
    print(f"\n  [{len(plan.units)} Analysis Unit(s)]")
    for u in plan.units:
        model_str = u.model or "(auto)"
        fields_str = ", ".join(u.related_fields) if u.related_fields else "(未指定)"
        print(f"    [{u.unit_id}] {u.purpose}")
        print(f"         Fields  : {fields_str}")
        print(f"         Model   : {model_str}")
        print(f"         Cautious: {u.cautious}")

    # Alignment notes
    print("\n  Alignment Notes:")
    print(f"    {plan.alignment_notes}")
    print()
    print("-" * 72)
    print("  Commands: Enter = accept and run | add <purpose> | remove <id>")
    print("            modify <id> purpose|model|cautious <new value>")
    print("-" * 72)


def _handle_plan_modification(state: AgentState, command: str) -> AgentState:
    """Parse a user modification command and update the Plan in state.

    Returns updated state. On unrecognized input, prints an error and
    returns the original state unchanged.
    """
    from src.agent.state import PlanUnit

    plan = state.plan
    if plan is None:
        print("  [ERROR] No Plan to modify.")
        return state

    parts = command.strip().split(maxsplit=2)
    action = parts[0].lower() if parts else ""

    if action == "add" and len(parts) >= 2:
        purpose = parts[1]
        model = parts[2] if len(parts) > 2 else None
        new_id = max([u.unit_id for u in plan.units], default=0) + 1
        new_unit = PlanUnit(
            unit_id=new_id,
            purpose=purpose,
            model=model,
            cautious="用户手动添加",
        )
        plan.units.append(new_unit)
        print(f"  [OK] Added unit [{new_id}]: {purpose}")
        return state.model_copy(update={"plan": plan})

    if action == "remove" and len(parts) >= 2:
        try:
            target_id = int(parts[1])
        except ValueError:
            print(f"  [ERROR] Invalid unit id: {parts[1]}")
            return state
        before = len(plan.units)
        plan.units = [u for u in plan.units if u.unit_id != target_id]
        if len(plan.units) < before:
            print(f"  [OK] Removed unit [{target_id}].")
        else:
            print(f"  [ERROR] Unit [{target_id}] not found.")
        return state.model_copy(update={"plan": plan})

    if action == "modify" and len(parts) >= 3:
        try:
            target_id = int(parts[1])
        except ValueError:
            print(f"  [ERROR] Invalid unit id: {parts[1]}")
            return state
        field = parts[2].lower()
        # Value is everything after the field name, or empty
        value_start = len(parts[0]) + len(parts[1]) + len(parts[2]) + 3
        new_value = command[value_start:].strip() if len(command) > value_start else ""

        for u in plan.units:
            if u.unit_id == target_id:
                if field == "purpose":
                    u.purpose = new_value
                elif field == "model":
                    u.model = new_value if new_value else None
                elif field == "cautious":
                    u.cautious = new_value
                else:
                    print(f"  [ERROR] Unknown field: {field}. Use purpose/model/cautious.")
                    return state
                print(f"  [OK] Modified unit [{target_id}] {field}.")
                return state.model_copy(update={"plan": plan})
        print(f"  [ERROR] Unit [{target_id}] not found.")
        return state

    if action:
        print(f"  [ERROR] Unknown command: {action}. Try add/remove/modify or Enter.")
    return state


def _copy_charts_next_to_report(state: AgentState, output_path: str) -> None:
    """Copy all chart PNGs from temp dirs to a charts/ dir next to the report.

    Uses unit_{N}_{basename} naming to match what report_gen puts in the
    markdown image references.
    """
    import shutil as _shutil

    an_result = state.analysis_result or {}
    unit_results = an_result.get("unit_results", [])
    if not unit_results:
        return

    report_dir = os.path.dirname(os.path.abspath(output_path))
    charts_dir = os.path.join(report_dir, "charts")
    copied = 0

    for ur in unit_results:
        uid = ur.get("unit_id", "unknown")
        src_dir = ur.get("output_dir", "")
        if not src_dir or not os.path.isdir(src_dir):
            continue
        for fname in sorted(os.listdir(src_dir)):
            if fname.lower().endswith(".png"):
                src = os.path.join(src_dir, fname)
                clean = _RE_UNIT_PREFIX.sub("", fname)
                dst = os.path.join(charts_dir, f"unit_{uid}_{clean}")
                os.makedirs(charts_dir, exist_ok=True)
                try:
                    _shutil.copy2(src, dst)
                    copied += 1
                except OSError:
                    pass

    if copied:
        print(f"  Charts embedded: {charts_dir}/ ({copied} image(s))")


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
        user_requirement=_sanitize_user_input(args.requirement, _REQUIREMENT_MAX_LENGTH),
    )

    print(f"\nDataInsight analyzing: {args.file_path}")
    print(f"Requirement: {args.requirement}")
    print("Running 4-stage pipeline...\n")

    # ── Phase 1: Plan (data_track → business_track → planner, pause before preprocessing) ──
    thread_config: dict[str, Any] = {"configurable": {"thread_id": "main"}}
    try:
        state = _run_graph(
            state, graph, config={**thread_config, "interrupt_before": ["preprocessing"]}
        )
    except Exception as e:
        print(f"\n[FATAL] Pipeline failed during planning: {e}", file=sys.stderr)
        sys.exit(1)

    # ── Plan Review ──
    if state.plan and not state.error:
        _display_plan(state.plan)

        while True:
            try:
                command = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not command:
                break

            state = _handle_plan_modification(state, command)

        if state.feedback:
            # Plan was modified — re-run planner_node with accumulated feedback
            from src.agent.nodes.planner import planner_node

            print("\n  Re-validating plan with modifications...")
            planner_update = planner_node(state)
            state = AgentState(**(state.model_dump() | planner_update))

    # ── Phase 2: Execute (preprocessing → analysis → report_gen) ──
    if state.plan and not state.error:
        print("\n  ── Executing plan ──\n")
        try:
            state = _run_graph(state, graph, config=thread_config)
        except Exception as e:
            print(f"\n[FATAL] Pipeline failed during execution: {e}", file=sys.stderr)
            sys.exit(1)
    elif state.error:
        print(f"\n[WARNING] Plan generation failed: {state.error}")

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

    # Always copy charts next to the report so embedded images resolve
    _copy_charts_next_to_report(state, output_path)

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
        sanitized = _sanitize_user_input(feedback, _FEEDBACK_MAX_LENGTH)
        state = state.model_copy(update={"feedback": sanitized})

        try:
            state = _run_graph(state, graph, config=thread_config)
        except Exception as e:
            print(f"\n[FATAL] Iteration failed: {e}", file=sys.stderr)
            sys.exit(1)

        report = state.final_report
        if report:
            _print_report(report)
            revised_path = output_path.replace(".md", "_revised.md")
            try:
                with open(revised_path, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"\nRevised report saved to: {revised_path}")
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
