// 通用分页
export interface Pagination {
    page: number
    page_size: number
    total: number
    total_pages: number
    has_more: boolean
}

// 通用响应结构 （拦截器只剥了 Axios 的壳，后端的 code/message/data 还在）
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}
