"""V0 configuration.

Small TOML-shaped configuration: agent binaries, models and budget limits.
Configuration file resolution order:

1. ``AGENT_REVIEW_CONFIG`` environment variable (path to a TOML file);
2. ``~/.agent-review/config.toml`` if it exists;
3. built-in defaults.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from agent_review.models import BudgetLimits

DEFAULT_CONFIG_PATH = Path.home() / ".agent-review" / "config.toml"

DEFAULT_PI_BINARY = os.environ.get("AGENT_REVIEW_PI_BIN", "pi")
DEFAULT_CODEX_BINARY = os.environ.get("AGENT_REVIEW_CODEX_BIN", "codex")


@dataclass
class AgentConfig:
    binary: str = DEFAULT_PI_BINARY
    model: str = ""


@dataclass
class Config:
    pi: AgentConfig = field(default_factory=AgentConfig)
    codex: AgentConfig = field(default_factory=lambda: AgentConfig(DEFAULT_CODEX_BINARY))
    budgets: BudgetLimits = field(default_factory=BudgetLimits)


def _apply_section(target: AgentConfig, section: dict) -> None:
    if "binary" in section:
        target.binary = str(section["binary"])
    if "model" in section:
        target.model = str(section["model"])


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    config = Config()
    config_path: Path | None
    if path is not None:
        config_path = Path(path)
    elif os.environ.get("AGENT_REVIEW_CONFIG"):
        config_path = Path(os.environ["AGENT_REVIEW_CONFIG"])
    else:
        config_path = DEFAULT_CONFIG_PATH

    if config_path is None or not config_path.is_file():
        return config

    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError:
        # Malformed config falls back to defaults rather than crashing the CLI.
        return config

    _apply_section(config.pi, data.get("pi", {}))
    _apply_section(config.codex, data.get("codex", {}))

    budgets = data.get("budgets", {})
    limits = BudgetLimits()
    if "revision" in budgets:
        limits.max_revision_rounds = int(budgets["revision"])
    if "ablation" in budgets:
        limits.max_ablation_rounds = int(budgets["ablation"])
    if "human_interruptions" in budgets:
        limits.max_human_interruptions = int(budgets["human_interruptions"])
    if "protocol_retries" in budgets:
        limits.max_protocol_retries = int(budgets["protocol_retries"])
    config.budgets = limits
    return config
