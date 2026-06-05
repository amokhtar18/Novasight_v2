"""Alert delivery channels for KPI breaches.

The ``AlertChannel`` protocol is what the service depends on, so tests substitute a
recorder. Two implementations ship: email (reusing the reporting ``EmailSender``)
and webhook (an HTTP POST). All connection parameters come from settings / the KPI
registry row — no literals (golden rule 1).
"""
from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.reporting.email import EmailSender


class WebhookTargetError(ValueError):
    """A webhook URL is not an allowed external target."""


def validate_webhook_url(url: str) -> str:
    """Reject webhook targets that are SSRF vectors before any request is made.

    Allows only ``http``/``https`` and refuses loopback, private, link-local,
    reserved, and multicast IP literals (e.g. the cloud metadata endpoint
    ``169.254.169.254`` or ``127.0.0.1``). Hostnames are allowed; combined with
    ``follow_redirects=False`` at call time this closes the obvious literal-target
    SSRF holes for operator-supplied URLs.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebhookTargetError(f"webhook scheme {parsed.scheme!r} is not allowed")
    host = parsed.hostname or ""
    if host in ("localhost", ""):
        raise WebhookTargetError("webhook host resolves to localhost")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url  # a hostname (not an IP literal) — allowed
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise WebhookTargetError(f"webhook host {host!r} is an internal address")
    return url


@dataclass(frozen=True)
class AlertEvent:
    """A breach occurrence — everything a channel needs to notify."""

    kpi_name: str
    tenant: str          # the tenant's public slug (not the internal DB name)
    value: float
    comparator: str
    threshold: float

    def summary(self) -> str:
        """A one-line human description of the breach."""
        return (
            f"KPI '{self.kpi_name}' breached: value {self.value} "
            f"{self.comparator} {self.threshold} (tenant {self.tenant})"
        )

    def as_payload(self) -> dict[str, object]:
        """The JSON body posted to a webhook channel."""
        return {
            "kpi": self.kpi_name,
            "tenant": self.tenant,
            "value": self.value,
            "comparator": self.comparator,
            "threshold": self.threshold,
        }


class AlertChannel(Protocol):
    """Minimal surface the alert service depends on."""

    def send(self, event: AlertEvent) -> None:
        """Deliver one breach notification."""
        ...


class EmailAlertChannel:
    """Deliver a breach as an email via the shared reporting ``EmailSender``."""

    def __init__(
        self, sender: EmailSender, recipients: Sequence[str], subject_prefix: str
    ) -> None:
        self._sender = sender
        self._recipients = list(recipients)
        self._subject_prefix = subject_prefix

    def send(self, event: AlertEvent) -> None:
        self._sender.send(
            subject=f"{self._subject_prefix}{event.kpi_name}",
            recipients=self._recipients,
            body=event.summary(),
        )


class WebhookAlertChannel:
    """Deliver a breach as an HTTP POST with a JSON body."""

    def __init__(self, url: str, timeout_seconds: float) -> None:
        # Validate at construction so a bad target fails before any breach fires.
        self._url = validate_webhook_url(url)
        self._timeout = timeout_seconds

    def send(self, event: AlertEvent) -> None:
        # ``follow_redirects=False`` so a 30x cannot bounce the request to an
        # internal address that passed the up-front host check.
        response = httpx.post(
            self._url,
            json=event.as_payload(),
            timeout=self._timeout,
            follow_redirects=False,
        )
        response.raise_for_status()
