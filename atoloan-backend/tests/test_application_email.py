"""
Unit tests for the applicant summary email (app/services/application_email.py,
app/integrations/ses_email.py).

Covers:
  1. send_email() — SES client called with sender/recipient/subject, raises on ClientError
  2. send_application_summary_email() — with a matched bank/term_options, includes credit
     score, bank name, and every term's rate in both bodies
  3. send_application_summary_email() — with no matched bank, falls back to a simpler email
  4. send_application_summary_email() — propagates SES failures (caller decides how to handle)
"""
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from app.integrations import ses_email as ses_email_module
from app.services import application_email as application_email_module
from app.services.application_email import send_application_summary_email
from app.integrations.ses_email import send_email


def _mock_ses_client(monkeypatch, send_email_mock=None) -> MagicMock:
    client = MagicMock()
    if send_email_mock is not None:
        client.send_email = send_email_mock
    monkeypatch.setattr(ses_email_module.boto3, "client", lambda *_, **__: client)
    return client


def _mock_settings(monkeypatch, sender="no-reply@atoloan.com", region="us-east-2") -> None:
    settings = MagicMock(ses_sender_email=sender, aws_region=region)
    monkeypatch.setattr(application_email_module, "get_settings", lambda: settings)


# ---------------------------------------------------------------------------
# 1. send_email() — SES integration
# ---------------------------------------------------------------------------

class TestSendEmail:
    def test_calls_ses_with_source_and_destination(self, monkeypatch) -> None:
        client = _mock_ses_client(monkeypatch)

        send_email(
            region="us-east-2",
            sender="no-reply@atoloan.com",
            to_address="applicant@example.com",
            subject="Subject",
            html_body="<p>hi</p>",
            text_body="hi",
        )

        client.send_email.assert_called_once()
        kwargs = client.send_email.call_args.kwargs
        assert kwargs["Source"] == "no-reply@atoloan.com"
        assert kwargs["Destination"] == {"ToAddresses": ["applicant@example.com"]}
        assert kwargs["Message"]["Subject"]["Data"] == "Subject"

    def test_raises_on_ses_client_error(self, monkeypatch) -> None:
        failing = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "MessageRejected", "Message": "Email address not verified"}},
                "SendEmail",
            )
        )
        _mock_ses_client(monkeypatch, send_email_mock=failing)

        try:
            send_email(
                region="us-east-2",
                sender="no-reply@atoloan.com",
                to_address="applicant@example.com",
                subject="Subject",
                html_body="<p>hi</p>",
                text_body="hi",
            )
            assert False, "expected ClientError to propagate"
        except ClientError:
            pass


# ---------------------------------------------------------------------------
# 2-4. send_application_summary_email() — content + best-effort contract
# ---------------------------------------------------------------------------

class TestSendApplicationSummaryEmail:
    def test_includes_credit_score_bank_and_all_term_rates(self, monkeypatch) -> None:
        _mock_settings(monkeypatch)
        client = _mock_ses_client(monkeypatch)

        best_offer = {
            "bank_name": "Example Credit Union",
            "program_name": "New Auto",
            "term_options": [
                {"term_in_months": 36, "interest_rate": "5.25%"},
                {"term_in_months": 60, "interest_rate": "5.75%"},
            ],
        }

        send_application_summary_email(
            to_address="applicant@example.com",
            first_name="Jane",
            credit_score=712,
            best_offer=best_offer,
        )

        kwargs = client.send_email.call_args.kwargs
        html = kwargs["Message"]["Body"]["Html"]["Data"]
        text = kwargs["Message"]["Body"]["Text"]["Data"]
        for body in (html, text):
            assert "712" in body
            assert "Example Credit Union" in body
            assert "36 months" in body and "5.25%" in body
            assert "60 months" in body and "5.75%" in body

    def test_no_best_offer_falls_back_to_simple_email(self, monkeypatch) -> None:
        _mock_settings(monkeypatch)
        client = _mock_ses_client(monkeypatch)

        send_application_summary_email(
            to_address="applicant@example.com",
            first_name="Jane",
            credit_score=650,
            best_offer=None,
        )

        kwargs = client.send_email.call_args.kwargs
        text = kwargs["Message"]["Body"]["Text"]["Data"]
        assert "650" in text
        assert "follow up" in text

    def test_propagates_ses_failure(self, monkeypatch) -> None:
        """Best-effort handling is the caller's job (e.g. findback's background
        task) — this function itself must not swallow SES errors."""
        _mock_settings(monkeypatch)
        failing = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "Throttling", "Message": "Rate exceeded"}}, "SendEmail"
            )
        )
        _mock_ses_client(monkeypatch, send_email_mock=failing)

        try:
            send_application_summary_email(
                to_address="applicant@example.com",
                first_name="Jane",
                credit_score=650,
                best_offer=None,
            )
            assert False, "expected ClientError to propagate"
        except ClientError:
            pass
