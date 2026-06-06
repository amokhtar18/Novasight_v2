"""Tests for KPI alert channels (app/reporting/alerts/channels.py)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.reporting.alerts.channels import (
    AlertEvent,
    EmailAlertChannel,
    WebhookAlertChannel,
    WebhookTargetError,
    validate_webhook_url,
)


@dataclass
class _FakeEmailSender:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def send(self, *, subject: str, recipients: Any, body: str, attachment: Any = None) -> None:
        self.calls.append({"subject": subject, "recipients": list(recipients), "body": body})


def _event() -> AlertEvent:
    return AlertEvent(
        kpi_name="Revenue drop", tenant="tenant_alpha", value=42.0, comparator="<", threshold=100.0
    )


def test_email_channel_sends_via_sender() -> None:
    sender = _FakeEmailSender()
    channel = EmailAlertChannel(sender, ["ops@alpha.test"], "[NovaSight][ALERT] ")

    channel.send(_event())

    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["subject"] == "[NovaSight][ALERT] Revenue drop"
    assert call["recipients"] == ["ops@alpha.test"]
    assert "42.0" in call["body"]
    assert "< 100.0" in call["body"]


def test_webhook_channel_posts_json() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch("app.reporting.alerts.channels.httpx.post", return_value=response) as post:
        WebhookAlertChannel("https://hooks.example.test/kpi", 7.5).send(_event())

    post.assert_called_once()
    assert post.call_args.args[0] == "https://hooks.example.test/kpi"
    assert post.call_args.kwargs["timeout"] == 7.5
    # Redirects are not followed (a 30x must not bounce to an internal address).
    assert post.call_args.kwargs["follow_redirects"] is False
    payload = post.call_args.kwargs["json"]
    assert payload == {
        "kpi": "Revenue drop",
        "tenant": "tenant_alpha",
        "value": 42.0,
        "comparator": "<",
        "threshold": 100.0,
    }
    response.raise_for_status.assert_called_once()


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "ftp://example.test/x",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://127.0.0.1/admin",
        "http://localhost/admin",
        "http://10.0.0.5/internal",
        "https://[::1]/admin",
    ],
)
def test_webhook_url_validation_rejects_ssrf_targets(bad_url: str) -> None:
    # Rejected at construction, before any breach can trigger a request.
    with pytest.raises(WebhookTargetError):
        WebhookAlertChannel(bad_url, 5.0)


def test_webhook_url_validation_allows_external_https() -> None:
    assert validate_webhook_url("https://hooks.example.test/kpi").startswith("https://")
