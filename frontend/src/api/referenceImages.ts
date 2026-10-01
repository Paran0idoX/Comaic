import { ApiError, apiHeaders, normalizeBackendError, parseApiErrorResponse } from './errors'
import type { CharacterReferencePromptPair, CharacterReferenceRun } from './characterReference'
import type { VisualAsset, VisualAssetRole } from './visualBible'

export type ReferenceCategory = 'character' | 'scene' | 'prop'
export type ReferenceCategoryDefinition = {
  entity_type: ReferenceCategory; roles: Array<{ role: ReferenceRole; label_key: string }>
}
export type ReferenceRole = Extract<VisualAssetRole, 'identity_face' | 'identity_half_body' | 'identity_full_body' | 'identity_side' | 'identity_back' | 'scene_master' | 'prop_reference'>
export type ReferenceSubject = {
  id: number; project_id: number; entity_type: 'scene' | 'prop'; key: string; name: string
  description: string; negative_constraints: string; created_at: string; updated_at: string
}
export type ReferenceSubjectPayload = Pick<ReferenceSubject, 'entity_type' | 'name' | 'description' | 'negative_constraints'> & { key?: string }
export type ReferenceRequest = {
  // 人物 entity_id 为大纲人物；场景为画面设定版本，命名条目始终由 reference_subject_id 标识。
  entity_type: ReferenceCategory; entity_id?: number | null; reference_subject_id?: number | null
  outfit_variant_id?: number | null; tool_preset_id: number; roles: ReferenceRole[]
  source_mode?: 'auto' | 'none' | 'manual'; source_asset_ids?: number[]
  canvas_asset_id?: number | null
}
export type ReferencePromptPreview = {
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  prompts: Partial<Record<ReferenceRole, CharacterReferencePromptPair>>
  source_asset_ids?: number[]
  canvas_asset_id?: number | null
  warnings?: string[]
}
export type ReferenceImageTask = {
  id: number; project_id: number; entity_type: ReferenceCategory; entity_id: number | null
  entity_key: string | null; reference_subject_id: number | null; outfit_variant_id: number | null
  outline_character_id: number | null; character_name?: string; subject_name: string
  tool_preset_id: number; tool_name: string; status: 'pending' | 'running' | 'succeeded' | 'failed' | 'suspended'
  candidate_count: number; selected_roles: ReferenceRole[]; source_asset_ids: number[]
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  prompts: Partial<Record<ReferenceRole, CharacterReferencePromptPair>>
  progress: { completed?: number; failed?: number; total?: number }
  error_code: string | null; created_at: string; updated_at: string
  candidates: Array<{ candidate_index: number; seed: number; status: string; roles: Partial<Record<ReferenceRole, CharacterReferenceRun>> }>
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
export const createReferenceImageTask = (projectId: number, payload: ReferenceRequest & {
  candidate_count: number; prompts: Partial<Record<ReferenceRole, CharacterReferencePromptPair>>
}) => request<ReferenceImageTask>(`/api/reference-images/projects/${projectId}/tasks`, { method: 'POST', body: JSON.stringify(payload) })
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
