from copy import deepcopy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.helpers import JSON
from tracefi import TraceFi
from tracefi.hashing import MAX_DEPTH, MAX_NODES, canonicalize
from tracefi.security import REDACTED, Redactor, Secret


def nested(depth, wrap):
    value = 0
    for _ in range(depth):
        value = wrap(value)
    return value


def test_custom_invalid_and_cyclic_redaction():
    assert Redactor(["credential"])([{"CrEdEnTiAl": Secret("x")}]) == [{"CrEdEnTiAl": REDACTED}]
    for keys in ("api_key", [None], [""], [123]):
        with pytest.raises(TypeError):
            Redactor(keys)
    value: dict = {}
    value["self"] = value
    with pytest.raises(ValueError):
        Redactor()(value)
    assert repr(Secret("SENTINEL")) == REDACTED
    assert Secret("SENTINEL").reveal() == "SENTINEL"


@pytest.mark.parametrize(
    "key",
    [
        "context",
        "context_hash",
        "Trace-ID",
        "redaction_keys",
        "parent_id",
        "status",
        "name",
        "type",
        "version",
        "model",
    ],
)
def test_redaction_cannot_target_trace_structure(key):
    with pytest.raises(ValueError):
        TraceFi(db=":memory:", redact=[key])


def test_default_keys_ignore_case_and_separators_and_skip_secret_subtrees():
    cycle: list = []
    cycle.append(cycle)
    assert Redactor()({"private-key": cycle}) == {"private-key": REDACTED}
    assert Redactor()({"AUTHORIZATION": "a", "Access-Token": "b", "refresh_token": "c"}) == {
        "AUTHORIZATION": REDACTED,
        "Access-Token": REDACTED,
        "refresh_token": REDACTED,
    }


@pytest.mark.parametrize("wrap", [lambda value: [value], lambda value: {"key": value}])
def test_redaction_depth_is_bounded(wrap):
    assert Redactor()(nested(MAX_DEPTH, wrap)) == nested(MAX_DEPTH, wrap)
    with pytest.raises(ValueError):
        Redactor()(nested(MAX_DEPTH + 1, wrap))


def test_redaction_node_count_is_bounded():
    assert Redactor()([0] * (MAX_NODES - 1)) == [0] * (MAX_NODES - 1)
    with pytest.raises(ValueError):
        Redactor()([0] * MAX_NODES)


def test_secrets_never_persisted(tmp_path):
    path = tmp_path / "traces.sqlite3"
    with TraceFi(db=path) as collector:
        with collector.decision("secrets", model={"api_key": "MODEL_SENTINEL"}) as trace:
            trace.capture_context(
                {
                    "nested": {"Private-Key": "PRIVATE_SENTINEL"},
                    "items": [collector.secret("WRAPPED_SENTINEL")],
                    "api_key": "API_SENTINEL",
                }
            )
            with trace.span("tool") as span:
                span.log({"Authorization": "AUTH_SENTINEL"})
        stored = collector.storage.get(trace.trace_id)
    raw = path.read_bytes()
    for sentinel in (
        b"PRIVATE_SENTINEL",
        b"WRAPPED_SENTINEL",
        b"API_SENTINEL",
        b"AUTH_SENTINEL",
        b"MODEL_SENTINEL",
    ):
        assert sentinel not in raw
    assert stored["context"]["api_key"] == REDACTED


@given(JSON)
def test_redaction_is_recursive_idempotent_and_nonmutating(value):
    payload = {
        "safe": deepcopy(value),
        "nested": [{"PRIVATE-KEY": "KEY_SENTINEL"}],
        "Authorization": "AUTH_SENTINEL",
        "wrapped": Secret("WRAPPED_SENTINEL"),
    }
    redactor = Redactor()
    cleaned = redactor(payload)
    assert cleaned == redactor(cleaned)
    assert payload["safe"] == value
    assert payload["nested"][0]["PRIVATE-KEY"] == "KEY_SENTINEL"
    for sentinel in (b"KEY_SENTINEL", b"AUTH_SENTINEL", b"WRAPPED_SENTINEL"):
        assert sentinel not in canonicalize(cleaned)


@given(
    st.sampled_from(["api_key", "API-KEY", "Private_Key", "AUTHORIZATION", "refresh-token"]), JSON
)
def test_secret_key_values_never_enter_storage(key, value):
    with TraceFi(db=":memory:") as collector:
        with collector.decision("property-agent") as trace:
            trace.capture_context(
                {"level": [{key: {"sentinel": "PERSIST_SENTINEL", "data": value}}]}
            )
        stored = collector.storage.get(trace.trace_id)
        assert stored["context"]["level"][0][key] == REDACTED
        for table in ("traces", "spans", "artifacts"):
            for (raw,) in collector.storage.connection.execute(f"SELECT payload FROM {table}"):
                assert "PERSIST_SENTINEL" not in raw
