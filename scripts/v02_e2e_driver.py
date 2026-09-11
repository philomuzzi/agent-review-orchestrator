"""V0.2 real-agent E2E driver.

Real Pi + real Codex + real renderer. Only the Human gate keystrokes
are constants (ScriptedUI); everything else is a live run, reusing the
CLI's Windows stdio hardening exactly like the V0.1 E2E drivers.

usage:
  python v02_e2e_driver.py <repo> <request> <answers-file> [--kind K]
  python v02_e2e_driver.py --resume <repo> <session-id> <answers-file>
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


def report(o) -> int:
    code = o.run()
    state = o.state
    print("\n===== E2E SUMMARY =====")
    print("exit_code:", code)
    print("session:", state.session_id)
    print("phase:", state.phase.value, "status:", state.status.value)
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
            "category": g.category.value,
            "status": g.status.value,
            "answers": len(g.answers),
            "source_issue_ids": g.source_issue_ids,
        }
        for g in gates
    ])
    issues = o.store.load_issues().issues
    print("issues:", [
        {"id": i.id, "cat": i.category.value, "sev": i.severity.value,
         "status": i.status.value, "covered_by": i.covered_by_decisions}
        for i in issues
    ])
    key_events = []
    for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["event"] in (
            "ISSUE_NEED_HUMAN", "ISSUE_HUMAN_AUTHORITY_CHECK_STARTED",
            "ISSUE_COVERED_BY_DECISION", "CONVERGENCE_GATE_CREATED",
            "CUSTOM_DECISION_CAPTURED", "HUMAN_GATE_CREATED",
            "HUMAN_GATE_CLOSED", "SESSION_HUMAN_HANDOFF", "HANDOFF_WRITTEN",
            "SESSION_DONE", "TASK_REVISION_INCREMENTED",
        ):
            key_events.append({k: v for k, v in e.items() if k != "ts"})
    print("key_events:", json.dumps(key_events, ensure_ascii=False, indent=1))
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
