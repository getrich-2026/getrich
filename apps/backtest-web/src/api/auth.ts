import { apiFetch, type ApiResponse } from "./client";

export interface UserInfo {
  id: string;
  email: string;
  name: string;
}

export interface AuthData {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  user: UserInfo;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  name?: string;
}

export interface RefreshRequest {
  refresh_token: string;
}

/** POST /v1/auth/login — authenticate and receive a JWT. */
export async function login(body: LoginRequest): Promise<ApiResponse<AuthData>> {
  return apiFetch<ApiResponse<AuthData>>("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** POST /v1/auth/register — create an account and receive a JWT. */
export async function register(
  body: RegisterRequest,
): Promise<ApiResponse<AuthData>> {
  return apiFetch<ApiResponse<AuthData>>("/auth/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** POST /v1/auth/refresh — exchange refresh token for new access token. */
export async function refreshToken(
  body: RefreshRequest,
): Promise<ApiResponse<AuthData>> {
  return apiFetch<ApiResponse<AuthData>>("/auth/refresh", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
