"""Built-in adapters, datasets and metrics models, addressable by name."""

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import cast

from tracefi.case_study import DATASET as LENDING_DATASET
from tracefi.case_study import LendingAgent, LendingMetrics
from tracefi.models import ExperimentAdapter, ModelAdapter
from tracefi.models.deterministic import DeterministicAgent
from tracefi.models.ollama import OllamaAgent

OFFLINE_ADAPTERS: dict[str, Callable[[], ExperimentAdapter]] = {
    "deterministic": DeterministicAgent,
    "agent-v1": lambda: DeterministicAgent("1"),
    "agent-v2": lambda: DeterministicAgent("2"),
    "lending-v1": lambda: LendingAgent("1"),
    "lending-v2": lambda: LendingAgent("2"),
}
ADAPTERS: dict[str, Callable[[], ModelAdapter]] = {**OFFLINE_ADAPTERS, "ollama": OllamaAgent}
DASHBOARD_ADAPTERS = ("deterministic", "lending-v1", "lending-v2")

DEFAULT_DATASET = Path(__file__).parent / "datasets"
DATASETS = {"lending": LENDING_DATASET}

METRICS_MODELS = {"synthetic-lending-v1": LendingMetrics()}


def load_adapter(name: str) -> ModelAdapter:
    """A built-in adapter by name, or a trusted `module:factory` adapter."""
    if name in ADAPTERS:
        return ADAPTERS[name]()
    if ":" not in name:
        raise ValueError("Adapter must be one of " + ", ".join(ADAPTERS) + " or module:factory")
    module, attribute = name.split(":", 1)
    adapter = getattr(importlib.import_module(module), attribute)()
    if not callable(getattr(adapter, "decide", None)):
        raise TypeError("Adapter must implement decide(state)")
    return cast(ModelAdapter, adapter)


def dataset_path(value: str | Path) -> Path:
    """A built-in dataset name or a directory of JSON scenarios."""
    path = Path(value)
    return DATASETS.get(path.as_posix(), path)
