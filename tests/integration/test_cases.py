"""M6 integration: deterministic Cases A/B/C on fixture repositories."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter, make_blocking_issue
from agent_review.config import Config
from agent_review.models import ExitCode, Phase, SessionStatus
from agent_review.orchestrator import Orchestrator

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "repos"


@pytest.fixture
def case_repo(tmp_path: Path, request):
    name = request.param
    dest = tmp_path / name
    shutil.copytree(FIXTURES / name, dest)
    return dest


class NonInteractiveUI:
    def is_interactive(self) -> bool:
        return False

    def echo(self, text: str) -> None:  # pragma: no cover
        pass

    def ask(self, prompt: str) -> str:  # pragma: no cover
        return ""


class AnswersUI(NonInteractiveUI):
    def __init__(self, answers):
        self.answers = list(answers)

    def is_interactive(self) -> bool:
        return True

    def echo(self, text: str) -> None:
        pass

    def ask(self, prompt: str) -> str:
        return self.answers.pop(0) if self.answers else ""


# --- Case A: simple change -> initial review passes -> DONE -------------------


@pytest.mark.parametrize("case_repo", ["case_a_simple"], indirect=True)
def test_case_a_simple_change(case_repo):
    o = Orchestrator.create(
        repository=case_repo,
        request="Add a max-retry counter to the sync task",
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    code = o.run()
    assert code == int(ExitCode.DONE)
    assert o.state.phase == Phase.DONE
    assert o.state.round == 1
    final = o.store.read_text("final.md")
    assert final and "Change Goal" in final
    assert "Explicitly Unchanged" in final
    # standalone: contains contract + design essentials
    contract = o.store.load_contract()
    assert contract.user_intent in final


# --- Case B: correctable blocker -> revision -> closure -> DONE -----------------


@pytest.mark.parametrize("case_repo", ["case_b_blocker"], indirect=True)
def test_case_b_blocker_revision_closure(case_repo):
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps(
                    {
                        "issues": [
                            make_blocking_issue(
                                1, "load_config drops nested override keys"
                            ).model_dump()
                        ],
                        "summary": "one blocker",
                    }
                )
            ]
        }
    )
    o = Orchestrator.create(
        repository=case_repo,
        request="Make load_config merge nested dictionaries deeply",
        config=Config(),
        pi=FakePiAdapter(),
        codex=codex,
        ui=NonInteractiveUI(),
    )
    code = o.run()
    assert code == int(ExitCode.DONE)
    assert o.state.budgets.revision_used == 1
    assert o.state.budgets.ablation_used == 0
    issues = o.store.load_issues().issues
    assert issues[0].status.value == "RESOLVED"
    assert o.store.read_text("proposal.md") is not None
    # the pre-revision proposal is archived, not destroyed
    assert list((o.store.history_dir).glob("proposal-*.md"))


# --- Case C: human trade-off -> gate -> decision -> redesign -> DONE -------------


TRADEOFF_DISCOVERY = json.dumps(
    {
        "task_kind": "CHANGE",
        "current_state": "queue workers use in-memory MemoryQueue; jobs lost on restart",
        "relevant_components": ["job_queue.py"],
        "existing_constraints": ["public push/pop API must not change"],
        "change_surface": ["job_queue.py"],
        "unknowns": [],
        "human_candidates": [
            {
                "category": "TRADE_OFF",
                "question": "Should restart-survivable jobs use SqliteQueue or stay memory-only?",
                "why": "Persistence changes operational behavior and dependencies.",
                "options": [
                    {"key": "sqlite", "label": "Persist via SqliteQueue", "impact": "jobs survive restart; adds migration"},
                    {"key": "memory", "label": "Stay memory-only", "impact": "no persistence; simplest"},
                ],
                "recommendation": "sqlite",
                "source": "DISCOVER",
            }
        ],
    }
)


@pytest.mark.parametrize("case_repo", ["case_c_tradeoff"], indirect=True)
def test_case_c_tradeoff_gate_redesign(case_repo):
    pi = FakePiAdapter(script={"discover": [TRADEOFF_DISCOVERY]})
    o = Orchestrator.create(
        repository=case_repo,
        request="Make queued jobs survive a worker restart",
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    code = o.run()
    assert code == int(ExitCode.WAITING_FOR_HUMAN)
    assert o.state.phase == Phase.WAITING_FOR_HUMAN
    assert o.store.read_text("human-gate.md") is not None
    assert not any(c[0] == "design" for c in pi.calls)

    # Resume interactively: answer the trade-off.
    resumed = Orchestrator.resume(
        repository=case_repo,
        session_id=o.state.session_id,
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=AnswersUI(["sqlite"]),
    )
    code = resumed.run()
    assert code == int(ExitCode.DONE)
    assert resumed.state.task_revision == 2
    proposal = resumed.store.load_proposal()
    assert proposal.based_on_task_revision == 2
    decisions = resumed.store.load_decisions().decisions
    assert decisions[0].selected_option_key == "sqlite"
    contract = resumed.store.load_contract()
    assert any("sqlite" in d for d in contract.confirmed_decisions)
    final = resumed.store.read_text("final.md")
    assert "sqlite" in final


# --- capability detection fails closed end-to-end --------------------------------


@pytest.mark.parametrize("case_repo", ["case_a_simple"], indirect=True)
def test_missing_agent_binary_fails_closed(case_repo):
    from agent_review.config import AgentConfig

    config = Config()
    config.pi = AgentConfig(binary="definitely-not-a-real-pi-binary")
    o = Orchestrator.create(
        repository=case_repo,
        request="anything",
        config=config,
        pi=None,  # force build_adapters with the broken config
        codex=None,
        ui=NonInteractiveUI(),
    )
    code = o.run()
    assert code == int(ExitCode.FAILED)
    assert o.state.phase == Phase.FAILED
    assert o.state.status == SessionStatus.FAILED
    assert "not found" in (o.state.error or "")
    # Nothing was mutated in the target repo except .review/
    assert sorted(p.name for p in case_repo.iterdir()) == sorted(
        [".review", "task_runner.py"]
    )
