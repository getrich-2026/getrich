/** 既有 /v1/auth/login 返回的 data；不额外持久化刷新凭证。 */
export interface AuthUser {
  id: string
  email: string
  name: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  user: AuthUser
}
