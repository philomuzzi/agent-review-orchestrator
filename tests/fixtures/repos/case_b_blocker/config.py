# config loader (Case B: correctable blocker)

DEFAULTS = {"retries": 3, "timeout": 30}


def load_config(overrides=None):
    """Merge overrides into DEFAULTS (shallow)."""
    config = DEFAULTS.copy()
    if overrides:
        config.update(overrides)
    return config
