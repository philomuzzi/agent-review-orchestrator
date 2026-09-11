"""Deterministic fake adapters used by the test suite and CI baseline.

Fake adapters consume a per-method script (list of raw replies or
exceptions). When a method's script is exhausted they fall back to a
deterministic default successful result, so minimal tests stay minimal.
"""

from __future__ import annotations

from typing import Any

from agent_review.agents.base import (
    AgentError,
    protocol_retry_reporter,
    run_with_protocol_repair,
)
from agent_review.models import (
    AblationResult,
    AuthorityOutcome,
    ChangeContract,
    ChangeMap,
    ClosureReviewResult,
    DesignResult,
    DiscoveryResult,
    FinalReviewResult,
    HumanAuthorityCheckResult,
    InitialReviewResult,
    InvestigationResult,
    Issue,
    IssueAuthorityOutcome,
    IssueCategory,
    IssueSeverity,
    RevisionResult,
    RootCauseStatus,
    SessionState,
)


def default_discovery(state: SessionState) -> DiscoveryResult:
    # Deterministic semantic title for tests (real title comes from Pi).
    title = state.request.strip()[:16] or "Review request"
    return DiscoveryResult(
        task_title=title,
        task_kind=state.task_kind,
        current_state=f"Discovered current state of {state.repository}.",
        relevant_components=["src/"],
        existing_constraints=["No public API removal."],
        change_surface=["src/"],
        unknowns=[],
        human_candidates=[],
    )


def default_investigation() -> InvestigationResult:
    return InvestigationResult(
        evidence=[{"description": "Relevant code paths inspected.", "location": "src/"}],
        hypotheses=[{"statement": "Primary hypothesis confirmed.", "status": "CONFIRMED"}],
        root_cause="Root cause identified from repository evidence.",
        root_cause_status=RootCauseStatus.SUPPORTED,
        causal_chain=["trigger", "propagation", "observable failure"],
        missing_evidence=[],
        human_candidates=[],
    )


def default_design(contract: ChangeContract) -> DesignResult:
    return DesignResult(
        summary=f"Minimal design satisfying: {contract.user_intent}",
        current_flow="Current flow as discovered.",
        proposed_flow="Proposed minimal flow.",
        changes=["Adjust the identified component."],
        failure_handling=["Fail closed on unexpected input."],
        compatibility=["No public interface change."],
        risks=["Small regression risk in touched paths."],
        alternatives_considered=["Larger refactor (rejected: out of scope)."],
        verification_plan=["Run existing test suite.", "Add focused tests for new behavior."],
        explicitly_unchanged=["All untouched modules."],
        change_map=ChangeMap(
            affected_components=["src/"],
            behavior_changes=["New minimal behavior."],
            unchanged_behaviors=["Everything else."],
        ),
    )


def default_revision(
    contract: ChangeContract, proposal: DesignResult, issues: list[Issue]
) -> RevisionResult:
    addressed = [
        {"issue_id": i.id, "how_addressed": f"Revised design to address {i.title}."}
        for i in issues
    ]
    revised = proposal.model_copy(deep=True)
    revised.summary = f"Revised minimal design: {contract.user_intent}"
    return RevisionResult(proposal=revised, addressed_issues=addressed)


def default_ablation(
    contract: ChangeContract, proposal: DesignResult, issues: list[Issue]
) -> AblationResult:
    ablated = proposal.model_copy(deep=True)
    ablated.summary = f"Ablated minimal design: {contract.user_intent}"
    addressed = [
        {"issue_id": i.id, "how_addressed": f"Ablated design resolves {i.title}."}
        for i in issues
    ]
    return AblationResult(
        proposal=ablated,
        removed=["Optional capability removed to shrink surface."],
        rationale="Minimum sufficient design that still satisfies the requirement.",
        addressed_issues=addressed,
    )


def default_initial_review(proposal: DesignResult) -> InitialReviewResult:
    return InitialReviewResult(
        issues=[], summary="No blocking issues found against the Change Contract."
    )


class ScriptedAdapter:
    """Base: per-method scripts of raw replies (str) or exceptions."""

    def __init__(self, script: dict[str, list[Any]] | None = None):
        self.script: dict[str, list[Any]] = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[tuple[str, Any]] = []
        self.protocol_retries_allowed = 1
        self.protocol_retries_used = 0
        self.agent_name = "agent"
        # Set by the orchestrator; protocol retries surface as events.
        self.event_sink = None
        self._current_method = ""
        self._current_model = ""

    def _next(self, method: str) -> Any:
        queue = self.script.get(method)
        if queue:
            item = queue.pop(0)
            self.script[method] = queue
            return item
        return None

    def _record(self, method: str, arg: Any = None) -> None:
        self.calls.append((method, arg))

    def _run(self, method: str, build_result, model_cls):
        self._current_method = method
        self._current_model = model_cls.__name__
        item = self._next(method)
        if isinstance(item, BaseException):
            raise item

        def call(repair_prompt):
            self._record(method, repair_prompt)
            if repair_prompt is not None:
                retry_item = self._next(method + ":repair")
                if isinstance(retry_item, BaseException):
                    raise retry_item
                if retry_item is not None:
                    return retry_item
                return build_result_text()
            if item is not None:
                return item
            return result_to_text(build_result())

        def result_to_text(obj) -> str:
            return obj.model_dump_json()

        def build_result_text() -> str:
            return build_result().model_dump_json()

        return run_with_protocol_repair(
            call,
            model_cls,
            method,
            max_retries=self.protocol_retries_allowed,
            on_event=self._on_protocol_event,
        )

    def _on_protocol_event(self, name: str, attempt: int) -> None:
        if name == "PROTOCOL_REPAIR_FAILED":
            self.protocol_retries_used += 1
        if self.event_sink is not None:
            reporter = protocol_retry_reporter(
                self.event_sink,
                self.agent_name,
                self._current_method,
                self._current_model,
            )
            reporter(name, attempt)

    def abort(self) -> None:  # pragma: no cover - fake has no child process
        pass


def default_authority_check(issues: list[Issue]) -> HumanAuthorityCheckResult:
    """Deterministic default: CANNOT_DETERMINE for every issue.

    Unscripted fake runs fail closed exactly like the V0 boundary: no
    coverage claim and no candidate packet are invented by the host.
    Tests that want real routing script ``human_authority_check``.
    """
    return HumanAuthorityCheckResult(
        outcomes=[
            IssueAuthorityOutcome(
                issue_id=i.id,
                outcome=AuthorityOutcome.CANNOT_DETERMINE,
                rationale="fake adapter default: no scripted authority check",
            )
            for i in issues
        ]
    )


class FakePiAdapter(ScriptedAdapter):
    def __init__(self, script=None):
        super().__init__(script)
        self.agent_name = "pi"

    def discover(self, state: SessionState) -> DiscoveryResult:
        return self._run(
            "discover", lambda: default_discovery(state), DiscoveryResult
        )

    def human_authority_check(self, state, issues, decisions, contract=None):
        return self._run(
            "human_authority_check",
            lambda: default_authority_check(issues),
            HumanAuthorityCheckResult,
        )

    def investigate(self, state: SessionState, discovery=None, decisions=None) -> InvestigationResult:
        return self._run(
            "investigate", lambda: default_investigation(), InvestigationResult
        )

    def design(
        self, state: SessionState, contract: ChangeContract, discovery=None
    ) -> DesignResult:
        def build() -> DesignResult:
            d = default_design(contract)
            d.based_on_task_revision = state.task_revision
            return d

        return self._run("design", build, DesignResult)

    def revise(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list[Issue],
    ) -> RevisionResult:
        def build() -> RevisionResult:
            r = default_revision(contract, proposal, issues)
            r.proposal.based_on_task_revision = state.task_revision
            return r

        return self._run("revise", build, RevisionResult)

    def ablate(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list[Issue],
    ) -> AblationResult:
        def build() -> AblationResult:
            a = default_ablation(contract, proposal, issues)
            a.proposal.based_on_task_revision = state.task_revision
            return a

        return self._run("ablate", build, AblationResult)


class FakeCodexAdapter(ScriptedAdapter):
    def __init__(self, script=None):
        super().__init__(script)
        self.agent_name = "codex"

    def initial_review(
        self, state: SessionState, contract: ChangeContract, proposal: DesignResult
    ) -> InitialReviewResult:
        return self._run(
            "initial_review",
            lambda: default_initial_review(proposal),
            InitialReviewResult,
        )

    def closure_review(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list[Issue],
    ) -> ClosureReviewResult:
        def build() -> ClosureReviewResult:
            outcomes = [
                {"issue_id": i.id, "resolution": "RESOLVED", "note": "Verified."}
                for i in issues
                if i.status.value == "ADDRESSED"
            ]
            return ClosureReviewResult(
                issue_outcomes=outcomes,
                new_issues=[],
                summary="Closure verified acceptance criteria.",
            )

        return self._run("closure_review", build, ClosureReviewResult)

    def final_review(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list[Issue],
    ) -> FinalReviewResult:
        def build() -> FinalReviewResult:
            return FinalReviewResult(
                satisfies_requirement=True,
                unresolved_issue_ids=[],
                issues=[],
                summary="Ablated design satisfies the requirement.",
            )

        return self._run("final_review", build, FinalReviewResult)


def make_blocking_issue(
    number: int,
    title: str = "Blocking design gap",
    acceptance: list[str] | None = None,
    category: IssueCategory = IssueCategory.DESIGN,
) -> Issue:
    return Issue(
        id=f"R{number:03d}",
        category=category,
        severity=IssueSeverity.BLOCKING,
        title=title,
        problem="The proposal does not satisfy part of the Change Contract.",
        impact="Requirement would remain unmet.",
        acceptance=acceptance or ["Design covers the stated requirement."],
        introduced_round=1,
        provenance="INITIAL_REVIEW",
    )
