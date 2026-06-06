import apiClient from './client'
import type { ApiResponse } from '@/types/common'
import type {
  ImportCommitData,
  ImportHistoryData,
  ImportPreviewBody,
  ImportPreviewData,
  StrategyUpsertBody,
  StrategyUpsertData,
} from '@/types/adminImport'

export const upsertAdminStrategy = (
  body: StrategyUpsertBody
): Promise<ApiResponse<StrategyUpsertData>> => {
  return apiClient.post<ApiResponse<StrategyUpsertData>>(
    '/admin/imports/strategies/upsert',
    body
  ) as unknown as Promise<ApiResponse<StrategyUpsertData>>
}

export const previewAdminImport = (
  body: ImportPreviewBody
): Promise<ApiResponse<ImportPreviewData>> => {
  return apiClient.post<ApiResponse<ImportPreviewData>>(
    '/admin/imports/preview',
    body
  ) as unknown as Promise<ApiResponse<ImportPreviewData>>
}

export const commitAdminImport = (
  jobId: string
): Promise<ApiResponse<ImportCommitData>> => {
  return apiClient.post<ApiResponse<ImportCommitData>>(
    `/admin/imports/${jobId}/commit`
  ) as unknown as Promise<ApiResponse<ImportCommitData>>
}

export const getAdminImportHistory = (): Promise<ApiResponse<ImportHistoryData>> => {
  return apiClient.get<ApiResponse<ImportHistoryData>>(
    '/admin/imports/history'
  ) as unknown as Promise<ApiResponse<ImportHistoryData>>
}
