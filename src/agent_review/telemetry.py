"""V0.3 session telemetry (design §59).

Deterministic aggregation from persisted artifacts (state, issues,
events, scope assessment) written once at the terminal boundary as
``telemetry.json``. No dashboard, no analytics platform — structured
workflow evidence for future Agent-composition decisions. Everything
here remains derivable from ``events.jsonl``; the file is a convenience
projection, never an authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent_review.models import (
    IssueSeverity,
    IssueStatus,
    NewIssueOrigin,
    ResultStatus,
    ScopeVerdict,
    SessionState,
)


def _load_events(store) -> list[dict]:
    path = store.dir / "events.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue  # audit trail may contain torn lines; skip
    return events


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def build_telemetry(store, state: SessionState) -> dict:
    events = _load_events(store)
    issues = store.load_issues().issues

    def _count(event_name: str, **match) -> int:
        total = 0
        for e in events:
            if e.get("event") != event_name:
                continue
            if all(e.get(k) == v for k, v in match.items()):
                total += 1
        return total

    def _ts(event_name: str, occurrence: int = 0) -> datetime | None:
        seen = 0
        for e in events:
            if e.get("event") == event_name:
                if seen == occurrence:
                    return _parse_ts(e.get("ts"))
                seen += 1
        return None

    # scope guard duration
    started = _ts("SCOPE_GUARD_STARTED")
    completed = _ts("SCOPE_GUARD_COMPLETED")
    scope_duration = None
    if started is not None and completed is not None:
        scope_duration = round((completed - started).total_seconds(), 1)

    # same-blocker recurrence: issues ADDRESSED more than once
    addressed_per_issue: dict[str, int] = {}
    for e in events:
        if e.get("event") == "ISSUE_ADDRESSED" and e.get("issue_id"):
            addressed_per_issue[e["issue_id"]] = (
                addressed_per_issue.get(e["issue_id"], 0) + 1
            )
    same_blocker_rounds = sum(1 for n in addressed_per_issue.values() if n > 1)

    first_event_ts = _parse_ts(events[0].get("ts")) if events else None
    last_event_ts = _parse_ts(events[-1].get("ts")) if events else None
    time_to_first_proposal = None
    proposal_ts = _ts("PROPOSAL_CREATED")
    if proposal_ts is not None and first_event_ts is not None:
        time_to_first_proposal = round(
            (proposal_ts - first_event_ts).total_seconds(), 1
        )
    total_elapsed = None
    if last_event_ts is not None:
        created = state.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        total_elapsed = round((last_event_ts - created).total_seconds(), 1)

    scope_assessment = store.load_scope_assessment()
    decomposition_count = (
        len(scope_assessment.decomposition) if scope_assessment else 0
    )

    return {
        "session_id": state.session_id,
        "scope_verdict": state.scope_verdict,
        "scope_guard_duration_seconds": scope_duration,
        "decomposition_count": decomposition_count,
        "initial_blocker_count": sum(
            1
            for i in issues
            if i.severity == IssueSeverity.BLOCKING
            and i.provenance == "INITIAL_REVIEW"
        ),
        "closure_new_blocker_count": sum(
            1
            for i in issues
            if i.severity == IssueSeverity.BLOCKING
            and i.provenance == "CLOSURE_REVIEW"
        ),
        "final_new_blocker_count": sum(
            1
            for i in issues
            if i.severity == IssueSeverity.BLOCKING
            and i.provenance == "FINAL_REVIEW"
        ),
        "previous_review_miss_count": sum(
            1 for i in issues if i.origin == NewIssueOrigin.PREVIOUS_REVIEW_MISS
        ),
        "full_revision_count": state.budgets.revision_used,
        "focused_revision_count": state.budgets.focused_revision_used,
        "ablation_count": state.budgets.ablation_used,
        "same_blocker_round_count": same_blocker_rounds,
        "no_material_progress_stop_count": _count("NO_MATERIAL_PROGRESS_STOP"),
        "correction_stop_count": _count("CORRECTION_STOPPED"),
        "need_human_issue_count": sum(
            1 for i in issues if i.status == IssueStatus.NEED_HUMAN
        ),
        "human_interruptions": state.budgets.human_interruptions_used,
        "terminal_result_status": state.result_status,
        "session_result_generated": (store.dir / "session-result.md").is_file(),
        "time_to_first_proposal_seconds": time_to_first_proposal,
        "total_elapsed_seconds": total_elapsed,
    }


def write_telemetry(store, state: SessionState) -> Path:
    payload = build_telemetry(store, state)
    path = store.dir / "telemetry.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path
