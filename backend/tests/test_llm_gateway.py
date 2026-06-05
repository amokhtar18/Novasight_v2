"""Tests for the LLM gateway (Phase 4, Task 4.2).

Strategy
--------
All tests run entirely in-process.  The Anthropic SDK / transport is mocked at
the ``anthropic.AsyncAnthropic`` level using ``unittest.mock.AsyncMock`` and
``MagicMock``, so no network calls are made and no real API key is needed.

Acceptance criteria covered
-----------------------------
(a) Switching the model via settings (AI__MODEL) changes the outgoing model with
    no code change — the model sent to the provider equals the configured value.
(b) The API key never appears in logs — captured logging asserts the secret is absent.
(c) Provider selection returns the right provider and fails closed on unknown provider.
(d) Per-tenant override changes the effective model; default falls back to settings.
(e) Prompt template loading by name+version renders correctly; a missing template
    fails clearly with TemplateNotFoundError.

Additional paths
----------------
(f) AnthropicProvider maps SDK errors to LLMProviderError (no provider-specific leakage).
(g) LLMGateway fills in default temperature/max_tokens from settings when not supplied.
(h) close_llm_client() is idempotent.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.gateway.gateway import LLMGateway, close_llm_client, model_for_tenant
from app.ai.gateway.loader import (
    PromptLoader,
    TemplateNotFoundError,
    TemplateRenderError,
)
from app.ai.gateway.provider import LLMProviderError, LLMRequest, LLMResponse
from app.ai.gateway.providers.anthropic import AnthropicProvider
from app.ai.gateway.registry import build_provider, registered_providers
from app.core.config import AISettings
from app.tenancy.context import TenantContext

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

_FAKE_KEY = "sk-ant-test-not-a-real-key"


def _ai_settings(
    provider: str = "anthropic",
    model: str = "claude-test-model",
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> AISettings:
    """Build an AISettings instance with controlled values (no env needed)."""
    from pydantic import SecretStr

    s = MagicMock(spec=AISettings)
    s.provider = provider
    s.model = model
    s.temperature = temperature
    s.max_tokens = max_tokens
    s.api_key = SecretStr(_FAKE_KEY)
    s.prompt_template_dir = "prompts-test"  # relative; PromptLoader resolves via Path
    return s  # type: ignore[return-value]


def _make_tenant_ctx(slug: str = "acme") -> TenantContext:
    return TenantContext(
        tenant_id=str(uuid.uuid4()),
        iceberg_namespace=f"ns_{slug}",
        clickhouse_db=f"tenant_{slug}",
        dbt_schema=f"tenant_{slug}",
    )


def _make_sdk_message(
    model: str = "claude-test-model",
    text: str = "Hello!",
    input_tokens: int = 10,
    output_tokens: int = 5,
    stop_reason: str = "end_turn",
) -> MagicMock:
    """Build a mock anthropic.Message returned by the SDK."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    msg = MagicMock()
    msg.content = [block]
    msg.model = model
    msg.usage = usage
    msg.stop_reason = stop_reason
    return msg


def _make_anthropic_provider(
    model: str = "claude-test-model",
    response_text: str = "Answer.",
) -> tuple[AnthropicProvider, MagicMock]:
    """Return (AnthropicProvider, mock_messages_create) with a fake SDK client."""
    settings = _ai_settings(model=model)

    fake_message = _make_sdk_message(model=model, text=response_text)
    mock_create = AsyncMock(return_value=fake_message)

    with patch("anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages = MagicMock()
        instance.messages.create = mock_create
        instance.close = AsyncMock(return_value=None)

        provider = AnthropicProvider(settings)
        # Replace the internal client with the mock instance so calls go there.
        provider._client = instance

    return provider, mock_create


# ---------------------------------------------------------------------------
# (a) Model from settings flows through to provider — no hardcoding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_from_settings_is_sent_to_provider() -> None:
    """The model configured in settings is the one sent to the Anthropic API."""
    configured_model = "claude-configured-model"
    provider, mock_create = _make_anthropic_provider(model=configured_model)
    settings = _ai_settings(model=configured_model)
    ctx = _make_tenant_ctx()

    gateway = LLMGateway(provider=provider, ai_settings=settings)  # type: ignore[arg-type]
    await gateway.complete(
        LLMRequest(system="sys", user_message="hello"),
        ctx=ctx,
    )

    mock_create.assert_awaited_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == configured_model


@pytest.mark.asyncio
async def test_changing_model_setting_changes_outgoing_model() -> None:
    """When AI__MODEL changes, the outgoing model changes with no code change."""
    model_a = "claude-model-a"
    model_b = "claude-model-b"

    ctx = _make_tenant_ctx()

    # First call with model_a
    provider_a, create_a = _make_anthropic_provider(model=model_a)
    await LLMGateway(provider=provider_a, ai_settings=_ai_settings(model=model_a)).complete(  # type: ignore[arg-type]
        LLMRequest(system="s", user_message="q"), ctx=ctx
    )
    assert create_a.call_args.kwargs["model"] == model_a

    # Second call with model_b (simulates AI__MODEL env change)
    provider_b, create_b = _make_anthropic_provider(model=model_b)
    await LLMGateway(provider=provider_b, ai_settings=_ai_settings(model=model_b)).complete(  # type: ignore[arg-type]
        LLMRequest(system="s", user_message="q"), ctx=ctx
    )
    assert create_b.call_args.kwargs["model"] == model_b

    # The two calls used different models.
    assert create_a.call_args.kwargs["model"] != create_b.call_args.kwargs["model"]


# ---------------------------------------------------------------------------
# (b) API key never appears in logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_key_never_appears_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    """The API key must not appear in any log record emitted by the gateway."""
    provider, _ = _make_anthropic_provider()
    settings = _ai_settings()
    ctx = _make_tenant_ctx()

    with caplog.at_level(logging.DEBUG, logger="app.ai"):
        gateway = LLMGateway(provider=provider, ai_settings=settings)  # type: ignore[arg-type]
        await gateway.complete(
            LLMRequest(system="sys", user_message="hello"),
            ctx=ctx,
        )

    # The fake key must not appear in any log record.
    for record in caplog.records:
        assert _FAKE_KEY not in record.getMessage(), (
            f"API key found in log record: {record.getMessage()!r}"
        )


@pytest.mark.asyncio
async def test_api_key_absent_from_provider_error_message() -> None:
    """LLMProviderError messages must not contain the API key."""
    from pydantic import SecretStr

    settings = MagicMock(spec=AISettings)
    settings.provider = "anthropic"
    settings.model = "m"
    settings.temperature = 0.0
    settings.max_tokens = 512
    settings.api_key = SecretStr(_FAKE_KEY)

    import anthropic as sdk

    # Simulate an auth error from the SDK.
    with patch("anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages = MagicMock()
        instance.messages.create = AsyncMock(
            side_effect=sdk.AuthenticationError(
                message="invalid x-api-key",
                response=MagicMock(status_code=401),
                body={"error": {"message": "invalid x-api-key"}},
            )
        )
        instance.close = AsyncMock(return_value=None)

        provider = AnthropicProvider(settings)  # type: ignore[arg-type]
        provider._client = instance

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.complete(
            LLMRequest(system="s", user_message="q", model="m", temperature=0.0, max_tokens=10)
        )

    assert _FAKE_KEY not in str(exc_info.value)


# ---------------------------------------------------------------------------
# (c) Provider selection — correct provider returned, unknown fails closed
# ---------------------------------------------------------------------------


def test_build_provider_returns_anthropic_for_anthropic_setting() -> None:
    """build_provider('anthropic') returns an AnthropicProvider instance."""
    settings = _ai_settings(provider="anthropic")

    with patch("anthropic.AsyncAnthropic"):
        provider = build_provider(settings)  # type: ignore[arg-type]

    assert isinstance(provider, AnthropicProvider)


def test_build_provider_fails_closed_on_unknown_provider() -> None:
    """build_provider raises ValueError for an unrecognised provider name."""
    settings = _ai_settings(provider="unicorn-ai")

    with pytest.raises(ValueError, match="unicorn-ai"):
        build_provider(settings)  # type: ignore[arg-type]


def test_build_provider_error_lists_known_providers() -> None:
    """The ValueError for an unknown provider lists the known providers."""
    settings = _ai_settings(provider="unknown")

    with pytest.raises(ValueError) as exc_info:
        build_provider(settings)  # type: ignore[arg-type]

    message = str(exc_info.value)
    for name in registered_providers():
        assert name in message


def test_registered_providers_includes_anthropic() -> None:
    assert "anthropic" in registered_providers()


# ---------------------------------------------------------------------------
# (d) Per-tenant model override
# ---------------------------------------------------------------------------


def test_model_for_tenant_returns_default_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_for_tenant returns settings.ai.model when no override is given."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    env = _minimal_complete_env(ai_model="claude-default-model")
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    ctx = _make_tenant_ctx()
    result = model_for_tenant(ctx, ai_settings=get_settings().ai, override=None)

    assert result == "claude-default-model"
    get_settings.cache_clear()


def test_model_for_tenant_uses_override_when_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_for_tenant returns the override when one is explicitly supplied."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    env = _minimal_complete_env(ai_model="claude-default-model")
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    ctx = _make_tenant_ctx()
    result = model_for_tenant(
        ctx, ai_settings=get_settings().ai, override="claude-tenant-specific-model"
    )

    assert result == "claude-tenant-specific-model"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gateway_complete_uses_model_override_over_settings() -> None:
    """Passing model_override to gateway.complete uses that model, not settings."""
    default_model = "claude-default"
    override_model = "claude-override"

    provider, mock_create = _make_anthropic_provider(model=override_model)
    # Settings says default_model, but we pass override_model explicitly.
    settings = _ai_settings(model=default_model)
    ctx = _make_tenant_ctx()

    gateway = LLMGateway(provider=provider, ai_settings=settings)  # type: ignore[arg-type]
    await gateway.complete(
        LLMRequest(system="s", user_message="q"),
        ctx=ctx,
        model_override=override_model,
    )

    assert mock_create.call_args.kwargs["model"] == override_model


@pytest.mark.asyncio
async def test_gateway_complete_uses_settings_model_without_override() -> None:
    """Without model_override, gateway.complete uses settings.ai.model."""
    default_model = "claude-from-settings"

    provider, mock_create = _make_anthropic_provider(model=default_model)
    settings = _ai_settings(model=default_model)
    ctx = _make_tenant_ctx()

    gateway = LLMGateway(provider=provider, ai_settings=settings)  # type: ignore[arg-type]
    await gateway.complete(
        LLMRequest(system="s", user_message="q"),
        ctx=ctx,
    )

    assert mock_create.call_args.kwargs["model"] == default_model


# ---------------------------------------------------------------------------
# (e) Prompt template loading and rendering
# ---------------------------------------------------------------------------


def test_prompt_loader_load_returns_raw_text(tmp_path: Path) -> None:
    """load() returns the raw template text without substitution."""
    tmpl_dir = tmp_path / "nl_to_sql" / "v1"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "system.txt").write_text("Hello {name}!", encoding="utf-8")

    loader = PromptLoader(str(tmp_path))
    text = loader.load("nl_to_sql", "v1", "system")

    assert text == "Hello {name}!"


def test_prompt_loader_render_substitutes_variables(tmp_path: Path) -> None:
    """render() performs {variable} substitution and returns the rendered string."""
    tmpl_dir = tmp_path / "nl_to_sql" / "v1"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "system.txt").write_text(
        "Tenant: {tenant_id}. Context: {semantic_context}.", encoding="utf-8"
    )

    loader = PromptLoader(str(tmp_path))
    rendered = loader.render(
        "nl_to_sql", "v1", "system",
        tenant_id="acme",
        semantic_context="sales metrics",
    )

    assert rendered == "Tenant: acme. Context: sales metrics."


def test_prompt_loader_missing_template_raises_template_not_found(tmp_path: Path) -> None:
    """Loading a non-existent template raises TemplateNotFoundError."""
    loader = PromptLoader(str(tmp_path))

    with pytest.raises(TemplateNotFoundError) as exc_info:
        loader.load("no_such_template", "v99", "system")

    err = exc_info.value
    assert err.name == "no_such_template"
    assert err.version == "v99"
    assert err.filename == "system"
    assert "no_such_template" in str(err)


def test_prompt_loader_rejects_path_traversal(tmp_path: Path) -> None:
    """A name/version that escapes the template root is rejected (no arbitrary read).

    Guards against the loader being wired to an API parameter later: a ``..``
    segment must fail closed rather than read a file outside prompt_template_dir.
    """
    root = tmp_path / "prompts"
    root.mkdir()
    loader = PromptLoader(str(root))

    # A traversal in either the name or the version must escape-check and raise.
    with pytest.raises(ValueError, match="escapes"):
        loader.load("../../etc", "v1", "passwd")
    with pytest.raises(ValueError, match="escapes"):
        loader.load("nl_to_sql", "../../..", "system")


def test_prompt_loader_missing_variable_raises_template_render_error(tmp_path: Path) -> None:
    """render() raises TemplateRenderError when a required placeholder is absent."""
    tmpl_dir = tmp_path / "insights" / "v1"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "system.txt").write_text("Result: {result_set}.", encoding="utf-8")

    loader = PromptLoader(str(tmp_path))

    with pytest.raises(TemplateRenderError) as exc_info:
        loader.render("insights", "v1", "system")  # missing result_set

    assert exc_info.value.missing_key == "result_set"


def test_prompt_loader_default_filename_is_system(tmp_path: Path) -> None:
    """load() defaults to 'system.txt' when filename is omitted."""
    tmpl_dir = tmp_path / "nl_to_sql" / "v1"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "system.txt").write_text("default file content", encoding="utf-8")

    loader = PromptLoader(str(tmp_path))
    assert loader.load("nl_to_sql", "v1") == "default file content"


def test_prompt_loader_can_load_user_template(tmp_path: Path) -> None:
    """load() can load a 'user.txt' template by name."""
    tmpl_dir = tmp_path / "nl_to_sql" / "v1"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "user.txt").write_text("Question: {question}", encoding="utf-8")

    loader = PromptLoader(str(tmp_path))
    rendered = loader.render("nl_to_sql", "v1", "user", question="Show revenue by region")

    assert rendered == "Question: Show revenue by region"


# ---------------------------------------------------------------------------
# (f) AnthropicProvider error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_provider_auth_error_raises_llm_provider_error() -> None:
    """AuthenticationError from the SDK is wrapped in LLMProviderError."""
    import anthropic as sdk

    provider, _ = _make_anthropic_provider()
    provider._client.messages.create = AsyncMock(
        side_effect=sdk.AuthenticationError(
            message="bad key",
            response=MagicMock(status_code=401),
            body={},
        )
    )

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.complete(
            LLMRequest(system="s", user_message="q", model="m", temperature=0.0, max_tokens=10)
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.provider == "anthropic"


@pytest.mark.asyncio
async def test_anthropic_provider_rate_limit_raises_llm_provider_error() -> None:
    """RateLimitError from the SDK is wrapped in LLMProviderError(status=429)."""
    import anthropic as sdk

    provider, _ = _make_anthropic_provider()
    provider._client.messages.create = AsyncMock(
        side_effect=sdk.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body={},
        )
    )

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.complete(
            LLMRequest(system="s", user_message="q", model="m", temperature=0.0, max_tokens=10)
        )

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_anthropic_provider_connection_error_raises_llm_provider_error() -> None:
    """APIConnectionError from the SDK is wrapped in LLMProviderError."""
    import anthropic as sdk

    provider, _ = _make_anthropic_provider()
    provider._client.messages.create = AsyncMock(
        side_effect=sdk.APIConnectionError(request=MagicMock())
    )

    with pytest.raises(LLMProviderError):
        await provider.complete(
            LLMRequest(system="s", user_message="q", model="m", temperature=0.0, max_tokens=10)
        )


@pytest.mark.asyncio
async def test_anthropic_provider_returns_typed_response() -> None:
    """A successful call returns a typed LLMResponse with text, model, usage."""
    provider, _ = _make_anthropic_provider(
        model="claude-test-model", response_text="  Insight text.  "
    )

    resp = await provider.complete(
        LLMRequest(
            system="You are helpful.",
            user_message="Summarise",
            model="claude-test-model",
            temperature=0.0,
            max_tokens=100,
        )
    )

    assert isinstance(resp, LLMResponse)
    assert resp.text == "Insight text."  # stripped
    assert resp.model == "claude-test-model"
    assert "input_tokens" in resp.usage
    assert "output_tokens" in resp.usage


# ---------------------------------------------------------------------------
# (g) Gateway fills defaults from settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_fills_temperature_from_settings_when_not_in_request() -> None:
    """Gateway substitutes settings.ai.temperature when request.temperature is None."""
    provider, mock_create = _make_anthropic_provider()
    settings = _ai_settings(temperature=0.7, max_tokens=256)
    ctx = _make_tenant_ctx()

    gateway = LLMGateway(provider=provider, ai_settings=settings)  # type: ignore[arg-type]
    await gateway.complete(
        LLMRequest(system="s", user_message="q"),  # temperature=None
        ctx=ctx,
    )

    assert mock_create.call_args.kwargs["temperature"] == 0.7


@pytest.mark.asyncio
async def test_gateway_fills_max_tokens_from_settings_when_not_in_request() -> None:
    """Gateway substitutes settings.ai.max_tokens when request.max_tokens is None."""
    provider, mock_create = _make_anthropic_provider()
    settings = _ai_settings(temperature=0.0, max_tokens=999)
    ctx = _make_tenant_ctx()

    gateway = LLMGateway(provider=provider, ai_settings=settings)  # type: ignore[arg-type]
    await gateway.complete(
        LLMRequest(system="s", user_message="q"),  # max_tokens=None
        ctx=ctx,
    )

    assert mock_create.call_args.kwargs["max_tokens"] == 999


@pytest.mark.asyncio
async def test_gateway_respects_request_level_temperature_override() -> None:
    """Request-level temperature takes precedence over settings default."""
    provider, mock_create = _make_anthropic_provider()
    settings = _ai_settings(temperature=0.0)
    ctx = _make_tenant_ctx()

    gateway = LLMGateway(provider=provider, ai_settings=settings)  # type: ignore[arg-type]
    await gateway.complete(
        LLMRequest(system="s", user_message="q", temperature=0.9),
        ctx=ctx,
    )

    assert mock_create.call_args.kwargs["temperature"] == 0.9


# ---------------------------------------------------------------------------
# (h) close_llm_client is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_llm_client_is_idempotent() -> None:
    """close_llm_client() can be called multiple times without error."""
    # Reset any global state from other tests.
    import app.ai.gateway.gateway as gw_module

    gw_module._provider = None

    await close_llm_client()  # no-op when never initialised
    await close_llm_client()  # second call also safe


@pytest.mark.asyncio
async def test_close_llm_client_calls_provider_close() -> None:
    """close_llm_client() calls provider.close() exactly once."""
    import app.ai.gateway.gateway as gw_module

    mock_provider = MagicMock()
    mock_provider.close = AsyncMock()
    gw_module._provider = mock_provider  # type: ignore[assignment]

    await close_llm_client()

    mock_provider.close.assert_awaited_once()
    assert gw_module._provider is None  # cleared after close


# ---------------------------------------------------------------------------
# Helper: minimal env dict for settings tests
# ---------------------------------------------------------------------------


def _minimal_complete_env(ai_model: str = "claude-test-model") -> dict[str, str]:
    """Return a minimal environment dict that satisfies all Settings required fields."""
    return {
        "ENVIRONMENT": "test",
        "POSTGRES__HOST": "localhost",
        "POSTGRES__USER": "test",
        "POSTGRES__PASSWORD": "test",
        "POSTGRES__DB": "test",
        "REDIS__HOST": "localhost",
        "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
        "OBJECT_STORE__ACCESS_KEY": "testkey",
        "OBJECT_STORE__SECRET_KEY": "testsecret",
        "OBJECT_STORE__BUCKET": "test-bucket",
        "ICEBERG__CATALOG_URI": "http://localhost:8181",
        "ICEBERG__WAREHOUSE": "s3://test/warehouse",
        "CLICKHOUSE__HOST": "localhost",
        "CLICKHOUSE__PASSWORD": "test",
        "AI__PROVIDER": "anthropic",
        "AI__MODEL": ai_model,
        "AI__API_KEY": _FAKE_KEY,
        "AI__PROMPT_TEMPLATE_DIR": "prompts",
        "CUBE__BASE_URL": "http://cube:4000",
        "CUBE__API_SECRET": "a-random-secret-of-at-least-32-chars",
        "AUTH__DEV_STUB": "true",
        "AUTH__DEV_STUB_SECRET": "test-secret-at-least-32-chars-long!",
        "SEED_TENANT__SLUG": "local",
        "SEED_TENANT__NAME": "Local",
        "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
    }
