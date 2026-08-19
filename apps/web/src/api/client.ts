import axios, { type AxiosRequestConfig } from 'axios'
import type { ApiResponse } from '@/types/common'

// 后端基址由 VITE_API_BASE_URL 提供（值里已含 /v1 前缀）。
// 不要在源码里硬编码服务器地址 —— 本仓库是公开仓库。
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 10000,
})

// 请求拦截器：每次请求自动带上 token + 开发期 mock 用户头
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // 开发期 mock 认证：后端读 X-User-Id 头识别用户。
  // 缺了它，is_subscribed / subscription_info 这类跟用户相关的字段全是默认值。
  // 切到真实 JWT 后可以删掉。
  const demoUserId = import.meta.env.VITE_DEMO_USER_ID
  if (demoUserId && !config.headers['X-User-Id']) {
    config.headers['X-User-Id'] = demoUserId
  }
  return config
})

// 响应拦截器：校验后端统一信封 { code, message, data }，把 response.data
// 就地换成信封里的 data。仍然返回 AxiosResponse，所以不需要对 Axios 的类型
// 撒谎；真正把它剥成 T 的是下面的 http 包装。
client.interceptors.response.use(
  (response) => {
    const body = response.data as ApiResponse<unknown> | undefined
    // code === 0 才算成功。非 0 必须抛出来，否则业务错误会被当成正常数据
    // 一路带到组件里，渲染成空白而不报错。
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        throw new Error(body.message || `请求失败（code=${body.code}）`)
      }
      response.data = body.data
    }
    return response
  },
  (error) => {
    if (error.response?.status === 401) {
      // token 过期，跳回登录页
      localStorage.removeItem('token')
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)

// 各 api 模块统一走这层：返回的就是后端信封里的 data，类型即 T。
// 调用方不该再见到 AxiosResponse，更不该写 res.data.data。
export const http = {
  get: <T>(url: string, config?: AxiosRequestConfig) =>
    client.get<T>(url, config).then((r) => r.data),
  post: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    client.post<T>(url, body, config).then((r) => r.data),
  put: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    client.put<T>(url, body, config).then((r) => r.data),
  delete: <T>(url: string, config?: AxiosRequestConfig) =>
    client.delete<T>(url, config).then((r) => r.data),
}

export default client
