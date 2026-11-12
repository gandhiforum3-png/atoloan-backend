"""Sign-in code email: SES in deployed envs, a log line in local dev."""
import logging
from unittest.mock import MagicMock

import pytest

from app.core.config import get_settings
from app.integrations import email as email_module


@pytest.fixture
def ses(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(email_module.boto3, "client", lambda *a, **k: client)
    return client


def test_dev_mode_logs_instead_of_sending(monkeypatch, ses, caplog):
    monkeypatch.setattr(get_settings(), "app_env", "")
    monkeypatch.setattr(get_settings(), "ses_from_email", "")
    with caplog.at_level(logging.WARNING):
        email_module.send_login_code("jane@example.com", "123456", "en")
    assert "123456" in caplog.text  # dev log carries the code
    ses.send_email.assert_not_called()


def test_sends_through_ses_when_configured(monkeypatch, ses):
    monkeypatch.setattr(get_settings(), "app_env", "prod")
    monkeypatch.setattr(get_settings(), "ses_from_email", "no-reply@atoloans.com")
    email_module.send_login_code("jane@example.com", "123456", "en")
    kwargs = ses.send_email.call_args.kwargs
    assert kwargs["FromEmailAddress"] == "no-reply@atoloans.com"
    assert kwargs["Destination"] == {"ToAddresses": ["jane@example.com"]}
    assert "123456" in kwargs["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert kwargs["Content"]["Simple"]["Subject"]["Data"] == "Your Atoloans sign-in code"


def test_spanish_subject(monkeypatch, ses):
    monkeypatch.setattr(get_settings(), "app_env", "prod")
    monkeypatch.setattr(get_settings(), "ses_from_email", "no-reply@atoloans.com")
    email_module.send_login_code("jane@example.com", "123456", "es")
    assert ses.send_email.call_args.kwargs["Content"]["Simple"]["Subject"]["Data"] == "Tu código de acceso de Atoloans"


def test_deployed_without_sender_refuses(monkeypatch, ses):
    monkeypatch.setattr(get_settings(), "app_env", "prod")
    monkeypatch.setattr(get_settings(), "ses_from_email", "")
    with pytest.raises(RuntimeError):
        email_module.send_login_code("jane@example.com", "123456", "en")
    ses.send_email.assert_not_called()


def test_disabled_notice_carries_no_code(monkeypatch, ses):
    monkeypatch.setattr(get_settings(), "app_env", "prod")
    monkeypatch.setattr(get_settings(), "ses_from_email", "no-reply@atoloans.com")
    email_module.send_disabled_notice("jane@example.com", "es")
    content = ses.send_email.call_args.kwargs["Content"]["Simple"]
    assert content["Subject"]["Data"] == "Tu cuenta de Atoloans está desactivada"
    assert not any(ch.isdigit() for ch in content["Body"]["Text"]["Data"])
