import { ApiError, apiHeaders, normalizeBackendError, parseApiErrorResponse } from './errors'
import type { CharacterReferencePromptPair, CharacterReferenceRun } from './characterReference'
import type { VisualAsset, VisualAssetRole } from './visualBible'

export type ReferenceCategory = 'character' | 'scene' | 'prop'
export type ReferenceCategoryDefinition = {
  entity_type: ReferenceCategory; roles: Array<{ role: ReferenceRole; label_key: string }>
}
export type ReferenceRole = Extract<VisualAssetRole, 'identity_face' | 'identity_full_body' | 'identity_side' | 'identity_back' | 'scene_master' | 'prop_reference'>
export type HistoricalReferenceRole = ReferenceRole | 'identity_half_body'
export type ReferenceSize = { width: number; height: number }
export type VisualFact = {
  kind: string; attribute: string; must_keep?: boolean; default_is_explicit?: boolean; polarity: 'required' | 'forbidden'; source_field: string; source_excerpt: string
  views: ReferenceRole[]; options: Array<{ natural: string; tags: string[] }>
  selected: number; default_index: number; selection_reason: string
}
export type VisualProfileRef = { id: number; revision: number; source_hash: string }
export type VisualProfile = VisualProfileRef & {
  project_id: number; kind: 'character' | 'outfit' | 'scene_subject' | 'scene_version' | 'prop_subject'
  owner_id: number; format_version: number; data: { human: boolean; facts: VisualFact[] }
}
export const visualProfileRefs = (profiles: VisualProfile[]): VisualProfileRef[] =>
  profiles.map(({ id, revision, source_hash }) => ({ id, revision, source_hash }))
export type ReferenceSubject = {
  id: number; project_id: number; entity_type: 'scene' | 'prop'; key: string; name: string
  scene_definition_version?: number
  description: string; negative_constraints: string; created_at: string; updated_at: string
}
export type ReferenceSubjectPayload = Pick<ReferenceSubject, 'entity_type' | 'name' | 'description' | 'negative_constraints'> & { key?: string }
export type ReferenceRequest = {
  // 人物 entity_id 为大纲人物；场景为画面设定版本，命名条目始终由 reference_subject_id 标识。
  entity_type: ReferenceCategory; entity_id?: number | null; reference_subject_id?: number | null
  outfit_variant_id?: number | null; tool_preset_id: number; roles: ReferenceRole[]
  source_mode?: 'auto' | 'none' | 'manual'; source_asset_ids?: number[]
  canvas_asset_id?: number | null
  sizes?: Partial<Record<ReferenceRole, ReferenceSize>>
  refresh_visual_profiles?: boolean
}
export type ReferencePromptPreview = {
  visual_profiles?: VisualProfile[]
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  prompts: Partial<Record<ReferenceRole, CharacterReferencePromptPair>>
  source_asset_ids?: number[]
  canvas_asset_id?: number | null
  warnings?: string[]
  sizes?: Partial<Record<ReferenceRole, ReferenceSize>>
}
export type ReferenceImageTask = {
  id: number; project_id: number; entity_type: ReferenceCategory; entity_id: number | null
  entity_key: string | null; reference_subject_id: number | null; outfit_variant_id: number | null
  outline_character_id: number | null; character_name?: string; subject_name: string
  tool_preset_id: number; tool_name: string; status: 'pending' | 'running' | 'succeeded' | 'failed' | 'suspended'
  candidate_count: number; selected_roles: HistoricalReferenceRole[]; source_asset_ids: number[]
  sizes?: Partial<Record<ReferenceRole, ReferenceSize>>
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  prompts: Partial<Record<ReferenceRole, CharacterReferencePromptPair>>
  progress: { completed?: number; failed?: number; total?: number }
  error_code: string | null; created_at: string; updated_at: string
  candidates: Array<{ candidate_index: number; seed: number; status: string; roles: Partial<Record<HistoricalReferenceRole, CharacterReferenceRun>> }>
}

const request = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, { ...options, headers: apiHeaders(options.headers) })
  if (!response.ok) throw await parseApiErrorResponse(response)
  return await response.json() as T
}
export const listReferenceCategories = async (): Promise<ReferenceCategoryDefinition[]> =>
  (await request<{ categories: ReferenceCategoryDefinition[] }>('/api/reference-images/catalog')).categories

export const listReferenceSubjects = async (projectId: number): Promise<ReferenceSubject[]> =>
  (await request<{ items: ReferenceSubject[] }>(`/api/reference-images/projects/${projectId}/subjects`)).items
export const createReferenceSubject = (projectId: number, payload: ReferenceSubjectPayload) =>
  request<ReferenceSubject>(`/api/reference-images/projects/${projectId}/subjects`, { method: 'POST', body: JSON.stringify(payload) })
export const updateReferenceSubject = (id: number, payload: Omit<ReferenceSubjectPayload, 'entity_type' | 'key'>) =>
  request<ReferenceSubject>(`/api/reference-images/subjects/${id}`, { method: 'PUT', body: JSON.stringify(payload) })
export const bindSceneReferenceSubject = (sceneId: number, subjectId: number | null) =>
  request<{ id: number; reference_subject_id: number | null }>(`/api/reference-images/script-scenes/${sceneId}/subject`, {
    method: 'PUT', body: JSON.stringify({ reference_subject_id: subjectId }),
  })
export const previewReferencePrompts = (projectId: number, payload: ReferenceRequest) =>
  request<ReferencePromptPreview>(`/api/reference-images/projects/${projectId}/prompt-preview`, { method: 'POST', body: JSON.stringify(payload) })
export type ReferencePromptBatchItem = {
  project_id: number; index: number; status: 'running' | 'succeeded' | 'failed'
  preview?: ReferencePromptPreview; error?: { code?: string; message?: string }
}
/** 一次提交全部对象；并发调度及逐项状态由后端负责，不自动重发收费请求。 */
export const previewReferencePromptBatch = async (projectId: number, items: ReferenceRequest[],
  onItem: (item: ReferencePromptBatchItem) => void, signal?: AbortSignal): Promise<void> => {
  const response = await fetch(`/api/reference-images/projects/${projectId}/prompt-preview/batch`, {
    method: 'POST', headers: apiHeaders(), body: JSON.stringify({ items }), signal,
  })
  if (!response.ok) throw await parseApiErrorResponse(response)
  if (!response.body) throw new ApiError('Missing reference prompt stream')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let buffer = '', completed = false
  const consume = (chunk: string) => {
    const lines = chunk.split(/\r?\n/)
    const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
    if (!data) return
    const payload = JSON.parse(data)
    if (event === 'item') onItem(payload as ReferencePromptBatchItem)
    if (event === 'done' && payload.project_id === projectId) completed = true
    if (event === 'error') {
      const error = normalizeBackendError(payload)
      throw new ApiError(error.message || 'Reference prompt stream error', { code: error.code, payload })
    }
  }
  try {
    while (!completed) {
      const { done, value } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      const chunks = buffer.split(/\r?\n\r?\n/)
      buffer = chunks.pop() || ''
      for (const chunk of chunks) consume(chunk)
      if (done) { if (buffer.trim()) consume(buffer); break }
    }
    if (!completed) throw new ApiError('Reference prompt stream ended before completion')
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
}
export const updateVisualProfile = (profile: VisualProfile) =>
  request<VisualProfile>(`/api/reference-images/visual-profiles/${profile.id}`, {
    method: 'PUT', body: JSON.stringify({ expected_revision: profile.revision, data: profile.data }),
  })
export const createReferenceImageTask = (projectId: number, payload: ReferenceRequest & {
  candidate_count: number; prompts: Partial<Record<ReferenceRole, CharacterReferencePromptPair>>
  visual_profile_refs?: VisualProfileRef[]
}) => request<ReferenceImageTask>(`/api/reference-images/projects/${projectId}/tasks`, { method: 'POST', body: JSON.stringify(payload) })
export type ReferenceTaskRequest = ReferenceRequest & {
  candidate_count: number; prompts: ReferencePromptPreview['prompts']
  visual_profile_refs?: VisualProfileRef[]
}
export const createReferenceImageBatch = async (projectId: number, items: ReferenceTaskRequest[]): Promise<ReferenceImageTask[]> =>
  (await request<{ items: ReferenceImageTask[] }>(`/api/reference-images/projects/${projectId}/tasks/batch`, {
    method: 'POST', body: JSON.stringify({ items }),
  })).items
export const listReferenceImageTasks = async (projectId: number): Promise<ReferenceImageTask[]> =>
  (await request<{ items: ReferenceImageTask[] }>(`/api/reference-images/projects/${projectId}/tasks`)).items
export const getReferenceImageTask = (taskId: number) => request<ReferenceImageTask>(`/api/reference-images/tasks/${taskId}`)
export const suspendReferenceImageTask = (taskId: number) => request<ReferenceImageTask>(`/api/reference-images/tasks/${taskId}/suspend`, { method: 'POST' })
export const continueReferenceImageTask = (taskId: number) => request<ReferenceImageTask>(`/api/reference-images/tasks/${taskId}/continue`, { method: 'POST' })
export const approveReferenceImage = (imageId: number) => request<VisualAsset>(`/api/reference-images/images/${imageId}/approve`, { method: 'POST' })

/** 只监听已创建任务；重连读取快照，不会重新发起收费生成。 */
export const watchReferenceImageTask = (id: number, callbacks: {
  onTask: (task: ReferenceImageTask, terminal: boolean) => void; onError: (error: ApiError) => void
}): (() => void) => {
  const source = new EventSource(`/api/reference-images/tasks/${id}/events`)
  const consume = (event: MessageEvent<string>, terminal: boolean) => {
    try { callbacks.onTask(JSON.parse(event.data) as ReferenceImageTask, terminal) }
    catch { callbacks.onError(new ApiError('Invalid reference image event')) }
    if (terminal) source.close()
  }
  source.addEventListener('progress', event => consume(event as MessageEvent<string>, false))
  source.addEventListener('done', event => consume(event as MessageEvent<string>, true))
  source.addEventListener('error', event => {
    if (!(event instanceof MessageEvent) || !event.data) return
    let payload: unknown = event.data
    try { payload = JSON.parse(event.data) } catch { /* 统一错误模块处理安全消息。 */ }
    const error = normalizeBackendError(payload)
    callbacks.onError(new ApiError(error.message || 'Reference image stream error', { code: error.code, payload }))
    source.close()
  })
  return () => source.close()
}
