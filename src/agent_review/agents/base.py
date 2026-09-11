"""Stable agent adapter interfaces.

The orchestrator depends only on these protocols, so swapping fake
adapters for real Pi/Codex processes never changes orchestration logic.
"""

from __future__ import annotations

from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel

from agent_review.models import (
    AblationResult,
    ChangeContract,
    DesignResult,
    DiscoveryResult,
    FinalReviewResult,
    InitialReviewResult,
    ClosureReviewResult,
    InvestigationResult,
    RevisionResult,
    SessionState,
)

T = TypeVar("T", bound=BaseModel)


class AgentError(Exception):
    """Agent-level failure (binary missing, process crash, timeout)."""


class CapabilityError(AgentError):
    """Required safe capability unavailable; orchestrator must fail closed."""


class ProtocolError(AgentError):
    """Agent output could not be parsed/validated after the retry budget."""


class RawSink(Protocol):
    def append_raw(self, agent: str, phase: str, line: str) -> None: ...


def extract_json_object(text: str) -> str:
    """Extract the first JSON object from an agent reply.

    Handles bare JSON, ```json fenced blocks and leading/trailing prose.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # fenced block: ```json ... ``` (possibly multiple; take first)
        inner = stripped.split("```", 2)
        if len(inner) >= 2:
            block = inner[1]
            if block.lower().lstrip().startswith("json"):
                block = block.lstrip()[4:]
            return block.strip()
    # find first '{' and match braces naively (strings escaped properly)
    start = stripped.find("{")
    if start == -1:
        raise ValueError("no JSON object found in agent output")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]
    raise ValueError("unbalanced JSON object in agent output")


def validate_agent_output(text: str, model_cls: type[T]) -> T:
    """Parse agent reply text and validate against a Pydantic model."""
    import json

    payload = extract_json_object(text)
    data = json.loads(payload)
    return model_cls.model_validate(data)


def run_with_protocol_repair(
    call: Callable[[str], str],
    model_cls: type[T],
    phase: str,
    max_retries: int = 1,
    on_event: Callable[[str, int], None] | None = None,
) -> T:
    """Run an agent call and validate output, allowing protocol-repair retries.

    ``call`` receives ``None`` for the initial attempt (adapter uses its own
    phase prompt) and the repair prompt string for subsequent attempts.
    """
    repair_prompt = (
        "Your previous reply could not be parsed as the required JSON schema "
        f"({getattr(model_cls, '__name__', model_cls)}). Re-emit the same "
        "conclusion using the required schema. Do not re-analyze or change "
        "the answer. Output only the JSON object."
    )
    attempts = max_retries + 1
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        prompt = repair_prompt if attempt > 1 else None
        text = call(prompt)
        try:
            result = validate_agent_output(text, model_cls)
            if attempt > 1 and on_event:
                on_event("PROTOCOL_REPAIR_SUCCEEDED", attempt)
            return result
        except Exception as exc:  # parse/validation failure only
            last_error = exc
            if attempt == attempts:
                if on_event:
                    on_event("PROTOCOL_RETRIES_EXHAUSTED", attempt)
                break
            if on_event:
                on_event("PROTOCOL_REPAIR_FAILED", attempt)
    raise ProtocolError(
        f"agent output for phase {phase} failed schema validation after "
        f"{attempts} attempt(s): {last_error}"
    )


# Canonical event-phase vocabulary (audit N103): adapters speak in method
# names ("initial_review"); the event stream must speak in workflow Phase
# names so V0.3 aggregation never splits one logical phase into two values.
CANONICAL_PHASE_NAMES = {
    "discover": "DISCOVER",
    "investigate": "INVESTIGATE",
    "design": "DESIGN",
    "revise": "REVISION",
    "ablate": "ABLATION",
    "initial_review": "INITIAL_REVIEW",
    "closure_review": "CLOSURE_REVIEW",
    "final_review": "FINAL_REVIEW",
    "capability": "CAPABILITY",
}


def canonical_phase(name: str) -> str:
    """Normalize an adapter method/probe name to the Phase vocabulary."""
    key = str(name).strip().lower()
    return CANONICAL_PHASE_NAMES.get(key, str(name).upper() or "UNKNOWN")


def protocol_retry_reporter(
    sink: Callable[[str, dict], None] | None,
    agent: str,
    phase: str,
    schema_name: str = "",
):
    """Adapt run_with_protocol_repair callbacks onto the event stream.

    Maps internal repair states onto the stable V0.1 event names:
    PROTOCOL_RETRY / PROTOCOL_RETRY_SUCCEEDED / PROTOCOL_RETRY_EXHAUSTED.
    Phase values are canonicalized to the workflow Phase vocabulary.
    """
    phase = canonical_phase(phase)

    def report(name: str, attempt: int) -> None:
        if sink is None:
            return
        if name == "PROTOCOL_REPAIR_FAILED":
            sink(
                "PROTOCOL_RETRY",
                {"agent": agent, "phase": phase, "next_attempt": attempt + 1,
                 "schema": schema_name},
            )
        elif name == "PROTOCOL_REPAIR_SUCCEEDED":
            sink(
                "PROTOCOL_RETRY_SUCCEEDED",
                {"agent": agent, "phase": phase, "attempt": attempt},
            )
        elif name == "PROTOCOL_RETRIES_EXHAUSTED":
            sink(
                "PROTOCOL_RETRY_EXHAUSTED",
                {"agent": agent, "phase": phase, "attempts": attempt},
            )

    return report


class PiAdapter(Protocol):
    def discover(self, state: SessionState) -> DiscoveryResult: ...
    def investigate(self, state: SessionState, discovery=None, decisions=None) -> InvestigationResult: ...
    def design(
        self, state: SessionState, contract: ChangeContract, discovery=None
    ) -> DesignResult: ...
    def revise(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list,
    ) -> RevisionResult: ...
    def ablate(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list,
    ) -> AblationResult: ...
    def abort(self) -> None: ...


class CodexAdapter(Protocol):
    def initial_review(
        self, state: SessionState, contract: ChangeContract, proposal: DesignResult
    ) -> InitialReviewResult: ...
    def closure_review(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list,
    ) -> ClosureReviewResult: ...
    def final_review(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list,
    ) -> FinalReviewResult: ...
    def abort(self) -> None: ...
