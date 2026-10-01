import { apiHeaders, parseApiErrorResponse } from './errors'

export type ConsistencyMetricKey =
  | 'cids_cross'
  | 'cids_self'
  | 'csd_cross'
  | 'csd_self'
  | 'occm'
  | 'copy_paste'

export type ConsistencyRuntimeReadiness = {
  ready: boolean
  python_executable: string
  source_root: string
  pretrain_root: string
  missing_modules: string[]
  missing_source_files: string[]
  missing_weights: string[]
  invalid_source_files: string[]
  invalid_weights: string[]
  onnx_cuda_available: boolean
  arcface_provider: 'cuda' | 'cpu'
  torch_version: string | null
  cuda_available: boolean
  cuda_device: string | null
  detail: string | null
  metric_version: string
}

export type ConsistencyThresholds = {
  cids_cross_min: number
  cids_self_min: number
  csd_cross_min: number
  csd_self_min: number
  occm_min: number
  copy_paste_max: number
}

export type ConsistencySettings = ConsistencyThresholds & {
  runtime: ConsistencyRuntimeReadiness
  metric_version: string
}

export type ConsistencyIssue = {
  code: string
  message: string
  details?: Record<string, unknown>
  [key: string]: unknown
}

export type ConsistencyReferenceBaseline = {
  mode: 'approved_identity_assets'
  reference_count: number
  characters: Array<{
    character_id: number
    character_key: string
    character_name: string
    reference_count: number
    references: Array<{
      asset_id: number
      role: string
      version: number
      sha256: string
    }>
  }>
}

export type ConsistencyReadiness = {
  ready: boolean
  batch_task_id: number
  metric_version: string
  errors: ConsistencyIssue[]
  warnings: ConsistencyIssue[]
  runtime: ConsistencyRuntimeReadiness | null
  track_count: number
  incomplete_tracks: Array<{ candidate_index: number; missing_pages: number[] }>
  source_hash: string | null
  reference_baseline: ConsistencyReferenceBaseline | null
}

export type ConsistencyTrack = {
  id: number
  evaluation_task_id: number
  candidate_index: number
  status: 'pending' | 'passed' | 'failed' | 'error'
  passed: boolean
  image_ids: Record<string, number>
  metrics: Partial<Record<ConsistencyMetricKey, number | null>>
  details: {
    applicability?: Partial<Record<ConsistencyMetricKey, boolean>>
    checks?: Record<string, { applicable?: boolean; passed?: boolean; value?: number | null }>
    [key: string]: unknown
  }
  error_code: string | null
  error_message: string | null
  adopted_at: string | null
  created_at: string
  updated_at: string
}

export type ConsistencyEvaluationTask = {
  id: number
  batch_task_id: number
  script_task_id: number
  status: 'pending' | 'waiting_resource' | 'running' | 'suspended' | 'succeeded' | 'failed'
  source_hash: string
  thresholds: ConsistencyThresholds
  metric_version: string
  progress: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  heartbeat_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  tracks: ConsistencyTrack[]
}

export type ConsistencyGate = {
  passed: boolean
  script_task_id: number
  batch_task_id: number | null
  evaluation_task_id: number | null
  track_id: number | null
  candidate_index: number | null
  source_hash: string | null
}

const requestJson = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, {
    ...options,
    headers: apiHeaders(options.headers),
  })
  if (!response.ok) throw await parseApiErrorResponse(response)
  return (await response.json()) as T
}

export const getConsistencySettings = (): Promise<ConsistencySettings> =>
  requestJson<ConsistencySettings>('/api/settings/consistency-evaluation')

export const updateConsistencySettings = (
  payload: ConsistencyThresholds,
): Promise<ConsistencySettings> =>
  requestJson<ConsistencySettings>('/api/settings/consistency-evaluation', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const getConsistencyReadiness = (batchTaskId: number): Promise<ConsistencyReadiness> =>
  requestJson<ConsistencyReadiness>(`/api/consistency-evaluations/batches/${batchTaskId}/readiness`)

export const createConsistencyEvaluation = (
  batchTaskId: number,
): Promise<ConsistencyEvaluationTask> =>
  requestJson<ConsistencyEvaluationTask>(`/api/consistency-evaluations/batches/${batchTaskId}`, {
    method: 'POST',
  })

export const listConsistencyEvaluations = async (
  batchTaskId: number,
): Promise<ConsistencyEvaluationTask[]> => {
  const result = await requestJson<{ items: ConsistencyEvaluationTask[] }>(
    `/api/consistency-evaluations/batches/${batchTaskId}/tasks`,
  )
  return result.items
}

export const getConsistencyEvaluation = (taskId: number): Promise<ConsistencyEvaluationTask> =>
  requestJson<ConsistencyEvaluationTask>(`/api/consistency-evaluations/tasks/${taskId}`)

export const adoptConsistencyTrack = (trackId: number): Promise<ConsistencyTrack> =>
  requestJson<ConsistencyTrack>(`/api/consistency-evaluations/tracks/${trackId}/adopt`, {
    method: 'POST',
  })

export const getConsistencyGate = (scriptTaskId: number): Promise<ConsistencyGate> =>
  requestJson<ConsistencyGate>(`/api/consistency-evaluations/script-tasks/${scriptTaskId}/gate`)
