import { isAxiosError } from 'axios'
import { http } from './client'
import type {
  DataQualityResponse,
  DiagnosisErrorResponse,
  DiagnosisResult,
  ErrorInfo,
  RecomputeRequest,
  ReportResponse,
  SnapshotAccepted,
  SnapshotProgress,
  SnapshotRequest,
  SpecVersionInfo,
  SpecVersionList,
  UserLevel,
} from '@/types/diagnosis'

// 本模块只发请求、返回后端 data（信封由 client.ts 剥掉），不做面向视图的形状转换。
// 处理中时 /result、/report、/data-quality 返回 202 + SnapshotProgress，调用方按
// run_status 区分；轮询用 react-query 的 refetchInterval，不要在组件里手写定时器。
// 分享端点按设计延后，这里不提供。

/**
 * 提交诊断。``idempotencyKey`` 由调用方在每次「开始诊断」时生成，
 * 只在这一次操作的网络重试中复用；同键异体后端返回 409。
 */
export const createSnapshot = (body: SnapshotRequest, idempotencyKey: string) =>
  http.post<SnapshotAccepted>('/diagnosis/snapshots', body, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })

/**
 * 按新的 options 基于原快照创建新快照，原快照不变。当前后端在原数据版本可复现前
 * 一律返回 409（error.code = BASE_DATA_VERSION_UNAVAILABLE，retryable = false）。
 */
export const recomputeSnapshot = (
  snapshotId: string,
  body: RecomputeRequest,
  idempotencyKey: string,
) =>
  http.post<SnapshotAccepted>(`/diagnosis/snapshots/${snapshotId}/recompute`, body, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })

export const getDiagnosisResult = (snapshotId: string) =>
  http.get<DiagnosisResult | SnapshotProgress>(`/diagnosis/snapshots/${snapshotId}/result`)

export const getDiagnosisReport = (snapshotId: string, userLevel: UserLevel) =>
  http.get<ReportResponse | SnapshotProgress>(`/diagnosis/snapshots/${snapshotId}/report`, {
    params: { user_level: userLevel },
  })

export const getDiagnosisDataQuality = (snapshotId: string) =>
  http.get<DataQualityResponse | SnapshotProgress>(
    `/diagnosis/snapshots/${snapshotId}/data-quality`,
  )

export const listSpecVersions = () => http.get<SpecVersionList>('/diagnosis/spec-versions')

export const getCurrentSpecVersion = () =>
  http.get<SpecVersionInfo>('/diagnosis/spec-versions/current')

/**
 * 取出诊断接口的结构化错误。诊断错误体是 {request_id, error}，不走 {code, data} 信封，
 * 所以要从 Axios 错误响应里读；不是该形状时返回 null，由调用方按普通网络错误处理。
 * ``issues[].path`` 是 JSON Pointer（如 /plans/0/holdings/2/symbol），可据此定位到输入行。
 */
export function diagnosisError(error: unknown): ErrorInfo | null {
  if (!isAxiosError<DiagnosisErrorResponse>(error)) return null
  const body = error.response?.data
  if (!body || typeof body !== 'object' || !('error' in body)) return null
  return body.error
}
