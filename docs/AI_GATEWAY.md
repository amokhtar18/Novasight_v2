# AI Gateway

> Phase 4, Task 4.2 — provider-agnostic LLM gateway under `backend/app/ai/gateway/`.

The gateway is the **single entry point** for every LLM call in Analytica.  No other
module in `app/ai/` imports or references provider-specific SDK types.

---

## Architecture

```
app/ai/gateway/
  __init__.py           — public re-exports (LLMGateway, LLMRequest, LLMResponse, …)
  provider.py           — LLMProvider protocol, LLMRequest, LLMResponse, LLMProviderError
  registry.py           — provider registry: name → factory callable
  gateway.py            — LLMGateway facade, model_for_tenant, close_llm_client
  loader.py             — PromptLoader (versioned template files)
  providers/
    __init__.py
    anthropic.py        — AnthropicProvider (AsyncAnthropic + Messages API)
```

### Four-stage pattern (nl-to-sql-grounding skill)

Every AI feature that uses this gateway follows:

1. **Ground** — pull metrics/dimensions from the Cube semantic layer (tenant-scoped).
2. **Generate** — call `LLMGateway.complete()` with a versioned prompt template.
3. **Validate** — parse and validate the output (SQL allow-list, chart schema, etc.).
4. **Execute / return** — run validated read-only queries or return the validated spec.

---

## Public interface

### `LLMRequest`

```python
class LLMRequest(BaseModel):
    system: str                    # system-role instruction
    user_message: str              # user-turn content
    model: str | None = None       # filled by gateway from model_for_tenant()
    temperature: float | None = None  # falls back to AI__TEMPERATURE
    max_tokens: int | None = None  # falls back to AI__MAX_TOKENS
```

### `LLMResponse`

```python
class LLMResponse(BaseModel):
    text: str                      # generated text, stripped
    model: str                     # model that produced the response (from provider)
    usage: dict[str, int]          # {"input_tokens": N, "output_tokens": N}
    raw_metadata: dict[str, Any]   # provider-specific metadata (e.g. stop_reason)
```

### `LLMGateway.complete()`

```python
async def complete(
    self,
    request: LLMRequest,
    *,
    ctx: TenantContext,
    model_override: str | None = None,
) -> LLMResponse: ...
```

The `TenantContext` is required for logging and is the future hook for per-tenant
model selection.  It is never forwarded to the provider.

### FastAPI dependency

```python
@router.post("/ask")
async def ask(
    ctx: TenantContext = Depends(get_tenant_context),
    gateway: LLMGateway = Depends(get_llm_gateway),
) -> str:
    resp = await gateway.complete(
        LLMRequest(system="You are a helpful analyst.", user_message="…"),
        ctx=ctx,
    )
    return resp.text
```

---

## Configuration knobs

All config comes from the `AI__*` env var group (see `docs/CONFIGURATION.md`).
**Nothing is hardcoded.**

| Env var | Type | Default | Purpose |
|---|---|---|---|
| `AI__PROVIDER` | str | — | Provider name: `"anthropic"` |
| `AI__MODEL` | str | — | Default model id sent to the provider |
| `AI__API_KEY` | SecretStr | — | Provider API key (never logged) |
| `AI__TEMPERATURE` | float | `0.0` | Sampling temperature |
| `AI__MAX_TOKENS` | int | `1024` | Max tokens per completion |
| `AI__PROMPT_TEMPLATE_DIR` | str | — | Directory containing versioned prompt templates |

No new env vars were added in this task — all settings were already present in
`AISettings` from Task 4.1 groundwork.

---

## Per-tenant model selection

```python
model_for_tenant(ctx: TenantContext, *, override: str | None = None, ai_settings: AISettings | None = None) -> str
```

Resolution order:
1. `override` if non-None — an explicit per-request or per-tenant model id.
2. `ai_settings.model` (or `get_settings().ai.model`) — the `AI__MODEL` default.

`LLMGateway.complete()` exposes this as the `model_override` keyword argument,
threading it through from the API boundary.  This is the **designated plug-in point**
for a future per-tenant model-config lookup: when that feature lands, replace the
`ai_settings.model` fallback with a database lookup keyed on `ctx.tenant_id`.  No
callers need to change — they already pass the `TenantContext`.

---

## Prompt template layout

Templates live under `AI__PROMPT_TEMPLATE_DIR`:

```
<prompt_template_dir>/
  nl_to_sql/
    v1/
      system.txt       ← system-role prompt with {placeholders}
      user.txt         ← user-turn template
  insights/
    v1/
      system.txt
  …
```

Naming convention: `<feature-name>/<vN>/<role>.txt`

Versioning policy: increment `v2`, `v3`, etc. when you change a template in a
way that would alter LLM behaviour.  Old versions remain on disk so running
deployments are not affected by a new checkout.

### Loader API

```python
loader = PromptLoader(prompt_template_dir=settings.ai.prompt_template_dir)

# Raw load (no substitution):
raw = loader.load("nl_to_sql", "v1", "system")

# Render with variables:
rendered = loader.render(
    "nl_to_sql", "v1", "system",
    tenant_id="acme",
    semantic_context="<metrics/dimensions>",
    max_rows="10000",
)
```

Errors:
- `TemplateNotFoundError` — file does not exist (includes the full resolved path).
- `TemplateRenderError` — a required `{placeholder}` was not supplied.

FastAPI dependency: `get_prompt_loader` (wired from `settings.ai.prompt_template_dir`).

---

## No-keys-in-logs guarantee

The API key is read via `SecretStr.get_secret_value()` exactly once — inline in
`AnthropicProvider.__init__()`, not bound to a named attribute.  The result is
passed directly to the `AsyncAnthropic` constructor.  After construction:

- The key is held internally by the SDK client only; it is not accessible via any
  attribute on `AnthropicProvider`.
- Error messages in `LLMProviderError` contain only the HTTP status code and a
  generic label (e.g. `"Anthropic authentication failed — check AI__API_KEY"`).
  The raw SDK exception is chained via `__cause__` for structured logging but must
  not be forwarded to clients.
- Gateway-level log records include only: `tenant_id`, `model`, `temperature`,
  `max_tokens`, and token counts from the response.  No prompt text, no key.
- Tests assert that `_FAKE_KEY` is absent from all captured log records for every
  gateway call (acceptance criterion b).

---

## Provider selection (fail-closed)

The registry in `gateway/registry.py` maps provider name strings to factories:

```python
_REGISTRY: dict[str, ProviderFactory] = {
    "anthropic": _anthropic_factory,
}
```

`build_provider(ai_settings)` raises `ValueError` at startup if
`settings.ai.provider` is not in the registry — the process will not start with
an unknown provider.

Adding a new provider:
1. Create `providers/<name>.py` implementing the `LLMProvider` protocol.
2. Add one line to `_REGISTRY` in `registry.py`.
3. No other files change.

---

## Lifespan shutdown

`close_llm_client()` is wired into the FastAPI lifespan shutdown in `app/main.py`
(alongside the existing `close_http_client()` for the Cube semantic layer):

```python
# app/main.py lifespan shutdown
await close_http_client()   # Cube HTTP client
await close_llm_client()    # LLM provider HTTP client
```

It is idempotent — safe to call even if the provider was never instantiated.

---

## Testing

Tests are in `backend/tests/test_llm_gateway.py`.  The Anthropic SDK transport is
mocked via `AsyncMock` — no real network calls.  Coverage:

- **(a)** `AI__MODEL` setting flows through to provider, and changing it changes the
  outgoing model with no code change.
- **(b)** API key is absent from all log records during a gateway call.
- **(c)** `build_provider("anthropic")` returns an `AnthropicProvider`; unknown
  provider name raises `ValueError` listing known providers.
- **(d)** `model_override` in `gateway.complete()` overrides the default; omitting
  it falls back to `settings.ai.model`.
- **(e)** `PromptLoader.render()` renders correctly; missing template raises
  `TemplateNotFoundError`; missing placeholder raises `TemplateRenderError`.
- SDK auth/rate-limit/connection errors are wrapped in `LLMProviderError` without
  leaking provider-specific types or the API key.
- `close_llm_client()` is idempotent.
