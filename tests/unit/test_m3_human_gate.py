"""M3 acceptance: Human Gate protocol, decisions, task revision, budgets."""

from __future__ import annotations

import json

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.config import Config
from agent_review.models import (
    ExitCode,
    GateStatus,
    IssueSeverity,
    Phase,
    SessionStatus,
)
from agent_review.orchestrator import Orchestrator


class ScriptedUI:
    def __init__(self, answers: list[str] | None = None, interactive: bool = True):
        self.answers = list(answers or [])
        self.interactive = interactive
        self.prompts: list[str] = []

    def is_interactive(self) -> bool:
        return self.interactive

    def echo(self, text: str) -> None:
        self.prompts.append(text)

    def ask(self, prompt: str) -> str:
        if not self.answers:
            return ""
        return self.answers.pop(0)


def candidate(
    category="REQUIREMENT",
    question="Which pause semantics are required?",
    options=None,
    recommendation=None,
):
    return {
        "category": category,
        "question": question,
        "why": "Business semantics only the user can decide.",
        "options": (
            options
            if options is not None
            else [
                {"key": "cooperative", "label": "Cooperative pause between steps", "impact": "Safe, slight delay"},
                {"key": "immediate", "label": "Immediate abort of current step", "impact": "Fast, may lose in-flight work"},
            ]
        ),
        "recommendation": recommendation,
        "source": "DISCOVER",
    }


def discovery_with_candidates(candidates, task_kind="CHANGE"):
    return json.dumps(
        {
            "task_kind": task_kind,
            "current_state": "sync task runs to completion",
            "relevant_components": ["src/sync.py"],
            "existing_constraints": ["keep public API"],
            "change_surface": ["src/sync.py"],
            "unknowns": [],
            "human_candidates": candidates,
        }
    )


def make_orchestrator(repo, pi=None, codex=None, ui=None, kind=None):
    return Orchestrator.create(
        repository=repo,
        request="给同步任务增加暂停能力",
        task_kind_explicit=kind,
        config=Config(),
        pi=pi or FakePiAdapter(),
        codex=codex or FakeCodexAdapter(),
        ui=ui or ScriptedUI(interactive=False),
    )


# --- Scenario 6: Requirement Human Gate -------------------------------------


def test_scenario_6_requirement_gate_flow(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    ui = ScriptedUI(answers=["1"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    code = o.run()
    assert code == int(ExitCode.DONE)
    assert o.state.task_revision == 2  # decision changed design basis
    decisions = o.store.load_decisions().decisions
    assert len(decisions) == 1
    assert decisions[0].status.value == "ACTIVE"
    assert decisions[0].selected_option_key == "cooperative"
    contract = o.store.load_contract()
    assert any("cooperative" in d for d in contract.confirmed_decisions)
    final = o.store.read_text("final.md")
    assert "Confirmed Human Decisions" in final
    assert "cooperative" in final
    events = [
        json.loads(line)["event"]
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for expected in ("HUMAN_GATE_CREATED", "DECISION_APPLIED", "HUMAN_GATE_CLOSED"):
        assert expected in events


def test_scenario_6_noninteractive_persists_packet_and_exits_20(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    ui = ScriptedUI(interactive=False)
    o = make_orchestrator(repo, pi=pi, ui=ui)
    code = o.run()
    assert code == int(ExitCode.WAITING_FOR_HUMAN)
    assert o.state.phase == Phase.WAITING_FOR_HUMAN
    assert o.state.active_gate == "HG001"
    assert (o.store.dir / "human-gate.md").is_file()
    packet = json.loads((o.store.dir / "human-gate.json").read_text(encoding="utf-8"))
    assert packet["current"]["gate_id"] == "HG001"
    # Nothing ran after the gate.
    assert not any(c[0] == "design" for c in pi.calls)


# --- Scenario 7: partial Human response --------------------------------------


def test_scenario_7_partial_response_keeps_gate_open_then_resumes(repo):
    candidates = [candidate(question="Q1?"), candidate(question="Q2?")]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["1", "banana"])  # Q1 valid, Q2 not mappable
    o = make_orchestrator(repo, pi=pi, ui=ui)
    code = o.run()
    assert code == int(ExitCode.WAITING_FOR_HUMAN)
    gate_log = o.store.load_gate_log()
    assert gate_log.current.status == GateStatus.OPEN
    assert len(gate_log.current.answers) >= 2
    answered = {a.decision_key for a in gate_log.current.answers if a.matched}
    assert len(answered) == 1

    # Resume answers only the unresolved decision; no phases re-run.
    resume_ui = ScriptedUI(answers=["2"])
    resumed = Orchestrator.resume(
        repository=repo, session_id=o.state.session_id, config=Config(),
        pi=pi, codex=FakeCodexAdapter(), ui=resume_ui,
    )
    assert resumed.run() == int(ExitCode.DONE)
    assert resumed.state.task_revision == 2
    # Discovery ran exactly once across both runs.
    assert sum(1 for c in pi.calls if c[0] == "discover" and c[1] is None) == 1


# --- Scenario 8: 都按推荐 with recommendations everywhere ----------------------


def test_scenario_8_global_recommend_shortcut(repo):
    candidates = [
        candidate(question="Q1?", recommendation="cooperative"),
        candidate(question="Q2?", category="TRADE_OFF", recommendation="immediate"),
    ]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["都按推荐"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == int(ExitCode.DONE)
    decisions = {d.decision_key: d for d in o.store.load_decisions().decisions}
    assert len(decisions) == 2
    selected = {d.selected_option_key for d in decisions.values()}
    assert selected == {"cooperative", "immediate"}


# --- Scenario 9: missing recommendation prevents automatic choice --------------


def test_scenario_9_missing_recommendation_not_auto_chosen(repo):
    candidates = [
        candidate(question="Q1?", recommendation="cooperative"),
        candidate(question="Q2?", category="SCOPE", recommendation=None),
    ]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["都按推荐", "都按推荐"])  # never answers Q2 explicitly
    o = make_orchestrator(repo, pi=pi, ui=ui)
    code = o.run()
    assert code == int(ExitCode.WAITING_FOR_HUMAN)  # Q2 unresolved
    gate = o.store.load_gate_log().current
    matched = [a for a in gate.answers if a.matched]
    assert len(matched) == 1  # only Q1 (has recommendation)
    assert any("no recommended option" in p for p in ui.prompts)


# --- Scenario 10 + 11: decision increments revision; stale proposal redesign ---


def test_scenario_11_stale_proposal_forces_redesign(repo):
    # Session 1: no candidates -> design -> interrupt right after proposal.
    pi = FakePiAdapter()
    o = make_orchestrator(repo, pi=pi)

    class Stop(Exception):
        pass

    # Run discovery/intake/design manually by stepping the orchestrator.
    o.step()  # INIT -> DISCOVER
    o.step()  # DISCOVER -> INTAKE
    o.step()  # INTAKE -> DESIGN
    o.step()  # DESIGN -> INITIAL_REVIEW (proposal persisted)
    assert o.state.phase == Phase.INITIAL_REVIEW
    old_proposal = o.store.load_proposal()
    assert old_proposal is not None

    # Simulate a mid-flow gate decision (the V0 invalidation mechanism).
    from agent_review.phases import human_gate
    from agent_review.models import GateQuestion, GateOption

    question = GateQuestion(
        decision_key="TEST-00000001",
        category="TRADE_OFF",
        question="Reconsider trade-off?",
        options=[
            GateOption(key="a", label="Option A"),
            GateOption(key="b", label="Option B"),
        ],
    )
    gate = human_gate.HumanGate(
        gate_id="HG001",
        category="TRADE_OFF",
        created_in_phase="INITIAL_REVIEW",
        questions=[question],
        answers=[
            human_gate.GateAnswer(
                decision_key=question.decision_key, raw="a", option_key="a", matched=True
            )
        ],
    )
    human_gate.apply_gate_answers(o, gate)
    human_gate.invalidate_design_basis(o, "test: decision changes design basis")

    assert o.state.task_revision == 2
    assert o.store.load_proposal() is None  # archived as STALE
    stale_files = list((o.store.history_dir).glob("proposal-*.md"))
    assert len(stale_files) == 1
    assert "STALE" in stale_files[0].read_text(encoding="utf-8")

    # Redesign path: gate routing sends the session back through INTAKE.
    from agent_review.phases import design, intake

    o.state.phase = Phase.INTAKE
    assert intake.run(o) is None
    assert o.state.phase == Phase.DESIGN
    design.run(o)
    new_proposal = o.store.load_proposal()
    assert new_proposal.based_on_task_revision == 2
    from agent_review.phases.review import compute_pass

    assert not compute_pass(
        [], None, old_proposal.based_on_task_revision, o.state.task_revision
    ).passed


# --- Suppression rules --------------------------------------------------------


def test_suppressed_categories_and_optionless_candidates(repo):
    candidates = [
        candidate(category="NAMING", question="Name it pause or halt?"),
        candidate(category="REQUIREMENT", question="No options question?", options=[]),
        candidate(category="TRADE_OFF", question="Real trade-off?", recommendation="cooperative"),
    ]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["都按推荐"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == int(ExitCode.DONE)
    assert o.state.budgets.human_interruptions_used == 1  # one gate only
    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    suppressed = [e for e in events if e["event"] == "HUMAN_CANDIDATE_SUPPRESSED"]
    # Intake re-runs after the gate, so assert on unique decision keys.
    assert len({e["decision_key"] for e in suppressed}) == 2


def test_already_decided_question_not_reasked(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1"]))
    assert o.run() == int(ExitCode.DONE)
    # Re-run intake: the decided candidate is filtered out.
    from agent_review.phases import intake

    o.state.phase = Phase.INTAKE  # direct re-entry for test
    code = intake.run(o)
    assert code is None
    assert o.state.phase == Phase.DESIGN  # no second gate
    assert o.state.budgets.human_interruptions_used == 1


# --- Decisions append-only + superseded ---------------------------------------


def test_decisions_append_only_and_superseded(repo):
    from agent_review.phases import human_gate
    from agent_review.models import GateAnswer, GateOption, GateQuestion

    o = make_orchestrator(repo)
    question = GateQuestion(
        decision_key="REQ-abc12345",
        category="REQUIREMENT",
        question="Which mode?",
        options=[GateOption(key="x", label="X"), GateOption(key="y", label="Y")],
    )
    gate = human_gate.HumanGate(
        gate_id="HG001",
        category="REQUIREMENT",
        created_in_phase="INTAKE",
        questions=[question],
    )
    gate.answers.append(
        GateAnswer(decision_key=question.decision_key, raw="x", option_key="x", matched=True)
    )
    human_gate.apply_gate_answers(o, gate)
    first = o.store.load_decisions().decisions
    assert len(first) == 1

    # Human later supersedes the decision with a new answer.
    gate2 = human_gate.HumanGate(
        gate_id="HG002",
        category="REQUIREMENT",
        created_in_phase="INTAKE",
        questions=[question],
    )
    gate2.answers.append(
        GateAnswer(decision_key=question.decision_key, raw="y", option_key="y", matched=True)
    )
    human_gate.apply_gate_answers(o, gate2)
    decisions = o.store.load_decisions().decisions
    assert len(decisions) == 2  # append-only
    assert decisions[0].status.value == "SUPERSEDED"
    assert decisions[0].superseded_by == "D002"
    assert decisions[1].status.value == "ACTIVE"


# --- Scenario 13: third Human interruption -> HUMAN_HANDOFF --------------------


def test_scenario_13_third_interruption_handoff(repo):
    candidates = [candidate(question=f"Q{i}?") for i in range(1, 8)]  # 7 decisions
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["1", "1", "1", "1", "1", "1"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.phase == Phase.HUMAN_HANDOFF
    assert o.state.status == SessionStatus.HUMAN_HANDOFF
    assert o.state.budgets.human_interruptions_used == 2
    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert sum(1 for e in events if e["event"] == "REQUIREMENT_TOO_AMBIGUOUS") >= 1
    assert any("interruption budget exhausted" in (e.get("reason") or "") for e in events)


# --- Problem mode: UNRESOLVED root cause with FACT gate ------------------------


def test_problem_mode_unresolved_with_fact_gate_then_supported(repo):
    unresolved_investigation = json.dumps(
        {
            "evidence": [{"description": "logs inspected", "location": "app.log"}],
            "hypotheses": [{"statement": "race in worker pool", "status": "UNTESTED"}],
            "root_cause": "",
            "root_cause_status": "UNRESOLVED",
            "causal_chain": [],
            "missing_evidence": ["which queue backend runs in production"],
            "human_candidates": [
                {
                    "category": "FACT",
                    "question": "Which queue backend runs in production?",
                    "why": "Not derivable from the repository.",
                    "options": [
                        {"key": "kafka", "label": "Kafka", "impact": "check consumer lag"},
                        {"key": "rabbit", "label": "RabbitMQ", "impact": "check prefetch"},
                    ],
                    "recommendation": None,
                    "source": "INVESTIGATE",
                }
            ],
        }
    )
    supported_investigation = json.dumps(
        {
            "evidence": [{"description": "confirmed", "location": "src/q.py"}],
            "hypotheses": [{"statement": "h", "status": "CONFIRMED"}],
            "root_cause": "prefetch misconfiguration",
            "root_cause_status": "SUPPORTED",
            "causal_chain": ["a", "b"],
            "missing_evidence": [],
            "human_candidates": [],
        }
    )
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([], task_kind="PROBLEM")],
            "investigate": [unresolved_investigation, supported_investigation],
        }
    )
    ui = ScriptedUI(answers=["1"])
    o = make_orchestrator(repo, pi=pi, ui=ui, kind="problem")
    code = o.run()
    assert code == int(ExitCode.DONE)
    assert o.store.load_contract().root_cause == "prefetch misconfiguration"
    decisions = o.store.load_decisions().decisions
    assert decisions and decisions[0].selected_option_key == "kafka"
    # investigation ran twice: UNRESOLVED -> FACT gate -> re-investigate
    investigate_calls = [c for c in pi.calls if c[0] == "investigate" and c[1] is None]
    assert len(investigate_calls) == 2


def test_problem_mode_unresolved_without_gate_hands_off(repo):
    investigation = json.dumps(
        {
            "evidence": [],
            "hypotheses": [],
            "root_cause": "",
            "root_cause_status": "UNRESOLVED",
            "causal_chain": [],
            "missing_evidence": ["production traces"],
            "human_candidates": [],
        }
    )
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([], task_kind="PROBLEM")],
            "investigate": [investigation],
        }
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(), kind="problem")
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert "UNRESOLVED" in (o.state.handoff_reason or "")
    # No design was fabricated.
    assert not any(c[0] == "design" for c in pi.calls)


class EOFUI(ScriptedUI):
    """Interactive UI whose input stream immediately hits EOF."""

    def ask(self, prompt: str) -> str:
        raise EOFError


def test_gate_eof_exits_waiting_not_failed(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=EOFUI(interactive=True))
    code = o.run()
    assert code == int(ExitCode.WAITING_FOR_HUMAN)
    assert o.state.phase == Phase.WAITING_FOR_HUMAN
    assert (o.store.dir / "human-gate.md").is_file()
