"""Loads modules from backend/edge-agent (a hyphenated folder that is not an importable package)."""

import importlib.util
import sys
from types import ModuleType

from config import BASE_DIR

EDGE_AGENT_DIR = BASE_DIR / "edge-agent"


def load_edge_agent_module(name: str) -> ModuleType:
    qualified = f"edge_agent_{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
    path = EDGE_AGENT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load edge-agent module {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module
