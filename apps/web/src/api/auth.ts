import { http } from './client'
import type { LoginRequest, LoginResponse } from '@/types/auth'

/** 复用既有登录接口；错误凭证在表单内反馈，避免全局 401 跳转丢失错误提示。 */
export const loginWithPassword = (body: LoginRequest) =>
  http.post<LoginResponse>('/auth/login', body, {
    validateStatus: status => status >= 200 && status < 300 || status === 401,
  })
