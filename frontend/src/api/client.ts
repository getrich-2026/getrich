const BASE_URL = "/v1";

/** Standard API response envelope: { code, message, data, timestamp, request_id }. */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
  timestamp: number;
  request_id: string;
}

/** Standard paginated response envelope from the backend. */
export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Minimal error shape returned by the API. */
export interface ApiError {
  detail: string;
}

export class ApiClientError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
  }
}

// ---------------------------------------------------------------------------
// Auth token management (in-memory + sessionStorage)
// ---------------------------------------------------------------------------

const TOKEN_KEY = "getrich_access_token";
const USER_KEY = "getrich_user";
const REFRESH_KEY = "getrich_refresh_token";

import type { UserInfo } from "./auth";

let _cachedToken: string | null = null;
let _cachedUser: UserInfo | null = null;
let _cachedRefreshToken: string | null = null;

/** Return the current JWT access token, or null if not logged in. */
export function getAccessToken(): string | null {
  if (_cachedToken) return _cachedToken;
  _cachedToken = sessionStorage.getItem(TOKEN_KEY);
  return _cachedToken;
}

/** Persist a new access token and update the in-memory cache. */
export function setAccessToken(token: string): void {
  _cachedToken = token;
  sessionStorage.setItem(TOKEN_KEY, token);
}

/** Clear the access token (logout). */
export function clearAccessToken(): void {
  _cachedToken = null;
  sessionStorage.removeItem(TOKEN_KEY);
}

// ---------------------------------------------------------------------------
// User info helpers (in-memory + sessionStorage)
// ---------------------------------------------------------------------------

/** Return the stored user info, or null if not logged in. */
export function getStoredUser(): UserInfo | null {
  if (_cachedUser) return _cachedUser;
  const raw = sessionStorage.getItem(USER_KEY);
  if (raw) {
    try {
      _cachedUser = JSON.parse(raw) as UserInfo;
    } catch {
      _cachedUser = null;
    }
  }
  return _cachedUser;
}

/** Persist user info and update the in-memory cache. */
export function setStoredUser(user: UserInfo): void {
  _cachedUser = user;
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

/** Clear stored user info (logout). */
export function clearStoredUser(): void {
  _cachedUser = null;
  sessionStorage.removeItem(USER_KEY);
}

// ---------------------------------------------------------------------------
// Refresh token helpers (in-memory + localStorage — survives tab close)
// ---------------------------------------------------------------------------

/** Return the current refresh token, or null if not available. */
export function getRefreshToken(): string | null {
  if (_cachedRefreshToken) return _cachedRefreshToken;
  _cachedRefreshToken = localStorage.getItem(REFRESH_KEY);
  return _cachedRefreshToken;
}

/** Persist a new refresh token and update the in-memory cache. */
export function setRefreshToken(token: string): void {
  _cachedRefreshToken = token;
  localStorage.setItem(REFRESH_KEY, token);
}

/** Clear the refresh token (logout). */
export function clearRefreshToken(): void {
  _cachedRefreshToken = null;
  localStorage.removeItem(REFRESH_KEY);
}

/**
 * Core fetch with Bearer token injection. Returns the raw Response.
 * Separated from apiFetch so the 401 interceptor can retry cleanly and so
 * non-JSON endpoints (e.g. binary downloads) can reuse the same auth
 * header injection.
 */
export async function _fetchWithAuth(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return fetch(`${BASE_URL}${path}`, { ...init, headers });
}

/**
 * Minimal fetch without auth headers — used for the refresh call itself
 * to avoid infinite loops.
 */
async function _fetchRaw(path: string, init?: RequestInit): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  return fetch(`${BASE_URL}${path}`, { ...init, headers });
}

/**
 * Thin wrapper around `fetch`. Builds the full URL from `BASE_URL + path`,
 * sets JSON headers (including Authorization if a token exists), and handles
 * non-2xx responses.
 *
 * On 401, attempts a silent refresh using the stored refresh token.
 * If refresh succeeds, retries the original request.
 * If refresh fails or no refresh token exists, clears auth state and redirects.
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await _fetchWithAuth(path, init);

  // 401 interceptor — only for authenticated endpoints
  if (res.status === 401 && path !== "/auth/refresh" && path !== "/auth/login") {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        const refreshRes = await _fetchRaw("/auth/refresh", {
          method: "POST",
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (refreshRes.ok) {
          const refreshBody = (await refreshRes.json()) as {
            code: number;
            data: {
              access_token: string;
              refresh_token: string;
              user: UserInfo;
            };
          };
          setAccessToken(refreshBody.data.access_token);
          setRefreshToken(refreshBody.data.refresh_token);
          setStoredUser(refreshBody.data.user);
          // Retry the original request with new token
          return _parseResponse<T>(await _fetchWithAuth(path, init));
        }
      } catch {
        /* refresh network failure — fall through to clear auth */
      }
    }
    // Refresh failed or no refresh token — clear auth state and redirect
    clearAccessToken();
    clearRefreshToken();
    clearStoredUser();
    window.location.href = "/login";
    throw new ApiClientError(401, "session expired, please log in again");
  }

  return _parseResponse<T>(res);
}

/** Parse a non-401 response body, throwing ApiClientError on failure. */
async function _parseResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as ApiError;
      detail = body.detail ?? detail;
    } catch {
      /* ignore parse failures */
    }
    throw new ApiClientError(res.status, detail);
  }
  return res.json() as Promise<T>;
}
