"""Adapter factory: build the Pi/Codex adapters a session will use.

Real adapters are wired for Pi (M4) and Codex (M5); deterministic fake
adapters remain available for tests. Real adapters fail closed when the
required safe capability is unavailable.
"""

from __future__ import annotations

from pathlib import Path

from agent_review.config import Config
from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter


def build_adapters(
    config: Config,
    repository: Path | None = None,
    store=None,
):
    """Returns (pi_adapter, codex_adapter).

    Real adapters receive the session store as a raw-event sink so all
    agent I/O lands under ``.review/<session>/raw/``.
    ``AGENT_REVIEW_FAKE_ADAPTERS=1`` forces deterministic fakes (tests).
    """
    import os

    if os.environ.get("AGENT_REVIEW_FAKE_ADAPTERS") == "1":
        return FakePiAdapter(), FakeCodexAdapter()

    raw_sink = store.append_raw if store is not None else None
    repo = repository or Path.cwd()

    from agent_review.agents.pi import RealPiAdapter
    from agent_review.agents.codex import RealCodexAdapter

    pi_adapter = RealPiAdapter(
        config.pi,
        repository=repo,
        raw_sink=raw_sink,
        protocol_retries=config.budgets.max_protocol_retries,
    )
    codex_adapter = RealCodexAdapter(
        config.codex,
        repository=repo,
        raw_sink=raw_sink,
        protocol_retries=config.budgets.max_protocol_retries,
    )
    return pi_adapter, codex_adapter
