"""
/ratesheetuploader with a stubbed Claude client — no network, no API key needed.
"""
import base64
import types

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models.rate_sheet import CreditUnionRateSheet
from app.services import rate_sheet_parser

PDF = b"%PDF-1.4 fake"
SHEET = CreditUnionRateSheet.model_validate(
    {"credit_union_info": {"name": "Test CU"}, "loan_programs": [{"program_name": "New < 2 Years"}]}
)


def _message(stop_reason="end_turn", parsed=SHEET):
    return types.SimpleNamespace(stop_reason=stop_reason, stop_details=None, parsed_output=parsed, _request_id="req_test")


@pytest.fixture
def stub_claude(monkeypatch):
    """Returns (set_message, sent_kwargs): set the fake final message, inspect what was sent."""
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
    state = {"message": _message(), "sent": {}}

    class FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_final_message(self):
            return state["message"]

    class FakeClient:
        def __init__(self, **_):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._stream))

        def _stream(self, **kwargs):
            state["sent"].update(kwargs)
            return FakeStream()

    monkeypatch.setattr(rate_sheet_parser.anthropic, "AsyncAnthropic", FakeClient)
    return lambda m: state.update(message=m), state["sent"]


def _upload(name="cu.pdf", content=PDF, content_type="application/pdf"):
    response = TestClient(app).post(
        "/ratesheetuploader",
        files={"file": (name, content, content_type)},
        headers={"X-Service-Token": "test-service-token"},
    )
    assert response.status_code == 200
    return response.json()["files"][0]


def test_pdf_goes_to_claude_as_document_and_returns_rate_sheet(stub_claude):
    _, sent = stub_claude
    result = _upload()

    assert result == {"filename": "cu.pdf", "parse_error": None, "rate_sheet": SHEET.model_dump()}
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_format"] is CreditUnionRateSheet
    assert sent["fallbacks"] == "default"
    document, year = sent["messages"][0]["content"]
    assert document["type"] == "document" and base64.b64decode(document["source"]["data"]) == PDF
    assert year["text"].startswith("CURRENT_YEAR = ")


@pytest.mark.parametrize(
    "message, expected_error",
    [
        (_message("refusal"), "declined"),
        (_message("max_tokens"), "truncated"),
        (_message(parsed=None), "no structured"),
    ],
)
def test_unusable_responses_become_parse_errors(stub_claude, message, expected_error):
    set_message, _ = stub_claude
    set_message(message)
    result = _upload()

    assert result["rate_sheet"] is None
    assert expected_error in result["parse_error"]


def test_non_pdf_is_not_sent(stub_claude):
    _, sent = stub_claude
    assert _upload("x.txt", b"hi", "text/plain") == {"filename": "x.txt", "parse_error": None, "rate_sheet": None}
    assert not sent


@pytest.mark.parametrize("token", [None, "wrong"])
def test_ratesheetuploader_requires_service_token(token):
    headers = {"X-Service-Token": token} if token else {}
    response = TestClient(app).post("/ratesheetuploader", files={"file": ("cu.pdf", PDF, "application/pdf")}, headers=headers)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", [("get", "/credit-unions"), ("delete", "/credit-unions/1"), ("post", "/update")])
def test_lender_routes_require_service_token(method, path):
    assert getattr(TestClient(app), method)(path).status_code == 401


def test_lender_routes_fail_closed_when_token_unset(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "service_token", "")
    assert TestClient(app).get("/credit-unions", headers={"X-Service-Token": ""}).status_code == 401
