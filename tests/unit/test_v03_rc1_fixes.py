"""V0.3-RC1 correctness fixes — B401–B405 deterministic regressions.

Per docs/V0_3_RC1_FIX_SPEC.md:

- B401 late blocking-issue provenance fails closed (never downgraded);
- B402 HumanCandidate dependency protocol is a PUBLIC Agent protocol
  (packet-local candidate ids; unknown/self/cyclic references invalid);
- B403 the Change Contract owns the current effective Acceptance
  Baseline (stable ids, authority provenance, exact-ID coverage);
- B404 Focused Revision containment validates the ACTUAL proposal delta;
- B405 existing Requirement Authority (Acceptance Baseline + ACTIVE
  decisions + REQUEST) is reused before asking Human again;

plus the Scope Guard risk-vs-compositeness regression and the
Acceptance/Authority structural replay.
"""

from __future__ import annotations

import json

import pytest

from agent_review.agents.fakes import (
    FakeCodexAdapter,
    FakePiAdapter,
    make_blocking_issue,
)
from agent_review.models import (
    ExitCode,
    IssueCategory,
    IssueStatus,
    Phase,
)
from agent_review.orchestrator import Orchestrator

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    default_proposal_dict,
    discovery_with_candidates,
    make_orchestrator,
)


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def event_names(o) -> list[str]:
    return [e["event"] for e in events_of(o)]


def blocker(number=1, title="request behavior is not delivered", **update):
    return make_blocking_issue(number, title=title).model_copy(update=update)


def review_with(issue, coverage=None):
    payload = {"issues": [issue.model_dump()], "summary": "blocked"}
    if coverage is not None:
        payload["acceptance_coverage"] = coverage
    return json.dumps(payload)


def a001(status="PASS", issue_title=None, criterion=None):
    entry = {
        "acceptance_id": "A001",
        "criterion": criterion or "原始请求的期望行为已交付：给同步任务增加暂停能力",
        "status": status,
    }
    if issue_title:
        entry["issue_title"] = issue_title
    return entry


# ===========================================================================
# B402 — public candidate_id dependency protocol
# ===========================================================================


def candidate_with_id(question, candidate_id, depends_on=()):
    base = candidate(question=question)
    base["candidate_id"] = candidate_id
    base["depends_on"] = list(depends_on)
    return base


def invalid_discovery(repo, candidates):
    """Discovery packets that violate the dependency protocol fail
    protocol validation (initial + repair) -> FAILED."""
    payload = discovery_with_candidates(candidates)
    pi = FakePiAdapter(script={"discover": [payload], "discover:repair": [payload]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "discovery:" in (o.state.error or "")


def test_b402_duplicate_candidate_id_rejected(repo):
    invalid_discovery(
        repo,
        [
            candidate_with_id("Storage engine?", "C1"),
            candidate_with_id("Retention window?", "C1"),
        ],
    )
    from agent_review.orchestrator import Orchestrator as _O  # noqa: F401


def test_b402_duplicate_candidate_id_reason(repo):
    import re

    from agent_review.models import DiscoveryResult

    with pytest.raises(Exception) as excinfo:
        DiscoveryResult.model_validate(
            {
                "human_candidates": [
                    {**candidate(), "candidate_id": "C1"},
                    {**candidate(question="Second?"), "candidate_id": "C1"},
                ]
            }
        )
    assert "duplicate candidate_id 'C1'" in str(excinfo.value)


def test_b402_unknown_dependency_rejected(repo):
    invalid_discovery(
        repo,
        [
            candidate_with_id("Depends on a ghost?", "C2", depends_on=["C9"]),
        ],
    )


def test_b402_unknown_dependency_reason(repo):
    from agent_review.models import DiscoveryResult

    with pytest.raises(Exception) as excinfo:
        DiscoveryResult.model_validate(
            {
                "human_candidates": [
                    {
                        **candidate(),
                        "candidate_id": "C2",
                        "depends_on": ["C9"],
                    }
                ]
            }
        )
    assert "unknown candidate_id 'C9'" in str(excinfo.value)
    assert "never silently treated as independent" in str(excinfo.value)


def test_b402_self_dependency_rejected(repo):
    invalid_discovery(
        repo,
        [candidate_with_id("Self referential?", "C1", depends_on=["C1"])],
    )


def test_b402_dependency_cycle_rejected(repo):
    invalid_discovery(
        repo,
        [
            candidate_with_id("First?", "C1", depends_on=["C2"]),
            candidate_with_id("Second?", "C2", depends_on=["C1"]),
        ],
    )


def test_b402_cycle_reason_is_auditable(repo):
    from agent_review.models import DiscoveryResult

    with pytest.raises(Exception) as excinfo:
        DiscoveryResult.model_validate(
            {
                "human_candidates": [
                    {**candidate(), "candidate_id": "C1", "depends_on": ["C2"]},
                    {
                        **candidate(question="Second?"),
                        "candidate_id": "C2",
                        "depends_on": ["C1"],
                    },
                ]
            }
        )
    assert "cycle" in str(excinfo.value)


def test_b402_dependency_without_own_candidate_id_rejected(repo):
    base = candidate(question="Anchored?")
    ghost = candidate(question="No id but depends?")
    ghost["depends_on"] = ["C1"]
    payload = discovery_with_candidates([base, ghost])
    pi = FakePiAdapter(script={"discover": [payload], "discover:repair": [payload]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)


def test_b402_public_protocol_dependency_ordering(repo):
    """The Agent-facing contract: C2 depends_on C1 -> C1 asked first in
    HG001, C2 asked only after C1 is ACTIVE (HG002) — expressed purely
    through public candidate ids, never an internal hash."""
    pi = FakePiAdapter(
        script={
            "discover": [
                discovery_with_candidates(
                    [
                        candidate_with_id("Storage engine?", "C1"),
                        candidate_with_id(
                            "Retention window given engine?", "C2", depends_on=["C1"]
                        ),
                    ]
                )
            ]
        }
    )
    ui = ScriptedUI(answers=["1", "1"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == int(ExitCode.DONE)
    gates = o.store.load_gate_log().gates
    assert len(gates) == 2
    assert [q.decision_key for q in gates[0].questions] and len(gates[0].questions) == 1
    assert len(gates[1].questions) == 1
    # Internal decision-key identity stays hash-derived and stable.
    from agent_review.phases.human_gate import candidate_decision_key

    assert gates[0].questions[0].decision_key == candidate_decision_key(
        "REQUIREMENT", "Storage engine?"
    )
    assert gates[1].questions[0].decision_key == candidate_decision_key(
        "REQUIREMENT", "Retention window given engine?"
    )
    # C1 became ACTIVE before C2 was asked (D001 exists before HG002).
    decisions = o.store.load_decisions().decisions
    assert decisions[0].decision_key == candidate_decision_key(
        "REQUIREMENT", "Storage engine?"
    )
    assert decisions[0].status.value == "ACTIVE"
    # C2 was never asked prematurely: no gate ever contained both.
    assert all(len(g.questions) == 1 for g in gates)


def test_b402_independent_candidates_batch_in_one_gate(repo):
    pi = FakePiAdapter(
        script={
            "discover": [
                discovery_with_candidates(
                    [
                        candidate_with_id("Storage engine?", "C1"),
                        candidate_with_id("Alert threshold?", "C2"),
                    ]
                )
            ]
        }
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1", "1"]))
    assert o.run() == int(ExitCode.DONE)
    gates = o.store.load_gate_log().gates
    assert len(gates) == 1
    assert len(gates[0].questions) == 2
    assert o.state.budgets.human_interruptions_used == 1


def test_b402_discovery_json_persists_candidate_ids(repo):
    """The public protocol is auditable in the persisted packet."""
    pi = FakePiAdapter(
        script={
            "discover": [
                discovery_with_candidates(
                    [
                        candidate_with_id("Storage engine?", "C1"),
                        candidate_with_id("Second?", "C2", depends_on=["C1"]),
                    ]
                )
            ]
        }
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1", "1"]))
    assert o.run() == int(ExitCode.DONE)
    discovery = json.loads(
        (o.store.dir / "discovery.json").read_text(encoding="utf-8")
    )
    ids = [c.get("candidate_id") for c in discovery["human_candidates"]]
    assert ids == ["C1", "C2"]
    assert discovery["human_candidates"][1]["depends_on"] == ["C1"]


# ===========================================================================
# B403 — Contract-owned current effective Acceptance Baseline
# ===========================================================================


def test_b403_new_session_has_non_empty_authoritative_baseline(repo):
    o = make_orchestrator(repo, ui=ScriptedUI(interactive=False))
    while o.state.phase.value not in ("DESIGN", "INITIAL_REVIEW"):
        code = o.step()
        assert code is None or code == 0
    contract = o.store.load_contract()
    assert contract.acceptance_criteria
    assert [c.id for c in contract.acceptance_criteria] == ["A001"]
    assert contract.acceptance_criteria[0].authority_refs == ["REQUEST"]
    task_md = o.store.read_text("task.md")
    assert "Acceptance Criteria" in task_md
    assert "authority: REQUEST" in task_md


def test_b403_decisions_extend_the_baseline_and_rebuild_preserves_history(repo):
    """One intake decision -> A002 traces to D001. A second coverage
    save (the next task revision's initial review) archives the old
    baseline to history/ instead of corrupting it."""
    pi = FakePiAdapter(
        script={"discover": [discovery_with_candidates([candidate()])]}
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1"]))
    assert o.run() == int(ExitCode.DONE)
    contract = o.store.load_contract()
    assert [c.id for c in contract.acceptance_criteria] == ["A001", "A002"]
    assert contract.acceptance_criteria[1].authority_refs == ["D001"]
    assert contract.based_on_task_revision == o.state.task_revision
    # Storage-level rebuild invariant: saving a new baseline preserves
    # the previous one in history/ verbatim.
    from agent_review.models import AcceptanceCoverageEntry

    first = o.store.load_acceptance_coverage()
    o.store.save_acceptance_coverage(
        [
            AcceptanceCoverageEntry(
                acceptance_id="A001",
                criterion="revised criterion",
                status="PASS",
            )
        ]
    )
    archived = list((o.store.dir / "history").glob("acceptance-coverage-*.json"))
    assert archived
    archived_entries = json.loads(archived[0].read_text(encoding="utf-8"))["entries"]
    assert archived_entries == json.loads(
        json.dumps([e.model_dump() for e in first])
    )


def test_b403_assumption_cannot_masquerade_as_authority():
    from agent_review.models import AcceptanceCriterion

    with pytest.raises(ValueError, match="authority provenance"):
        AcceptanceCriterion(id="A001", criterion="x", authority_refs=[])
    with pytest.raises(ValueError, match="unknown authority ref"):
        AcceptanceCriterion(id="A001", criterion="x", authority_refs=["GUT_FEELING"])
    with pytest.raises(ValueError, match="A###"):
        AcceptanceCriterion(id="X1", criterion="x", authority_refs=["REQUEST"])


def test_b403_contract_rejects_duplicate_acceptance_ids():
    from agent_review.models import AcceptanceCriterion, ChangeContract

    with pytest.raises(ValueError, match="unique"):
        ChangeContract(
            user_intent="u",
            current_behavior="c",
            desired_behavior="d",
            acceptance_criteria=[
                AcceptanceCriterion(id="A001", criterion="a", authority_refs=["REQUEST"]),
                AcceptanceCriterion(id="A001", criterion="b", authority_refs=["REQUEST"]),
            ],
        )


def test_b403_initial_unknown_id_fails_closed(repo):
    issue = blocker()
    payload = json.dumps(
        {
            "issues": [issue.model_dump()],
            "acceptance_coverage": [
                {
                    "acceptance_id": "A777",
                    "criterion": "ghost criterion",
                    "status": "PASS",
                }
            ],
            "summary": "blocked",
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [payload, payload]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "unknown: A777" in (o.state.error or "")
    assert o.state.result_status != "APPROVED"


def test_b403_no_empty_baseline_false_approved_via_final(repo):
    """A final review that reports nothing can never APPROVE an RC1
    session (the fake auto-fill is bypassed by a non-empty wrong
    coverage; the empty case is enforced by the validator itself)."""
    from agent_review.models import AcceptanceCoverageEntry, FinalReviewResult
    from agent_review.phases.review import (
        _validate_final_coverage_completeness,
        effective_acceptance_baseline,
    )

    o = make_orchestrator(repo, ui=ScriptedUI(interactive=False))
    while o.state.phase.value != "INITIAL_REVIEW":
        o.step()
    baseline = effective_acceptance_baseline(o)
    empty = FinalReviewResult(
        satisfies_requirement=True,
        acceptance_coverage=[],
        summary="nothing",
    )
    with pytest.raises(Exception, match="re-account every acceptance id"):
        _validate_final_coverage_completeness(o, baseline, empty)


def test_b403_legacy_session_compatibility_rule(repo):
    """Explicit legacy rule: a pre-RC1 contract (no acceptance_criteria)
    re-running INITIAL_REVIEW must still report a non-empty coverage; ids
    are assigned in reported order and FINAL must re-account those exact
    ids. No false APPROVED path is created for the legacy flow."""
    pi = FakePiAdapter()
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps(
                    {
                        "issues": [],
                        "acceptance_coverage": [
                            {"criterion": "legacy criterion one", "status": "PASS"},
                            {"criterion": "legacy criterion two", "status": "PASS"},
                        ],
                        "summary": "legacy initial",
                    }
                )
            ],
        }
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    while o.state.phase.value != "INITIAL_REVIEW":
        o.step()
    # Simulate the pre-RC1 persisted contract: strip the field.
    contract = o.store.load_contract()
    legacy = contract.model_dump()
    legacy["acceptance_criteria"] = []
    o.store.write_text(
        "task.json", json.dumps(legacy, ensure_ascii=False, indent=2) + "\n"
    )
    assert o.run() == int(ExitCode.DONE)
    stored = o.store.load_acceptance_coverage()
    assert [e.acceptance_id for e in stored] == ["A001", "A002"]
    from agent_review.phases.review import effective_acceptance_baseline

    assert [c.id for c in effective_acceptance_baseline(o)] == ["A001", "A002"]


def test_b403_legacy_empty_coverage_cannot_approve(repo):
    pi = FakePiAdapter()
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [], "acceptance_coverage": [], "summary": "x"}),
                json.dumps({"issues": [], "acceptance_coverage": [], "summary": "x"}),
            ],
        }
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    while o.state.phase.value != "INITIAL_REVIEW":
        o.step()
    contract = o.store.load_contract()
    legacy = contract.model_dump()
    legacy["acceptance_criteria"] = []
    o.store.write_text(
        "task.json", json.dumps(legacy, ensure_ascii=False, indent=2) + "\n"
    )
    assert o.run() == int(ExitCode.FAILED)
    assert "cannot APPROVE without accounting" in (o.state.error or "")


def test_b403_reviewer_cannot_silently_append_authority(repo):
    """A criterion the reviewer invents (unknown id) is rejected — the
    authority path for new criteria is the contract rebuild, not the
    review packet."""
    issue = blocker()
    payload = json.dumps(
        {
            "issues": [issue.model_dump()],
            "acceptance_coverage": [
                a001(),
                {
                    "acceptance_id": "A002",
                    "criterion": "reviewer-invented requirement",
                    "status": "PASS",
                },
            ],
            "summary": "blocked",
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [payload, payload]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "unknown: A002" in (o.state.error or "")


# ===========================================================================
# B404 — actual-delta containment for Focused Revision
# ===========================================================================


def focused_issue(number=1, change_scope=("verification_plan",)):
    from agent_review.models import CorrectionAction

    return make_blocking_issue(number, title="validation evidence gap").model_copy(
        update={
            "correction_action": CorrectionAction.FOCUSED_REVISION,
            "change_scope": list(change_scope),
        }
    )


def focused_payload(proposal, changed_sections, scope=("verification_plan",)):
    return json.dumps(
        {
            "proposal": proposal,
            "target_issue_ids": ["R001"],
            "allowed_change_scope": list(scope),
            "preserved_invariants": ["ACTIVE Human Decisions"],
            "changed_sections": list(changed_sections),
            "issue_responses": [
                {"issue_id": "R001", "how_addressed": "focused fix applied"}
            ],
        }
    )


def test_b404_reported_ok_but_actual_delta_outside_scope_rejected(repo):
    """Pi reports changed_sections inside the scope but the serialized
    proposal ALSO modifies a disallowed field -> fail closed."""
    issue = focused_issue()
    proposal = default_proposal_dict()
    proposal["verification_plan"] = ["discriminating tests added"]
    proposal["compatibility"] = ["secretly rewritten compatibility story"]
    bad = focused_payload(proposal, ["verification_plan"])
    pi = FakePiAdapter(script={"focused_revise": [bad, bad]})
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "actual proposal delta is outside the allowed change scope" in (
        o.state.error or ""
    )
    assert "compatibility" in (o.state.error or "")
    # The uncontained proposal never replaced the current one.
    current = o.store.load_proposal()
    assert "secretly rewritten" not in (current.compatibility or [""])[0]


def test_b404_omitted_changed_section_cannot_bypass_containment(repo):
    """changed_sections=[] but the actual delta touches a disallowed
    field -> still rejected (self-report is not the source of truth)."""
    issue = focused_issue()
    proposal = default_proposal_dict()
    proposal["risks"] = ["quietly rewritten risk list"]
    bad = focused_payload(proposal, [])
    pi = FakePiAdapter(script={"focused_revise": [bad, bad]})
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "risks" in (o.state.error or "")


def test_b404_actual_delta_inside_scope_accepted(repo):
    issue = focused_issue()
    proposal = default_proposal_dict()
    proposal["verification_plan"] = ["discriminating tests added"]
    good = focused_payload(proposal, ["verification_plan"])
    pi = FakePiAdapter(script={"focused_revise": [good]})
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    delta = json.loads(
        (o.store.dir / "correction-delta.json").read_text(encoding="utf-8")
    )
    assert delta["mechanism"] == "FOCUSED_REVISION"
    assert delta["actual_changed_sections"] == ["verification_plan"]
    assert delta["containment"] == "explicit"
    assert delta["previous_proposal_snapshot"]


def test_b404_scope_name_normalization(repo):
    """The reviewer's scope label matches canonically (hyphen vs
    underscore), not by exact string."""
    issue = focused_issue(change_scope=("verification-plan",))
    proposal = default_proposal_dict()
    proposal["verification_plan"] = ["discriminating tests added"]
    good = focused_payload(proposal, ["verification-plan"], scope=("verification-plan",))
    pi = FakePiAdapter(script={"focused_revise": [good]})
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)


def test_b404_semantic_scope_explicitly_distinguished(repo):
    """No explicit scope = semantic scope: no mechanical containment, and
    the event stream says so explicitly (not an empty explicit scope)."""
    issue = focused_issue(change_scope=())
    pi = FakePiAdapter()  # default fake touches summary (semantic scope)
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert "FOCUSED_REVISION_SEMANTIC_SCOPE" in event_names(o)


def test_b404_closure_receives_deterministic_delta_context(repo):
    """Closure Review gets persisted old/new delta evidence (B404
    differential-review contract), also after a FULL revision."""
    issue = blocker()  # no recommendation -> default FULL_REVISION
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    delta = json.loads(
        (o.store.dir / "correction-delta.json").read_text(encoding="utf-8")
    )
    assert delta["mechanism"] == "FULL_REVISION"
    assert "summary" in delta["actual_changed_sections"]
    assert delta["previous_proposal_snapshot"]
    assert "CORRECTION_DELTA_RECORDED" in event_names(o)


def test_b404_closure_prompt_embeds_delta_context(repo):
    """The REAL codex adapter passes the delta text into the closure
    prompt (unit-level render check)."""
    issue = focused_issue()
    proposal = default_proposal_dict()
    proposal["verification_plan"] = ["discriminating tests added"]
    good = focused_payload(proposal, ["verification_plan"])
    pi = FakePiAdapter(script={"focused_revise": [good]})
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    delta_text = (o.store.dir / "correction-delta.json").read_text(encoding="utf-8")
    from agent_review.agents.codex import RealCodexAdapter
    from agent_review.agents.pi import render_prompt
    from agent_review.config import AgentConfig

    adapter = RealCodexAdapter(AgentConfig(binary="codex"), repository=o.store.repository)
    captured = {}
    original = adapter._call

    def spy_call(phase, prompt, model_cls):
        captured.setdefault(phase, prompt)
        raise RuntimeError("stop before spawning")

    adapter._call = spy_call
    contract = o.store.load_contract()
    proposal_obj = o.store.load_proposal()
    try:
        adapter.closure_review(
            o.state, contract, proposal_obj, [], correction_delta=delta_text
        )
    except RuntimeError:
        pass
    assert "actual_changed_sections" in captured["closure_review"]
    assert "FOCUSED_REVISION" in captured["closure_review"]


# ===========================================================================
# B405 — existing Requirement Authority reuse
# ===========================================================================


def authority_result(outcome_payload):
    return json.dumps({"outcomes": [outcome_payload]})


def requirement_blocker():
    return blocker(
        category=IssueCategory.REQUIREMENT,
        title="request behavior is not delivered",
    )


def test_b405_coverage_by_current_baseline_skips_human_gate(repo):
    """Reviewer raises 'X is not satisfied' where X is the request-backed
    A001 criterion: authority check resolves COVERED via the baseline ->
    no Human interruption -> engineering correction continues."""
    issue = requirement_blocker()
    pi = FakePiAdapter(
        script={
            "human_authority_check": [
                authority_result(
                    {
                        "issue_id": "R001",
                        "outcome": "COVERED_BY_ACTIVE_DECISION",
                        "referenced_decision_ids": [],
                        "authority_refs": ["A001"],
                        "rationale": (
                            "A001 (REQUEST authority) already establishes the "
                            "requested behavior; this is a solution gap"
                        ),
                    }
                )
            ],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    names = event_names(o)
    assert "CONVERGENCE_GATE_CREATED" not in names
    assert "HUMAN_GATE_CREATED" not in names
    assert o.state.budgets.human_interruptions_used == 0
    covered = [e for e in events_of(o) if e["event"] == "ISSUE_COVERED_BY_DECISION"]
    assert covered and covered[0]["authority_refs"] == ["A001"]
    # Engineering correction ran instead of a gate.
    assert o.state.budgets.revision_used == 1
    # Auditable authority references persist on the issue.
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.covered_by_authority == ["A001"]
    assert r001.status == IssueStatus.RESOLVED  # default closure verified it


def test_b405_coverage_by_request_ref(repo):
    issue = requirement_blocker()
    pi = FakePiAdapter(
        script={
            "human_authority_check": [
                authority_result(
                    {
                        "issue_id": "R001",
                        "outcome": "COVERED_BY_ACTIVE_DECISION",
                        "referenced_decision_ids": [],
                        "authority_refs": ["REQUEST"],
                        "rationale": "the original request settles the semantics",
                    }
                )
            ],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    covered = [e for e in events_of(o) if e["event"] == "ISSUE_COVERED_BY_DECISION"]
    assert covered and covered[0]["authority_refs"] == ["REQUEST"]


def test_b405_combined_authority_refs_accepted(repo):
    issue = requirement_blocker()
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([candidate()])],
            "human_authority_check": [
                authority_result(
                    {
                        "issue_id": "R001",
                        "outcome": "COVERED_BY_ACTIVE_DECISION",
                        "referenced_decision_ids": ["D001"],
                        "authority_refs": ["A001"],
                        "rationale": "decision + baseline together settle it",
                    }
                )
            ],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(answers=["1"]))
    assert o.run() == int(ExitCode.DONE)
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.covered_by_authority == ["D001", "A001"]
    assert r001.covered_by_decisions == ["D001"]


def test_b405_unknown_authority_ref_fails_closed(repo):
    issue = requirement_blocker()
    pi = FakePiAdapter(
        script={
            "human_authority_check": [
                authority_result(
                    {
                        "issue_id": "R001",
                        "outcome": "COVERED_BY_ACTIVE_DECISION",
                        "referenced_decision_ids": [],
                        "authority_refs": ["A999"],
                        "rationale": "forged reference",
                    }
                )
            ],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "NEEDS_HUMAN_DECISION"
    assert "nonexistent authority" in (o.state.handoff_reason or "")
    assert "A999" in (o.state.handoff_reason or "")


def test_b405_superseded_decision_ref_fails_closed(repo):
    """D001 exists but was superseded -> stale, not current authority;
    the reference fails closed instead of silently covering."""
    issue = requirement_blocker()
    pi = FakePiAdapter(
        script={
            "human_authority_check": [
                authority_result(
                    {
                        "issue_id": "R001",
                        "outcome": "COVERED_BY_ACTIVE_DECISION",
                        "referenced_decision_ids": ["D001"],
                        "authority_refs": [],
                        "rationale": "references a superseded decision",
                    }
                )
            ],
        }
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    while o.state.phase.value not in ("DESIGN", "INITIAL_REVIEW"):
        code = o.step()
        assert code is None or code == 0
    # A superseded D001 plus a NEED_HUMAN REQUIREMENT blocker in the log.
    from agent_review.models import Decision, DecisionStatus, IssueLog

    decisions = o.store.load_decisions()
    decisions.decisions.append(
        Decision(
            decision_id="D001",
            decision_key="REQX",
            gate_id="HG000",
            question="settled?",
            answer_text="yes",
            status=DecisionStatus.SUPERSEDED,
        )
    )
    o.store.save_decisions(decisions)
    issue.id = "R001"
    issue.status = IssueStatus.NEED_HUMAN
    log = IssueLog(issues=[issue])
    o.store.save_issues(log)
    from agent_review.phases import human_gate

    code = human_gate.try_gate_for_need_human_issues(o, ["R001"])
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert "superseded" in (o.state.handoff_reason or "")


def test_b405_genuinely_new_requirement_still_opens_gate(repo):
    """A real new Requirement ambiguity keeps the bounded Human Authority
    path (V0.2 semantics unchanged)."""
    issue = requirement_blocker()
    from tests.unit.test_v02_authority_convergence import needs_new_result

    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([])],
            "human_authority_check": [needs_new_result()],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(answers=["1"]))
    code = o.run()
    names = event_names(o)
    assert "CONVERGENCE_GATE_CREATED" in names
    assert code in (int(ExitCode.DONE), int(ExitCode.HUMAN_HANDOFF))


# ===========================================================================
# Scope Guard regression — risk is not compositeness (§9)
# ===========================================================================


def test_high_risk_but_coherent_outcome_stays_bounded(repo):
    """Small coherent change + high correctness/data/security risk ->
    BOUNDED continues to DESIGN; high risk never yields
    DECOMPOSITION_REQUIRED by itself."""
    verdict = json.dumps(
        {
            "verdict": "BOUNDED",
            "primary_outcome": (
                "one migration-safe change to the payment retry classifier"
            ),
            "independent_outcomes": [],
            "decision_clusters": ["retry classification semantics"],
            "change_surfaces": ["src/payments/retry.py"],
            "external_unknowns": [],
            "rationale": (
                "single primary outcome and one coherent change surface even "
                "though the correctness/data/security risk is HIGH (payment "
                "data integrity, transaction boundary); risk is review depth, "
                "not compositeness"
            ),
        }
    )
    pi = FakePiAdapter(script={"scope_guard": [verdict]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert o.state.scope_verdict == "BOUNDED"
    names = event_names(o)
    assert "DESIGN_STARTED" in names
    assert "SCOPE_GUARD_STOPPED" not in names


def test_scope_prompt_states_risk_is_not_compositeness():
    from pathlib import Path

    prompts_dir = Path(__file__).resolve().parents[2] / "src" / "agent_review" / "prompts"
    text = (prompts_dir / "scope_guard.md").read_text(encoding="utf-8")
    assert "Risk and compositeness are DIFFERENT axes" in text
    assert "never DECOMPOSITION_REQUIRED by itself" in text


# ===========================================================================
# Acceptance / Authority structural replay (§12)
# ===========================================================================


def test_acceptance_authority_replay_no_reinterruption(repo):
    """original request establishes requirement X
    -> contract acceptance A001 traces to REQUEST authority
    -> reviewer raises 'X is not satisfied'
    -> authority check resolves COVERED_BY_EXISTING_AUTHORITY
    -> no Human interruption
    -> issue routes as engineering correction."""
    issue = requirement_blocker()
    pi = FakePiAdapter(
        script={
            "human_authority_check": [
                authority_result(
                    {
                        "issue_id": "R001",
                        "outcome": "COVERED_BY_ACTIVE_DECISION",
                        "referenced_decision_ids": [],
                        "authority_refs": ["A001"],
                        "rationale": (
                            "原始请求已确立该语义（A001，REQUEST 权威）；"
                            "关闭条件是代码回归证据，属方案缺口"
                        ),
                    }
                )
            ],
        }
    )
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps(
                    {
                        "issues": [issue.model_dump()],
                        "acceptance_coverage": [
                            a001(status="FAIL", issue_title=issue.title)
                        ],
                        "summary": "request behavior not delivered",
                    }
                )
            ],
        }
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    names = event_names(o)
    assert "HUMAN_GATE_CREATED" not in names
    assert o.state.budgets.human_interruptions_used == 0
    assert o.state.budgets.revision_used == 1
    covered = [e for e in events_of(o) if e["event"] == "ISSUE_COVERED_BY_DECISION"]
    assert covered and covered[0]["authority_refs"] == ["A001"]
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.status == IssueStatus.RESOLVED


def test_replay_late_blocker_malformed_provenance_never_approves(repo):
    """Late blocker with malformed provenance at FINAL_REVIEW cannot
    create a false APPROVED (B401 replay)."""
    late = make_blocking_issue(9, title="final phase surprise").model_dump()
    # origin intentionally missing
    final = json.dumps(
        {
            "satisfies_requirement": True,
            "unresolved_issue_ids": [],
            "issues": [late],
            "summary": "late blocker",
        }
    )
    codex = FakeCodexAdapter(
        script={
            "initial_review": [review_with(blocker())],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {
                                "issue_id": "R001",
                                "resolution": "UNRESOLVED",
                                "note": "over-design; ablate",
                                "correction_action": "ABLATION",
                            }
                        ],
                        "new_issues": [],
                        "summary": "closure",
                    }
                )
            ],
            "final_review": [final],
            "final_review:repair": [final],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert o.state.result_status == "FAILED"
    assert "must record origin" in (o.state.error or "")


def test_replay_missing_acceptance_coverage_never_approves(repo):
    """Missing Contract acceptance coverage cannot create a false
    APPROVED (B403 replay)."""
    issue = blocker()
    wrong = json.dumps(
        {
            "issues": [issue.model_dump()],
            "acceptance_coverage": [
                {"acceptance_id": "A002", "criterion": "ghost", "status": "PASS"}
            ],
            "summary": "blocked",
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [wrong, wrong]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert o.state.result_status == "FAILED"
    assert "missing: A001" in (o.state.error or "")
