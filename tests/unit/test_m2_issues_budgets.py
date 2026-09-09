"""M2 acceptance: issue lifecycle, PASS rule, budgets, ablation, handoff."""

from __future__ import annotations

import json

from agent_review.agents.fakes import (
    FakeCodexAdapter,
    FakePiAdapter,
    make_blocking_issue,
)
from agent_review.config import Config
from agent_review.models import (
    ExitCode,
    IssueSeverity,
    IssueStatus,
    Phase,
    SessionStatus,
)
from agent_review.orchestrator import Orchestrator
from agent_review.phases.review import compute_pass


def run_flow(repo, pi=None, codex=None, kind=None):
    o = Orchestrator.create(
        repository=repo,
        request="add pause capability",
        task_kind_explicit=kind,
        config=Config(),
        pi=pi or FakePiAdapter(),
        codex=codex or FakeCodexAdapter(),
    )
    code = o.run()
    return o, code


def blocker_review_json(number=1, title="Blocking design gap"):
    issue = make_blocking_issue(number, title)
    return json.dumps({"issues": [json.loads(issue.model_dump_json())], "summary": "s"})


# --- PASS rule unit ---------------------------------------------------------


def test_compute_pass_rules():
    blocking_open = make_blocking_issue(1)
    assert compute_pass([], None, 1, 1).passed
    assert not compute_pass([blocking_open], None, 1, 1).passed

    addressed = blocking_open.model_copy(update={"status": IssueStatus.ADDRESSED})
    result = compute_pass([addressed], None, 1, 1)
    assert not result.passed and result.addressed_blocking == ["R001"]

    need_human = blocking_open.model_copy(update={"status": IssueStatus.NEED_HUMAN})
    assert not compute_pass([need_human], None, 1, 1).passed

    assert not compute_pass([], "HG001", 1, 1).passed  # active gate blocks
    assert not compute_pass([], None, 1, 2).passed  # stale proposal blocks

    non_blocking = make_blocking_issue(2).model_copy(
        update={"severity": IssueSeverity.NON_BLOCKING, "acceptance": []}
    )
    assert compute_pass([non_blocking], None, 1, 1).passed


# --- Scenario 2: blocker -> revision -> closure -> PASS ----------------------


def test_scenario_2_blocker_revision_closure_pass(repo):
    codex = FakeCodexAdapter(script={"initial_review": [blocker_review_json()]})
    pi = FakePiAdapter()
    o, code = run_flow(repo, pi=pi, codex=codex)
    assert code == int(ExitCode.DONE)
    assert o.state.phase == Phase.DONE
    assert o.state.budgets.revision_used == 1
    assert o.state.budgets.ablation_used == 0
    assert o.state.round == 2  # initial + closure

    issues = o.store.load_issues().issues
    assert len(issues) == 1
    assert issues[0].status == IssueStatus.RESOLVED
    assert issues[0].addressed_by  # Pi explained what changed
    final = o.store.read_text("final.md")
    assert "Resolved Blocking Issues" in final
    assert "R001" in final
    # revision was actually invoked with the blocker
    assert any(c[0] == "revise" for c in pi.calls)


# --- Scenario 3/4: blocker unchanged -> ablation -> PASS ---------------------


def test_scenario_3_4_ablation_pass(repo):
    codex = FakeCodexAdapter(
        script={
            "initial_review": [blocker_review_json()],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "UNRESOLVED", "note": "not fixed"}
                        ],
                        "new_issues": [],
                        "summary": "still broken",
                    }
                )
            ],
        }
    )
    o, code = run_flow(repo, codex=codex)
    assert code == int(ExitCode.DONE)
    assert o.state.budgets.revision_used == 1
    assert o.state.budgets.ablation_used == 1
    assert (o.store.dir / "ablation.md").is_file()
    issues = o.store.load_issues().issues
    assert issues[0].status == IssueStatus.RESOLVED  # verified in final review
    events = [json.loads(l)["event"] for l in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "ABLATION_TRIGGERED" in events


# --- Scenario 5: ablation still blocked -> HUMAN_HANDOFF ---------------------


def test_scenario_5_ablation_still_blocked_handoff(repo):
    codex = FakeCodexAdapter(
        script={
            "initial_review": [blocker_review_json()],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "UNRESOLVED", "note": "no"}
                        ],
                        "new_issues": [],
                        "summary": "still broken",
                    }
                )
            ],
            "final_review": [
                json.dumps(
                    {
                        "satisfies_requirement": False,
                        "unresolved_issue_ids": ["R001"],
                        "issues": [],
                        "summary": "ablation insufficient",
                    }
                )
            ],
        }
    )
    o, code = run_flow(repo, codex=codex)
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.phase == Phase.HUMAN_HANDOFF
    assert o.state.status == SessionStatus.HUMAN_HANDOFF
    assert "ablation budget exhausted" in (o.state.handoff_reason or "")


# --- Scenario 18: NON_BLOCKING does not block PASS ---------------------------


def test_scenario_18_non_blocking_does_not_block(repo):
    suggestion = make_blocking_issue(1, "optional improvement").model_copy(
        update={"severity": IssueSeverity.NON_BLOCKING, "acceptance": []}
    )
    codex = FakeCodexAdapter(
        script={"initial_review": [json.dumps({"issues": [json.loads(suggestion.model_dump_json())], "summary": "s"})]}
    )
    pi = FakePiAdapter()
    o, code = run_flow(repo, pi=pi, codex=codex)
    assert code == int(ExitCode.DONE)
    assert o.state.round == 1  # no closure round needed
    assert not any(c[0] == "revise" for c in pi.calls)
    issues = o.store.load_issues().issues
    assert issues[0].severity == IssueSeverity.NON_BLOCKING
    assert issues[0].status == IssueStatus.OPEN  # suggestions stay open, not blocking
    final = o.store.read_text("final.md")
    assert "optional improvement" in final  # surfaced as non-blocking suggestion


# --- Scenario 12: closure new-blocker restrictions ---------------------------


def test_closure_illegal_new_blocker_downgraded(repo):
    illegal = make_blocking_issue(9, "late architecture taste")
    illegal.why_not_detected_initially = None
    codex = FakeCodexAdapter(
        script={
            "initial_review": [blocker_review_json()],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "RESOLVED", "note": "ok"}
                        ],
                        "new_issues": [json.loads(illegal.model_dump_json())],
                        "summary": "adds a taste blocker",
                    }
                )
            ],
        }
    )
    o, code = run_flow(repo, codex=codex)
    assert code == int(ExitCode.DONE)
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity == IssueSeverity.NON_BLOCKING
    assert "downgraded" in (issues["R002"].resolution or "")


def test_closure_regression_blocker_allowed(repo):
    from agent_review.models import IssueCategory

    regression = make_blocking_issue(9, "revision breaks pause/resume")
    regression.category = IssueCategory.REGRESSION
    codex = FakeCodexAdapter(
        script={
            "initial_review": [blocker_review_json()],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "RESOLVED", "note": "ok"}
                        ],
                        "new_issues": [json.loads(regression.model_dump_json())],
                        "summary": "regression found",
                    }
                )
            ],
        }
    )
    o, code = run_flow(repo, codex=codex)
    # Regression stays BLOCKING -> no PASS -> ablation -> final default passes.
    assert code == int(ExitCode.DONE)
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity == IssueSeverity.BLOCKING
    assert issues["R002"].status == IssueStatus.RESOLVED


def test_no_revision_budget_routes_straight_to_ablation(repo):
    config = Config()
    config.budgets.max_revision_rounds = 0
    o = Orchestrator.create(
        repository=repo,
        request="add pause capability",
        config=config,
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(script={"initial_review": [blocker_review_json()]}),
    )
    code = o.run()
    assert code == int(ExitCode.DONE)
    assert o.state.budgets.revision_used == 0
    assert o.state.budgets.ablation_used == 1
