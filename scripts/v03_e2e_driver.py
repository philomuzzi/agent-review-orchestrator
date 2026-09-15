"""V0.3 real-agent E2E driver (bounded real validation).

Same skeleton as the V0.2 driver (real Pi + real Codex + real renderer;
only gate keystrokes scripted) with a V0.3 summary: scope verdict,
result classification, correction routing and terminal artifacts.

usage:
  python v03_e2e_driver.py <repo> <request> <answers-file> [--kind K]
  python v03_e2e_driver.py --resume <repo> <session-id> <answers-file>
Answers file: one answer per line (UTF-8), consumed in order by the gate
("0" selects custom mode; the next line is the custom decision text).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent_review.cli import _guard_console_output, _harness_windows_stdio

_harness_windows_stdio()
_guard_console_output()

from agent_review.config import load_config
from agent_review.orchestrator import Orchestrator
from agent_review.progress import OutputLevel, ProgressRenderer


class ScriptedUI:
    """Real terminal echo; scripted human keystrokes only."""

    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.log: list[str] = []

    def is_interactive(self) -> bool:
        return True

    def echo(self, text: str) -> None:
        print(text, flush=True)

    def ask(self, prompt: str) -> str:
        answer = self.answers.pop(0) if self.answers else ""
        self.log.append(f"{prompt}{answer}")
        print(f"{prompt}{answer}", flush=True)
        return answer


V03_KEY_EVENTS = (
    "SCOPE_GUARD_STARTED",
    "SCOPE_GUARD_COMPLETED",
    "SCOPE_GUARD_STOPPED",
    "HUMAN_GATE_CREATED",
    "HUMAN_GATE_CLOSED",
    "ISSUE_NEED_HUMAN",
    "ISSUE_HUMAN_AUTHORITY_CHECK_STARTED",
    "ISSUE_COVERED_BY_DECISION",
    "CONVERGENCE_GATE_CREATED",
    "CORRECTION_ROUTED",
    "FOCUSED_REVISION_STARTED",
    "FOCUSED_REVISION_COMPLETED",
    "ABLATION_TRIGGERED",
    "NO_MATERIAL_PROGRESS_STOP",
    "CORRECTION_STOPPED",
    "SESSION_DONE",
    "SESSION_HUMAN_HANDOFF",
    "SESSION_RESULT_WRITTEN",
    "TELEMETRY_WRITTEN",
    "HANDOFF_WRITTEN",
    "TASK_REVISION_INCREMENTED",
)


def report(o) -> int:
    code = o.run()
    state = o.state
    print("\n===== V0.3 E2E SUMMARY =====")
    print("exit_code:", code)
    print("session:", state.session_id)
    print("phase:", state.phase.value, "status:", state.status.value)
    print("result_status:", state.result_status)
    print("scope_verdict:", state.scope_verdict)
    print("task_revision:", state.task_revision)
    print("budgets:", state.budgets.model_dump())
    print("handoff_reason:", state.handoff_reason)
    decisions = o.store.load_decisions().decisions
    print("decisions:", [
        {
            "id": d.decision_id,
            "key": d.decision_key,
            "source": d.source.value,
            "option": d.selected_option_key,
            "text": d.answer_text[:60],
            "status": d.status.value,
        }
        for d in decisions
    ])
    gates = o.store.load_gate_log().gates
    print("gates:", [
        {
            "id": g.gate_id,
            "questions": len(g.questions),
            "status": g.status.value,
            "source_issue_ids": g.source_issue_ids,
        }
        for g in gates
    ])
    issues = o.store.load_issues().issues
    print("issues:", [
        {"id": i.id, "cat": i.category.value, "sev": i.severity.value,
         "status": i.status.value, "correction": i.correction_action.value if i.correction_action else None,
         "origin": i.origin.value if i.origin else None,
         "covered_by": i.covered_by_decisions}
        for i in issues
    ])
    key_events = []
    for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["event"] in V03_KEY_EVENTS:
            key_events.append({k: v for k, v in e.items() if k != "ts"})
    print("key_events:", json.dumps(key_events, ensure_ascii=False, indent=1))
    telemetry = o.store.dir / "telemetry.json"
    if telemetry.is_file():
        print("telemetry:", telemetry.read_text(encoding="utf-8").strip())
    result_md = o.store.dir / "session-result.md"
    print("session_result_exists:", result_md.is_file())
    return code


def resume_main(argv) -> int:
    """usage: ... --resume <repo> <session-id> <answers-file>"""
    repo = Path(argv[0]).resolve()
    session_id = argv[1]
    answers = [
        line.rstrip("\n")
        for line in Path(argv[2]).read_text(encoding="utf-8").splitlines()
    ]
    config = load_config()
    renderer = ProgressRenderer(
        level=OutputLevel.DEFAULT, heartbeat_interval=config.progress.heartbeat_seconds
    )
    o = Orchestrator.resume(
        repository=repo,
        session_id=session_id,
        config=config,
        ui=ScriptedUI(answers),
        renderer=renderer,
    )
    return report(o)


def main() -> int:
    if sys.argv[1] == "--resume":
        return resume_main(sys.argv[2:])
    repo = Path(sys.argv[1]).resolve()
    request = sys.argv[2]
    answers_path = Path(sys.argv[3])
    kind = None
    if "--kind" in sys.argv:
        kind = sys.argv[sys.argv.index("--kind") + 1]
    answers = [
        line.rstrip("\n")
        for line in answers_path.read_text(encoding="utf-8").splitlines()
    ]

    config = load_config()
    renderer = ProgressRenderer(
        level=OutputLevel.DEFAULT, heartbeat_interval=config.progress.heartbeat_seconds
    )
    o = Orchestrator.create(
        repository=repo,
        request=request,
        task_kind_explicit=kind,
        config=config,
        ui=ScriptedUI(answers),
        renderer=renderer,
    )
    return report(o)


if __name__ == "__main__":
    sys.exit(main())
