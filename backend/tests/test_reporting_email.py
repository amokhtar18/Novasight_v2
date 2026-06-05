"""Tests for the SMTP email sender (app/reporting/email.py).

No socket is opened: ``smtplib.SMTP`` is patched so we assert the connection
parameters come from settings and the message is built with the attachment.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.config import SmtpSettings
from app.reporting.email import EmailAttachment, SmtpEmailSender


def _cfg() -> SmtpSettings:
    return SmtpSettings(
        host="smtp.example.test",
        port=2525,
        username="apiuser",
        password=SecretStr("s3cr3t"),
        use_tls=True,
        from_address="reports@example.test",
    )


def test_send_uses_settings_and_attaches_workbook() -> None:
    cfg = _cfg()
    sender = SmtpEmailSender(cfg)

    smtp_client = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_client

    with patch("app.reporting.email.smtplib.SMTP", return_value=smtp_ctx) as smtp_cls:
        sender.send(
            subject="[Analytica] Sales",
            recipients=["a@example.test", "b@example.test"],
            body="here is your report",
            attachment=EmailAttachment(filename="sales.xlsx", content=b"PK\x03\x04stuff"),
        )

    # Connection parameters come from settings, not literals.
    smtp_cls.assert_called_once_with("smtp.example.test", 2525)
    # STARTTLS is invoked with an explicit, verifying SSL context.
    smtp_client.starttls.assert_called_once()
    tls_context = smtp_client.starttls.call_args.kwargs["context"]
    import ssl

    assert isinstance(tls_context, ssl.SSLContext)
    assert tls_context.verify_mode == ssl.CERT_REQUIRED
    smtp_client.login.assert_called_once_with("apiuser", "s3cr3t")
    smtp_client.send_message.assert_called_once()

    sent_message = smtp_client.send_message.call_args.args[0]
    assert sent_message["From"] == "reports@example.test"
    assert sent_message["To"] == "a@example.test, b@example.test"
    assert sent_message["Subject"] == "[Analytica] Sales"
    # The workbook is attached.
    attachments = list(sent_message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "sales.xlsx"


def test_tls_verify_false_disables_verification() -> None:
    import ssl

    cfg = SmtpSettings(
        host="smtp.example.test",
        from_address="r@example.test",
        use_tls=True,
        tls_verify=False,
    )
    context = SmtpEmailSender(cfg)._tls_context()
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_send_without_recipients_is_rejected() -> None:
    with pytest.raises(ValueError, match="no recipients"):
        SmtpEmailSender(_cfg()).send(subject="x", recipients=[], body="y")
