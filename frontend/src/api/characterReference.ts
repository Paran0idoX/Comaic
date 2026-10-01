import { ApiError, apiHeaders, normalizeBackendError, parseApiErrorResponse } from './errors'

export type CharacterReferenceRole = 'identity_face' | 'identity_half_body' | 'identity_full_body'

export type CharacterReferenceCharacter = {
  id: number
  outline_version_id: number
  character_key: string
  name: string
  visual_type: 'realistic_human' | 'stylized_human' | 'non_human'
}

export type CharacterReferencePromptPair = {
  positive: string
  negative: string
}

export type CharacterReferencePromptPreview = {
  character_id: number
  tool_preset_id: number
  style_profile_id: number | null
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  prompts: Record<CharacterReferenceRole, CharacterReferencePromptPair>
}

export type CharacterReferenceImage = {
  id: number
  artifact_index: number
  image_url: string
  sha256: string
  width: number | null
  height: number | null
  promoted_asset_id: number | null
}

export type CharacterReferenceRun = {
  id: number
  candidate_index: number
  role: CharacterReferenceRole
  seed: number
  provider: 'comfyui' | 'openai_images_compatible'
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  positive_prompt: string
  negative_prompt: string
  status: 'pending' | 'running' | 'queued' | 'succeeded' | 'failed'
  review_status: 'draft' | 'approved' | 'archived'
  seed_applied: boolean
  external_request_id: string | null
  degradations: Array<Record<string, unknown>>
  error_code: string | null
  images: CharacterReferenceImage[]
  primary_image: CharacterReferenceImage | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

export type CharacterReferenceCandidateSet = {
  candidate_index: number
  seed: number
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  review_status: 'draft' | 'approved' | 'archived'
  complete: boolean
  roles: Partial<Record<CharacterReferenceRole, CharacterReferenceRun>>
}

export type CharacterReferenceTask = {
  id: number
  project_id: number
  outline_character_id: number
  entity_type?: 'character' | 'scene' | 'prop'
  entity_id?: number | null
  reference_subject_id?: number | null
  outfit_variant_id?: number | null
  selected_roles?: string[]
  source_asset_ids?: number[]
  character_name: string
  tool_preset_id: number
  tool_name: string
  style_profile_id: number | null
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'suspended'
  candidate_count: number
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  prompts: Record<CharacterReferenceRole, CharacterReferencePromptPair>
  progress: { completed?: number; failed?: number; total?: number }
  approved_candidate_index: number | null
  error_code: string | null
  heartbeat_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  candidates: CharacterReferenceCandidateSet[]
}

export type CharacterReferenceTaskPayload = {
  tool_preset_id: number
  style_profile_id: number | null
  candidate_count: number
  prompts: Record<CharacterReferenceRole, CharacterReferencePromptPair>
}

const requestJson = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, {
    ...options,
    headers: apiHeaders(options.headers),
  })
  if (!response.ok) throw await parseApiErrorResponse(response)
  return (await response.json()) as T
}

export const previewCharacterReferencePrompts = (
  characterId: number,
  payload: { tool_preset_id: number; style_profile_id: number | null },
): Promise<CharacterReferencePromptPreview> =>
  requestJson<CharacterReferencePromptPreview>(
    `/api/character-references/outline-characters/${characterId}/prompt-preview`,
    { method: 'POST', body: JSON.stringify(payload) },
  )

export const createCharacterReferenceTask = (
  characterId: number,
  payload: CharacterReferenceTaskPayload,
): Promise<CharacterReferenceTask> =>
  requestJson<CharacterReferenceTask>(
    `/api/character-references/outline-characters/${characterId}/tasks`,
    { method: 'POST', body: JSON.stringify(payload) },
  )

export const listCharacterReferenceTasks = async (
  characterId: number,
): Promise<CharacterReferenceTask[]> => {
  const result = await requestJson<{ items: CharacterReferenceTask[] }>(
    `/api/character-references/outline-characters/${characterId}/tasks`,
  )
  return result.items
}

export const listCharacterReferenceCharacters = async (
  outlineVersionId: number,
): Promise<CharacterReferenceCharacter[]> => {
  const result = await requestJson<{ items: CharacterReferenceCharacter[] }>(
    `/api/character-references/outline-versions/${outlineVersionId}/characters`,
  )
  return result.items
}

export const listProjectCharacterReferenceCharacters = async (
  projectId: number,
): Promise<CharacterReferenceCharacter[]> => {
  const result = await requestJson<{ items: CharacterReferenceCharacter[] }>(
    `/api/character-references/projects/${projectId}/outline-characters`,
  )
  return result.items
}

export const getCharacterReferenceTask = (taskId: number): Promise<CharacterReferenceTask> =>
  requestJson<CharacterReferenceTask>(`/api/character-references/tasks/${taskId}`)

export const suspendCharacterReferenceTask = (taskId: number): Promise<CharacterReferenceTask> =>
  requestJson<CharacterReferenceTask>(`/api/character-references/tasks/${taskId}/suspend`, {
    method: 'POST',
  })

export const continueCharacterReferenceTask = (taskId: number): Promise<CharacterReferenceTask> =>
  requestJson<CharacterReferenceTask>(`/api/character-references/tasks/${taskId}/continue`, {
    method: 'POST',
  })

export const approveCharacterReferenceSet = (
  taskId: number,
  candidateIndex: number,
): Promise<CharacterReferenceTask> =>
  requestJson<CharacterReferenceTask>(
    `/api/character-references/tasks/${taskId}/candidate-sets/${candidateIndex}/approve`,
    { method: 'POST' },
  )

export type CharacterReferenceStreamCallbacks = {
  onTask: (task: CharacterReferenceTask, terminal: boolean) => void
  onError: (error: ApiError) => void
}

/**
 * 原生 EventSource 会在临时断网后自动重连；服务端快照来自数据库，重连不会重复提交生成。
 */
export const watchCharacterReferenceTask = (
  taskId: number,
  callbacks: CharacterReferenceStreamCallbacks,
): (() => void) => {
  const source = new EventSource(`/api/character-references/tasks/${taskId}/events`)

  const handleTask = (event: MessageEvent<string>, terminal: boolean) => {
    try {
      callbacks.onTask(JSON.parse(event.data) as CharacterReferenceTask, terminal)
    } catch (error) {
      callbacks.onError(
        new ApiError(error instanceof Error ? error.message : 'Invalid character reference event'),
      )
    }
    if (terminal) source.close()
  }

  source.addEventListener('progress', (event) => handleTask(event as MessageEvent<string>, false))
  source.addEventListener('done', (event) => handleTask(event as MessageEvent<string>, true))
  source.addEventListener('error', (event) => {
    // 自定义 SSE error 带有 data；网络错误由 EventSource 自己重连，不提前终止任务监听。
    if (!(event instanceof MessageEvent) || !event.data) return
    let payload: unknown = event.data
    try {
      payload = JSON.parse(event.data)
    } catch {
      // 保留原始安全文案，交给统一错误显示处理。
    }
    const backendError = normalizeBackendError(payload)
    callbacks.onError(
      new ApiError(backendError.message || 'Character reference stream error', {
        code: backendError.code,
        payload,
      }),
    )
    source.close()
  })

  return () => source.close()
}
