"""Email delivery seam for the reporting worker.

The ``EmailSender`` Protocol is what the service depends on, so tests substitute an
in-memory recorder and never open a socket. ``SmtpEmailSender`` is the real
implementation; all of its connection parameters come from ``SmtpSettings`` (golden
rule 1 — no hardcoded host/credentials).

A rendered report is delivered as an email with the workbook as an attachment.
"""
from __future__ import annotations

import smtplib
import ssl
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.core.config import SmtpSettings
from app.reporting.excel import XLSX_CONTENT_TYPE


@dataclass(frozen=True)
class EmailAttachment:
    """A binary attachment: filename + bytes + MIME type."""

    filename: str
    content: bytes
    content_type: str = XLSX_CONTENT_TYPE


class EmailSender(Protocol):
    """Minimal email surface the reporting service depends on."""

    def send(
        self,
        *,
        subject: str,
        recipients: Sequence[str],
        body: str,
        attachment: EmailAttachment | None = None,
    ) -> None:
        """Send one message to ``recipients`` (with an optional attachment)."""
        ...


class SmtpEmailSender:
    """``EmailSender`` backed by ``smtplib``; configured entirely from settings."""

    def __init__(self, cfg: SmtpSettings) -> None:
        self._cfg = cfg

    def _build_message(
        self,
        *,
        subject: str,
        recipients: Sequence[str],
        body: str,
        attachment: EmailAttachment | None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._cfg.from_address
        message["To"] = ", ".join(recipients)
        message.set_content(body)
        if attachment is not None:
            maintype, _, subtype = attachment.content_type.partition("/")
            message.add_attachment(
                attachment.content,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.filename,
            )
        return message

    def send(
        self,
        *,
        subject: str,
        recipients: Sequence[str],
        body: str,
        attachment: EmailAttachment | None = None,
    ) -> None:
        if not recipients:
            raise ValueError("cannot send a report email with no recipients")
        message = self._build_message(
            subject=subject, recipients=recipients, body=body, attachment=attachment
        )
        with smtplib.SMTP(self._cfg.host, self._cfg.port) as client:
            if self._cfg.use_tls:
                client.starttls(context=self._tls_context())
            if self._cfg.username and self._cfg.password is not None:
                client.login(self._cfg.username, self._cfg.password.get_secret_value())
            client.send_message(message)

    def _tls_context(self) -> ssl.SSLContext:
        """Build the STARTTLS context from settings.

        Verification is on by default (secure). An internal/self-signed relay can
        supply a CA bundle, or — only when explicitly configured — disable
        verification; both are settings, never literals.
        """
        context = ssl.create_default_context(cafile=self._cfg.ca_bundle)
        if not self._cfg.tls_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context
