"""Non-interactive real-data test runner — bypasses plan review."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.graph import build_graph
from src.agent.state import AgentState

_STAGE_LABELS: dict[str, str] = {
    "data_track": "Stage 1a — Data Profile",
    "business_track": "Stage 1b — Business Analysis",
    "planner": "Stage 2  — Plan Generation",
    "preprocessing": "Stage 3a — Data Cleaning",
    "analysis": "Stage 3b — Analysis Execution",
    "report_gen": "Stage 4  — Report Assembly",
}

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-7s [%(name)-30s] %(message)s",
)

graph = build_graph()
state = AgentState(
    file_path="real_test/train.csv",
    user_requirement="分析Sales的驱动因素，按Region、Category、时间维度进行细分，找出高价值客户群体",
)

print("=" * 72)
print("DataInsight — Non-interactive Real Test")
print(f"Data  : {state.file_path}")
print(f"Question: {state.user_requirement}")
print("=" * 72)

seen: set[str] = set()
state_out = state.model_dump()

try:
    for chunk in graph.stream(state, stream_mode="updates"):
        for node_name in chunk:
            if node_name in _STAGE_LABELS:
                is_retry = node_name in seen
                tag = " (RETRY)" if is_retry else ""
                print(f"\n{'─' * 50}")
                print(f"  [{_STAGE_LABELS[node_name]}]{tag}")
                seen.add(node_name)

            if isinstance(chunk[node_name], dict):
                state_out = {**state_out, **chunk[node_name]}
except Exception as e:
    print(f"\n[FATAL] Pipeline failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

final_state = AgentState(**state_out)

if final_state.plan:
    print(f"\n  Plan: cleaning + {len(final_state.plan.units)} analysis unit(s)")
    for u in final_state.plan.units:
        print(f"    [{u.unit_id}] {u.purpose[:80]}...")

if final_state.analysis_result:
    ar = final_state.analysis_result
    print(f"\n  Analysis: {ar.get('status')} — "
          f"{sum(1 for r in ar.get('unit_results', []) if r.get('status') == 'success')}/"
          f"{len(ar.get('unit_results', []))} units succeeded")

report = final_state.final_report
if report:
    output_path = "real_test/train_analysis_report.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n  Report saved to: {output_path} ({len(report)} chars)")

    import os as _os
    import shutil as _shutil

    # Copy charts next to the report so embedded images resolve
    an_result = final_state.analysis_result or {}
    unit_results = an_result.get("unit_results", [])
    if unit_results:
        charts_dir = "real_test/charts"
        _os.makedirs(charts_dir, exist_ok=True)
        copied = 0
        for ur in unit_results:
            uid = ur.get("unit_id", "unknown")
            src_dir = ur.get("output_dir", "")
            if src_dir and _os.path.isdir(src_dir):
                for fname in sorted(_os.listdir(src_dir)):
                    if fname.lower().endswith(".png"):
                        _shutil.copy2(_os.path.join(src_dir, fname),
                                      _os.path.join(charts_dir, f"unit_{uid}_{fname}"))
                        copied += 1
        if copied:
            print(f"  Charts embedded: {charts_dir}/ ({copied} image(s))")

    # Save intermediates
    import json as _json
    import os as _os

    intermediates_dir = "real_test/train_intermediates"
    _os.makedirs(intermediates_dir, exist_ok=True)

    artifacts: list[tuple[str, str]] = []
    if final_state.data_profile:
        artifacts.append(("data_profile.json",
            _json.dumps(final_state.data_profile.model_dump(), ensure_ascii=False, indent=2)))
    if final_state.analysis_intent:
        artifacts.append(("analysis_intent.json",
            _json.dumps(final_state.analysis_intent.model_dump(), ensure_ascii=False, indent=2)))
    if final_state.plan:
        artifacts.append(("plan.json",
            _json.dumps(final_state.plan.model_dump(), ensure_ascii=False, indent=2)))
    if final_state.cleaning_insights:
        artifacts.append(("cleaning_insights.md", final_state.cleaning_insights))

    # Per-unit results
    for ur in final_state.analysis_result.get("unit_results", []) if final_state.analysis_result else []:
        uid = ur.get("unit_id", "unknown")
        artifacts.append((
            f"unit_{uid}_result.json",
            _json.dumps({
                "unit_id": uid, "status": ur.get("status"),
                "charts": ur.get("charts", []),
                "insights": ur.get("insights", []),
                "statistics": ur.get("statistics", {}),
                "error": ur.get("error"), "retry_count": ur.get("retry_count"),
            }, ensure_ascii=False, indent=2),
        ))
        for i, sp in enumerate(ur.get("scripts", [])):
            if _os.path.exists(sp):
                try:
                    with open(sp, encoding="utf-8") as src_f:
                        artifacts.append((f"unit_{uid}_script_{i+1}.py", src_f.read()))
                except OSError:
                    pass
        stdout = ur.get("stdout", "")
        if stdout:
            artifacts.append((f"unit_{uid}_stdout.txt", stdout))
        # Copy charts
        src_dir = ur.get("output_dir", "")
        if src_dir and _os.path.isdir(src_dir):
            charts_dir = _os.path.join(intermediates_dir, "charts")
            _os.makedirs(charts_dir, exist_ok=True)
            for fname in sorted(_os.listdir(src_dir)):
                if fname.lower().endswith(".png"):
                    _shutil.copy2(_os.path.join(src_dir, fname),
                                  _os.path.join(charts_dir, f"unit_{uid}_{fname}"))

    for filename, content in artifacts:
        filepath = _os.path.join(intermediates_dir, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(str(content))
        except OSError:
            pass

    print(f"  Intermediates saved to: {intermediates_dir}/ ({len(artifacts)} files)")
else:
    print(f"\n[FAILED] No report generated. Error: {final_state.error}")
    sys.exit(1)
