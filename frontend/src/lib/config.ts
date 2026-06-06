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
  /**
   * Optional pre-seeded bearer token (legacy dev-stub convenience). In normal
   * operation the token comes from the login flow, not config.js — so this is no
   * longer required and is ignored once the user signs in.
   */
  authToken?: string;
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

  // authToken is optional: the token normally comes from the login flow. A
  // leftover placeholder is treated as absent.
  const token =
    authToken && authToken !== "REPLACE_WITH_DEV_TOKEN" ? authToken : undefined;

  _config = { apiBaseUrl, authToken: token };
  return _config;
}

/**
 * Reset the cached config. Only used in tests.
 * @internal
 */
export function _resetConfig(): void {
  _config = null;
}
