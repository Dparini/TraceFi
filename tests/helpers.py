import textwrap
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from hypothesis import strategies as st

from tracefi import TraceFi
from tracefi.models import ModelAdapter
from tracefi.policy import check_policy
from tracefi.registry import load_adapter
from tracefi.storage import SQLiteStorage

TEXT = st.text(st.characters(exclude_categories=("Cs",)), max_size=30)
SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**100), max_value=10**100),
    st.floats(allow_nan=False, allow_infinity=False),
    TEXT,
)
JSON = st.recursive(
    SCALARS,
    lambda child: st.one_of(st.lists(child, max_size=5), st.dictionaries(TEXT, child, max_size=5)),
    max_leaves=20,
)

MARKET = {"apy": 0.067, "liquidity": 21_000_000, "price": 1, "oracle_age_seconds": 20}


def make_trace(
    context: dict[str, Any] | None = None,
    adapter: ModelAdapter | None = None,
    config: dict[str, Any] | None = None,
    collector: TraceFi | None = None,
) -> dict[str, Any]:
    """Capture one complete synthetic decision and return the verified stored trace."""
    if collector is None:
        with TraceFi(db=":memory:") as owned:
            return make_trace(context, adapter, config, owned)
    adapter = adapter or load_adapter("deterministic")
    with collector.decision(
        "rule-agent",
        "1",
        portfolio={"USDC": 100_000},
        agent_config=config or {"version": "1"},
        policy_config={"max_exposure": 0.35},
    ) as trace:
        trace.capture_context({**MARKET, **(context or {})})
        proposal = adapter.decide(trace.state())
        trace.capture_decision(proposal)
        state = trace.state()
        trace.capture_policy(
            check_policy(proposal, state["portfolio"], state["policy_configuration"])
        )
        trace.capture_simulation({"success": True})
        trace.capture_execution({"status": "success"})
    return collector.storage.get(trace.trace_id)


def save(path: Path, trace: dict[str, Any]) -> Path:
    storage = SQLiteStorage(path)
    try:
        storage.save(trace)
    finally:
        storage.close()
    return path


def adapter_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> str:
    """Write an importable adapter module and return its `module:factory` name."""
    name = "tracefi_test_adapter_" + uuid4().hex
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(source))
    monkeypatch.syspath_prepend(str(tmp_path))
    return name + ":factory"
