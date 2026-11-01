"""Public agent API with backwards-compatible imports."""
from . import core as _core
from .core import *
from .normalize import normalize_records
from .core import _envelope, _validate_message


def run_diagnosis(*args, **kwargs):
    """Run diagnosis while preserving monkeypatchable legacy agent functions."""
    for name in ("performance_agent", "infrastructure_agent", "connectivity_agent",
                 "correlation_agent", "reporting_agent"):
        setattr(_core, name, globals()[name])
    return _core.run_diagnosis(*args, **kwargs)
