import json
from unittest.mock import MagicMock, patch

import pytest

from tracefi.hashing import MAX_BYTES
from tracefi.models.ollama import OllamaAgent, _NoRedirect
from tracefi.registry import ADAPTERS, load_adapter


def test_builtin_adapters_and_factory_validation():
    for name in ADAPTERS:
        assert callable(load_adapter(name).decide)
    with pytest.raises(ValueError, match="lending-v2"):
        load_adapter("unknown")
    with pytest.raises(TypeError):
        load_adapter("builtins:object")


def test_ollama_transport_has_no_proxy_or_redirect_and_bounded_reads():
    response = MagicMock()
    response.read.return_value = json.dumps({"response": '{"action":"HOLD"}'}).encode()
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    with patch("tracefi.models.ollama.build_opener", return_value=opener) as factory:
        assert OllamaAgent().decide({}) == {"action": "HOLD"}
    proxy, redirect = factory.call_args.args
    assert proxy.proxies == {}
    assert isinstance(redirect, _NoRedirect)
    assert redirect.redirect_request(None, None, 302, "", {}, "https://example.com") is None
    response.read.assert_called_once_with(MAX_BYTES + 1)
    assert opener.open.call_args.args[0].full_url == "http://127.0.0.1:11434/api/generate"
    for payload in (
        b"[]",
        b'{"response": "[]"}',
        b'{"response": "{\\"x\\":NaN}"}',
        b"x" * (MAX_BYTES + 1),
    ):
        response.read.return_value = payload
        with (
            patch("tracefi.models.ollama.build_opener", return_value=opener),
            pytest.raises(ValueError),
        ):
            OllamaAgent().decide({})
