"""M5: real Codex adapter contract tests against a mock codex exec."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from agent_review.agents.base import AgentError, CapabilityError, ProtocolError
from agent_review.agents.codex import RealCodexAdapter, detect_codex_capability
from agent_review.agents.pi import render_prompt
from agent_review.config import AgentConfig
from agent_review.models import ChangeContract, DesignResult, Phase, SessionState

MOCK_CODEX = Path(__file__).resolve().parent.parent / "fixtures" / "mock_codex.py"

VALID_INITIAL = json.dumps({"issues": [], "summary": "mock review"})


def make_mock_codex_binary(tmp_path):
    """A spawnable wrapper around the mock script (cross-platform)."""
    if os.name == "nt":
        wrapper = tmp_path / "mock-codex.cmd"
        wrapper.write_text(
            f'@"{sys.executable}" "{MOCK_CODEX}" %*\n', encoding="utf-8"
        )
    else:
        wrapper = tmp_path / "mock-codex"
        wrapper.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{MOCK_CODEX}" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    return str(wrapper)


def use_mock_codex(monkeypatch, tmp_path, **extra):
    monkeypatch.setenv("MOCK_CODEX_TEXT", extra.get("text", VALID_INITIAL))
    for key, value in extra.items():
        if key != "text":
            monkeypatch.setenv(key, value)
    return make_mock_codex_binary(tmp_path)


def make_state(repo: Path) -> SessionState:
    return SessionState(
        session_id="s", repository=str(repo), request="add pause", phase=Phase.INITIAL_REVIEW
    )


def make_contract() -> ChangeContract:
    return ChangeContract(
        user_intent="pause", current_behavior="runs forever", desired_behavior="pausable"
    )


def make_proposal() -> DesignResult:
    return DesignResult(summary="minimal design", explicitly_unchanged=["rest"])


# --- prompts -------------------------------------------------------------------


def test_all_review_prompts_render():
    for name in ("initial_review", "closure_review", "final_review"):
        text = render_prompt(
            name,
            request="r",
            repo="/repo",
            contract="{}",
            proposal="{}",
            issues="[]",
            task_revision=1,
            schema="{}",
        )
        assert "{{" not in text


# --- capability detection --------------------------------------------------------


def test_capability_missing_binary():
    with pytest.raises(CapabilityError):
        detect_codex_capability(AgentConfig(binary="not-a-real-codex-xyz"))


def test_capability_roundtrip_success(tmp_path, monkeypatch):
    binary = use_mock_codex(monkeypatch, tmp_path)
    info = detect_codex_capability(AgentConfig(binary=binary), probe_timeout=60)
    assert info["exec"] is True
    assert info["read_only_probe"] is True


def test_capability_write_probe_fails_closed(tmp_path, monkeypatch):
    binary = use_mock_codex(monkeypatch, tmp_path, MOCK_CODEX_WRITE_PROBE="1")
    with pytest.raises(CapabilityError) as excinfo:
        detect_codex_capability(AgentConfig(binary=binary), probe_timeout=60)
    assert "read-only" in str(excinfo.value)


def test_capability_nonzero_exit_raises(tmp_path, monkeypatch):
    binary = use_mock_codex(monkeypatch, tmp_path, MOCK_CODEX_FAIL="1")
    with pytest.raises(AgentError):
        detect_codex_capability(AgentConfig(binary=binary), probe_timeout=60)


# --- phase calls ------------------------------------------------------------------


def test_initial_review_parses_output(repo, tmp_path, monkeypatch):
    binary = use_mock_codex(
        monkeypatch,
        tmp_path,
        text=json.dumps(
            {
                "issues": [
                    {
                        "category": "DESIGN",
                        "severity": "BLOCKING",
                        "title": "misses pause resume",
                        "problem": "no resume path",
                        "acceptance": ["resume works after restart"],
                    }
                ],
                "summary": "one blocker",
            }
        ),
    )
    adapter = RealCodexAdapter(AgentConfig(binary=binary), repository=repo)
    adapter._capability = {"skip": True}
    result = adapter.initial_review(make_state(repo), make_contract(), make_proposal())
    assert result.issues[0].severity.value == "BLOCKING"
    assert result.issues[0].acceptance


def test_review_output_repaired_once(repo, tmp_path, monkeypatch):
    binary = use_mock_codex(
        monkeypatch,
        tmp_path,
        text="garbage not json",
        MOCK_CODEX_REPAIR_TEXT=json.dumps(
            {
                "issues": [
                    {
                        "severity": "BLOCKING",
                        "title": "t",
                        "acceptance": ["a"],
                    }
                ],
                "summary": "ok",
            }
        ),
    )
    adapter = RealCodexAdapter(AgentConfig(binary=binary), repository=repo)
    adapter._capability = {"skip": True}
    result = adapter.initial_review(make_state(repo), make_contract(), make_proposal())
    assert result.issues[0].title == "t"
    assert adapter.protocol_retries_used == 1


def test_review_second_failure_raises(repo, tmp_path, monkeypatch):
    binary = use_mock_codex(monkeypatch, tmp_path, text="nope", MOCK_CODEX_REPAIR_TEXT="still nope")
    adapter = RealCodexAdapter(AgentConfig(binary=binary), repository=repo)
    adapter._capability = {"skip": True}
    with pytest.raises(ProtocolError):
        adapter.initial_review(make_state(repo), make_contract(), make_proposal())


def test_raw_events_captured(repo, tmp_path, monkeypatch):
    from agent_review.storage import StateStore

    store = StateStore.create_session(repo, "codex raw test", None)
    binary = use_mock_codex(monkeypatch, tmp_path)
    adapter = RealCodexAdapter(
        AgentConfig(binary=binary), repository=repo, raw_sink=store.append_raw
    )
    adapter._capability = {"skip": True}
    adapter.initial_review(make_state(repo), make_contract(), make_proposal())
    raw = store.raw_dir / "codex-initial_review.jsonl"
    assert raw.is_file()
    lines = [json.loads(l) for l in raw.read_text(encoding="utf-8").splitlines()]
    assert any(e.get("type") == "item.completed" for e in lines)


def test_read_only_flag_present_in_spawn(repo, tmp_path, monkeypatch):
    """The reviewer must never be spawned with write-capable sandbox flags."""
    captured = {}
    binary = use_mock_codex(monkeypatch, tmp_path)
    import agent_review.agents.codex as codex_mod

    original_popen = codex_mod.subprocess.Popen

    def spy_popen(argv, **kwargs):
        captured["argv"] = argv
        return original_popen(argv, **kwargs)

    monkeypatch.setattr(codex_mod.subprocess, "Popen", spy_popen)
    adapter = RealCodexAdapter(AgentConfig(binary=binary), repository=repo)
    adapter._capability = {"skip": True}
    adapter.initial_review(make_state(repo), make_contract(), make_proposal())
    argv = captured["argv"]
    assert "-s" in argv and argv[argv.index("-s") + 1] == "read-only"
    assert "--output-schema" in argv


# --- opt-in real smoke test --------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("AGENT_REVIEW_SMOKE") != "1" or shutil.which("codex") is None,
    reason="set AGENT_REVIEW_SMOKE=1 with codex installed to run the real smoke test",
)
def test_real_codex_smoke_review(repo):
    adapter = RealCodexAdapter(
        AgentConfig(binary="codex", model=""), repository=repo, timeout=600
    )
    adapter.ensure_capability()
    result = adapter.initial_review(make_state(repo), make_contract(), make_proposal())
    assert isinstance(result.issues, list)
