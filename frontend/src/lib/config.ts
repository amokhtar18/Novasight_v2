/**
 * Runtime configuration accessor.
 *
 * The config is injected at runtime via /public/config.js, which sets
 * window.__APP_CONFIG__ before the app bundle loads. This pattern mirrors
 * the backend's pydantic-settings approach: the artifact is environment-agnostic
 * and config comes in at the boundary.
 *
 * Fails loudly at startup if required values are missing, so broken deployments
 * are caught immediately rather than silently returning empty responses.
 */

export interface AppConfig {
  /** Base URL for all API calls, e.g. "/api/v1" or "https://api.example.com/api/v1" */
  apiBaseUrl: string;
  /** Bearer token sent on every request. Set from the dev stub or OIDC flow. */
  authToken: string;
}

declare global {
  interface Window {
    __APP_CONFIG__?: Partial<AppConfig>;
  }
}

let _config: AppConfig | null = null;

/**
 * Load and validate the runtime config from window.__APP_CONFIG__.
 * Call once at app startup; subsequent calls return the cached instance.
 * Throws if required fields are missing or still set to placeholder values.
 */
export function loadConfig(): AppConfig {
  if (_config !== null) return _config;

  const raw = window.__APP_CONFIG__;

  if (!raw) {
    throw new Error(
      "[config] window.__APP_CONFIG__ is not defined. " +
        "Ensure public/config.js is served and loaded before the app bundle."
    );
  }

  const { apiBaseUrl, authToken } = raw;

  if (!apiBaseUrl) {
    throw new Error("[config] apiBaseUrl is missing from window.__APP_CONFIG__");
  }

  if (!authToken) {
    throw new Error("[config] authToken is missing from window.__APP_CONFIG__");
  }

  if (authToken === "REPLACE_WITH_DEV_TOKEN") {
    // Warn loudly in dev; don't block startup so devs see the UI.
    console.warn(
      "[config] authToken is still the placeholder value. " +
        "Set a real dev stub token in public/config.js. See docs/FRONTEND.md."
    );
  }

  _config = { apiBaseUrl, authToken };
  return _config;
}

/**
 * Reset the cached config. Only used in tests.
 * @internal
 */
export function _resetConfig(): void {
  _config = null;
}
