"""Checks AnthropicClient against the real anthropic SDK, using a local stand-in server.
Verifies the request shape the current API requires and that answers are parsed by block type."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("anthropic")

from enforcement_toolkit.extraction.llm_client import AnthropicClient  # noqa: E402
from enforcement_toolkit.extraction.schema import output_schema  # noqa: E402

ANSWER = {"case_title": "SEC v. Doe", "respondents": [], "confidence": 0.9}
ANSWER_TEXT = json.dumps(ANSWER)


def _serve(stop_reason="end_turn", text=ANSWER_TEXT):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            seen["path"] = self.path
            seen["headers"] = dict(self.headers)
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            body = {
                "id": "msg_test", "type": "message", "role": "assistant", "model": seen["body"]["model"],
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "sig"},  # thinking comes first
                    {"type": "text", "text": text},
                ],
                "stop_reason": stop_reason, "stop_sequence": None,
                "usage": {"input_tokens": 1234, "output_tokens": 210},
            }  # fmt: skip
            out = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def make(**kw):
        srv, seen = _serve(**kw)
        c = AnthropicClient(
            "claude-sonnet-5-5", max_retries=0, base_url=f"http://127.0.0.1:{srv.server_port}"
        )
        return c, seen, srv

    return make


def test_request_uses_structured_outputs_not_removed_params(client):
    c, seen, srv = client()
    res = c.extract("system text", "user text", output_schema())
    srv.shutdown()
    body = seen["body"]
    assert seen["path"].endswith("/v1/messages")
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "low"
    for removed in ("temperature", "top_p", "top_k", "tool_choice", "tools"):
        assert removed not in body
    assert res.data == ANSWER and res.input_tokens == 1234 and res.output_tokens == 210


def test_truncated_answer_is_an_error_not_bad_data(client):
    c, _, srv = client(stop_reason="max_tokens", text='{"case_title": "SEC v. Do')
    with pytest.raises(RuntimeError, match="max_tokens"):
        c.extract("s", "u", output_schema())
    srv.shutdown()
