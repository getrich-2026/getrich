import axios from 'axios'

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
  // 开发期 mock 认证：后端读 X-User-Id 头识别用户
  // 切到真实 JWT 后可以删掉
  const demoUserId = import.meta.env.VITE_DEMO_USER_ID
  if (demoUserId && !config.headers['X-User-Id']) {
    config.headers['X-User-Id'] = demoUserId
  }
  return config
})

// 响应拦截器：统一处理错误
client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      // token 过期，跳回登录页
      localStorage.removeItem('token')
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)

export default client