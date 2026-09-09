"""M4: real Pi adapter contract tests against a mock RPC process."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from agent_review.agents.base import AgentError, CapabilityError, ProtocolError
from agent_review.agents.pi import (
    PiRpcClient,
    RealPiAdapter,
    _STARTUP_ARGS,
    detect_pi_capability,
    render_prompt,
)
from agent_review.config import AgentConfig, Config
from agent_review.models import Phase, SessionState

MOCK_PI = Path(__file__).resolve().parent.parent / "fixtures" / "mock_pi.py"


def use_mock_pi(monkeypatch, **extra):
    monkeypatch.setattr(
        PiRpcClient,
        "_spawn_argv",
        lambda self: [sys.executable, str(MOCK_PI), *_STARTUP_ARGS],
    )
    monkeypatch.setenv(
        "MOCK_PI_TEXT",
        extra.get("text", '{"task_kind":"CHANGE","current_state":"mocked"}'),
    )
    for key, value in extra.items():
        if key != "text":
            monkeypatch.setenv(key, value)


def make_adapter(repo: Path, raw_sink=None) -> RealPiAdapter:
    return RealPiAdapter(
        AgentConfig(binary=sys.executable, model=""),
        repository=repo,
        raw_sink=raw_sink,
    )


def make_state(repo: Path) -> SessionState:
    return SessionState(
        session_id="s", repository=str(repo), request="add pause", phase=Phase.DISCOVER
    )


# --- prompt rendering --------------------------------------------------------


def test_render_prompt_fills_all_placeholders():
    text = render_prompt(
        "discover",
        request="do X",
        repo="/repo",
        kind_hint="CHANGE",
        listing="a.py",
        schema="{}",
    )
    assert "do X" in text and "/repo" in text
    assert "{{" not in text


def test_render_prompt_rejects_unfilled():
    with pytest.raises(AgentError):
        render_prompt("discover", request="x", repo="y", kind_hint="CHANGE", listing="z")
    # schema placeholder unfilled -> error


def test_repository_listing_bounded_and_filtered(tmp_path):
    from agent_review.agents.pi import repository_listing

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("x", encoding="utf-8")
    (tmp_path / ".review").mkdir()
    listing = repository_listing(tmp_path)
    assert "src/" in listing and "src/a.py" in listing
    assert ".git" not in listing and ".review" not in listing
    small = repository_listing(tmp_path, max_entries=1)
    assert "omitted" in small


# --- capability detection ----------------------------------------------------


def test_capability_missing_binary():
    with pytest.raises(CapabilityError):
        detect_pi_capability(AgentConfig(binary="not-a-real-binary-xyz"))


def test_capability_rpc_roundtrip_success(tmp_path, monkeypatch):
    use_mock_pi(monkeypatch)
    info = detect_pi_capability(
        AgentConfig(binary=sys.executable), probe_timeout=60
    )
    assert info["rpc"] is True
    assert info["read_only_probe"]


def test_capability_write_probe_fails_closed(tmp_path, monkeypatch):
    use_mock_pi(monkeypatch, MOCK_PI_WRITE_PROBE="1")
    with pytest.raises(CapabilityError) as excinfo:
        detect_pi_capability(AgentConfig(binary=sys.executable), probe_timeout=60)
    assert "read-only" in str(excinfo.value)


def test_capability_agent_crash_raises(tmp_path, monkeypatch):
    use_mock_pi(monkeypatch, MOCK_PI_DIE_ON_PROMPT="1")
    with pytest.raises(AgentError):
        detect_pi_capability(AgentConfig(binary=sys.executable), probe_timeout=60)


# --- adapter phase calls ------------------------------------------------------


def test_discover_parses_structured_output(tmp_path, monkeypatch, repo):
    use_mock_pi(monkeypatch, text=json.dumps({
        "task_kind": "PROBLEM",
        "current_state": "sync loop runs forever",
        "relevant_components": ["src/sync.py"],
        "existing_constraints": ["API stable"],
        "change_surface": ["src/sync.py"],
        "unknowns": ["queue backend"],
        "human_candidates": [],
    }))
    adapter = make_adapter(repo)
    adapter._capability = {"binary": "mock"}  # skip detection for unit test
    result = adapter.discover(make_state(repo))
    assert result.task_kind.value == "PROBLEM"
    assert result.relevant_components == ["src/sync.py"]


def test_design_validates_and_repairs_once(repo, monkeypatch):
    bad = "this is not json"
    good = json.dumps({
        "summary": "minimal pause design",
        "explicitly_unchanged": ["everything else"],
        "changes": ["add pause flag"],
    })
    use_mock_pi(monkeypatch, text=bad, MOCK_PI_REPAIR_TEXT=good)
    adapter = make_adapter(repo)
    adapter._capability = {"binary": "mock"}
    from agent_review.models import ChangeContract

    contract = ChangeContract(
        user_intent="pause", current_behavior="runs", desired_behavior="pausable"
    )
    result = adapter.design(make_state(repo), contract)
    assert result.summary == "minimal pause design"
    assert adapter.protocol_retries_used == 1


def test_second_protocol_failure_raises(repo, monkeypatch):
    use_mock_pi(monkeypatch, text="still not json", MOCK_PI_REPAIR_TEXT="also not json")
    adapter = make_adapter(repo)
    adapter._capability = {"binary": "mock"}
    from agent_review.models import ChangeContract

    contract = ChangeContract(
        user_intent="pause", current_behavior="runs", desired_behavior="pausable"
    )
    with pytest.raises(ProtocolError):
        adapter.design(make_state(repo), contract)


def test_raw_events_captured_to_store(repo, monkeypatch, tmp_path):
    use_mock_pi(monkeypatch)
    from agent_review.storage import StateStore

    store = StateStore.create_session(repo, "raw capture test", None)
    adapter = RealPiAdapter(
        AgentConfig(binary=sys.executable, model=""),
        repository=repo,
        raw_sink=store.append_raw,
    )
    adapter._capability = {"binary": "mock"}
    adapter.discover(make_state(repo))
    raw = store.raw_dir / "pi-discover.jsonl"
    assert raw.is_file()
    lines = [json.loads(l) for l in raw.read_text(encoding="utf-8").splitlines()]
    assert any(e.get("type") == "response" and e.get("command") == "get_state" for e in lines)
    assert any(e.get("type") == "agent_settled" for e in lines)


def test_mock_spawn_uses_resolved_binary(repo, monkeypatch):
    """The adapter must spawn through shutil.which (Windows .CMD wrappers)."""
    import shutil

    use_mock_pi(monkeypatch)
    adapter = make_adapter(repo)
    adapter._capability = {"binary": "mock"}
    result = adapter.discover(make_state(repo))
    assert result.current_state == "mocked"
    assert shutil.which(sys.executable) is not None  # sanity


# --- opt-in real smoke test ---------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("AGENT_REVIEW_SMOKE") != "1" or shutil.which("pi") is None,
    reason="set AGENT_REVIEW_SMOKE=1 with pi installed to run the real smoke test",
)
def test_real_pi_smoke_discover(repo):
    adapter = RealPiAdapter(
        AgentConfig(binary="pi", model=""), repository=repo, timeout=600
    )
    adapter.ensure_capability()
    result = adapter.discover(make_state(repo))
    assert result.current_state
