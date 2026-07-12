import { ApiError, apiHeaders, normalizeBackendError, parseApiErrorResponse } from './errors'

export type ScriptPage = {
  id: number
  project_id: number
  section_id: number | null
  section_no: number | null
  task_id: number | null
  scene_id: number | null
  scene_key: string | null
  character_keys: string[]
  page_no: number
  summary: string | null
  characters: string | null
  clothing: string | null
  scene: string | null
  composition: string | null
  character_action: string | null
  dialogue: string | null
  image_prompt: string | null
  status: string
  script_review_status: string
  script_review_error: string | null
  created_at: string
  updated_at: string
}

export type ScriptPageListResponse = {
  items: ScriptPage[]
}

export type ScriptSection = {
  id: number
  task_id: number
  section_no: number
  page_start: number
  page_end: number
  title: string
  description: string
  status: string
  error_message: string | null
  created_at: string
  updated_at: string
  pages: ScriptPage[]
}

export type ScriptSectionListResponse = {
  items: ScriptSection[]
}

export type ScriptScene = {
  id: number
  task_id: number
  scene_key: string
  name: string
  location_type: string
  time_of_day: string
  lighting: string
  weather: string
  environment_details: string
  color_palette: string
  visual_anchors: string
  negative_constraints: string
  selected_visual_version_id: number | null
  created_at: string
  updated_at: string
}

export type ScriptCharacter = {
  id: number
  task_id: number | null
  section_id: number
  section_no: number | null
  outline_character_id: number | null
  outfit_variant_id: number | null
  character_key: string
  name: string
  section_role: string
  current_hairstyle: string
  current_clothing: string
  current_accessories: string
  current_state: string
  emotion: string
  temporary_changes: string
  visual_anchors: string
  negative_constraints: string
  outline_character: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export type GenerateSinglePageScriptPayload = {
  project_id: number
  page_no: number
  total_pages: number
  outline_version_id?: number
  user_requirement?: string
}

export type GenerateBatchScriptPayload = {
  project_id: number
  total_pages: number
  outline_version_id?: number
  user_requirement?: string
}

export type ContinueBatchScriptPayload = {
  user_requirement?: string
}

export type ListProjectScriptTasksOptions = {
  outlineVersionId?: number
  mode?: string
  status?: string
}

export type CreatePageScriptPayload = {
  page_no: number
  task_id?: number
  summary: string
  characters: string
  clothing: string
  scene: string
  composition: string
  character_action: string
  dialogue: string
}

export type UpdatePageScriptPayload = {
  task_id?: number
  summary: string
  characters: string
  clothing: string
  scene: string
  composition: string
  character_action: string
  dialogue: string
}

export type SinglePageScriptResponse = {
  task_id: number
  page_id: number
  page_no: number
  summary: string
  characters: string
  clothing: string
  scene: string
  composition: string
  character_action: string
  dialogue: string
  status: string
}

export type ScriptTask = {
  id: number
  project_id: number
  outline_version_id: number | null
  status: string
  mode: string
  total_pages: number
  target_page_no: number | null
  user_requirement: string | null
  section_plan: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

type SseEvent = {
  event: string
  data: string
}

export type ScriptStreamCallbacks = {
  onEvent: (event: string, payload: Record<string, unknown>) => void
  onError: (error: ApiError) => void
}

const requestJson = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, {
    ...options,
    headers: apiHeaders(options.headers),
  })

  if (!response.ok) {
    throw await parseApiErrorResponse(response)
  }

  return (await response.json()) as T
}

export const listProjectPages = async (projectId: number): Promise<ScriptPage[]> => {
  const result = await requestJson<ScriptPageListResponse>(`/api/projects/${projectId}/pages`)
  return result.items
}

export const listProjectScriptTasks = async (
  projectId: number,
  options: ListProjectScriptTasksOptions = {},
): Promise<ScriptTask[]> => {
  const params = new URLSearchParams()
  if (options.outlineVersionId !== undefined) {
    params.set('outline_version_id', String(options.outlineVersionId))
  }
  if (options.mode !== undefined) {
    params.set('mode', options.mode)
  }
  if (options.status !== undefined) {
    params.set('status', options.status)
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return requestJson<ScriptTask[]>(`/api/projects/${projectId}/script-tasks${suffix}`)
}

export const listScriptTaskPages = async (taskId: number): Promise<ScriptPage[]> => {
  const result = await requestJson<ScriptPageListResponse>(`/api/scripts/tasks/${taskId}/pages`)
  return result.items
}

export const listScriptTaskSections = async (taskId: number): Promise<ScriptSection[]> => {
  const result = await requestJson<ScriptSectionListResponse>(`/api/scripts/tasks/${taskId}/sections`)
  return result.items
}

export const listScriptTaskScenes = async (taskId: number): Promise<ScriptScene[]> => {
  const result = await requestJson<{ items: ScriptScene[] }>(`/api/scripts/tasks/${taskId}/scenes`)
  return result.items
}

export const listScriptTaskCharacters = async (taskId: number): Promise<ScriptCharacter[]> => {
  const result = await requestJson<{ items: ScriptCharacter[] }>(`/api/scripts/tasks/${taskId}/characters`)
  return result.items
}

export const generateSinglePageScript = (
  payload: GenerateSinglePageScriptPayload,
): Promise<SinglePageScriptResponse> =>
  requestJson<SinglePageScriptResponse>('/api/scripts/pages/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const getScriptTask = (taskId: number): Promise<ScriptTask> =>
  requestJson<ScriptTask>(`/api/scripts/tasks/${taskId}`)

export const suspendScriptTask = (taskId: number): Promise<ScriptTask> =>
  requestJson<ScriptTask>(`/api/scripts/tasks/${taskId}/suspend`, {
    method: 'POST',
  })

export const createPageScript = (
  projectId: number,
  payload: CreatePageScriptPayload,
): Promise<ScriptPage> =>
  requestJson<ScriptPage>(`/api/projects/${projectId}/pages/scripts`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updatePageScript = (
  projectId: number,
  pageNo: number,
  payload: UpdatePageScriptPayload,
): Promise<ScriptPage> =>
  requestJson<ScriptPage>(`/api/projects/${projectId}/pages/${pageNo}/script`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const clearPageScript = (
  projectId: number,
  pageNo: number,
  taskId?: number,
): Promise<ScriptPage> => {
  const suffix = taskId === undefined ? '' : `?task_id=${taskId}`
  return requestJson<ScriptPage>(`/api/projects/${projectId}/pages/${pageNo}/script${suffix}`, {
    method: 'DELETE',
  })
}

export const deleteAllProjectPages = (projectId: number): Promise<ScriptPage[]> =>
  requestJson<ScriptPageListResponse>(`/api/projects/${projectId}/pages`, {
    method: 'DELETE',
  }).then((result) => result.items)

export const deleteScriptTaskSections = (taskId: number): Promise<void> =>
  requestJson<ScriptSectionListResponse>(`/api/scripts/tasks/${taskId}/sections`, {
    method: 'DELETE',
  }).then(() => undefined)

export const streamBatchScriptGeneration = async (
  payload: GenerateBatchScriptPayload,
  callbacks: ScriptStreamCallbacks,
): Promise<void> => {
  await streamScriptEvents('/api/scripts/batch/stream', payload, callbacks)
}

export const streamContinueScriptGeneration = async (
  taskId: number,
  payload: ContinueBatchScriptPayload,
  callbacks: ScriptStreamCallbacks,
): Promise<void> => {
  await streamScriptEvents(`/api/scripts/tasks/${taskId}/continue/stream`, payload, callbacks)
}

const streamScriptEvents = async (
  url: string,
  payload: Record<string, unknown>,
  callbacks: ScriptStreamCallbacks,
): Promise<void> => {
  const response = await fetch(url, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify(payload),
  })

  if (!response.ok || response.body === null) {
    throw await parseApiErrorResponse(response)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const handleEvent = (event: SseEvent) => {
    const payload = event.data ? JSON.parse(event.data) : {}
    if (event.event === 'error') {
      const backendError = normalizeBackendError(payload)
      callbacks.onError(
        new ApiError(backendError.message || 'Script stream error', {
          code: backendError.code,
          payload,
        }),
      )
      return
    }
    callbacks.onEvent(event.event, payload as Record<string, unknown>)
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }

    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split(/\r?\n\r?\n/)
    buffer = chunks.pop() ?? ''

    for (const chunk of chunks) {
      const event = parseSseChunk(chunk)
      if (event !== null) {
        handleEvent(event)
      }
    }
  }

  const tail = parseSseChunk(buffer)
  if (tail !== null) {
    handleEvent(tail)
  }
}

const parseSseChunk = (chunk: string): SseEvent | null => {
  const lines = chunk
    .split('\n')
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0)

  if (lines.length === 0) {
    return null
  }

  let event = 'message'
  const dataLines: string[] = []

  for (const line of lines) {
    // sse-starlette 会定期发送 ": ping" 心跳；这是连接保活，不是业务进度事件。
    if (line.startsWith(':')) {
      continue
    }

    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart())
    }
  }

  if (dataLines.length === 0) {
    return null
  }

  return {
    event,
    data: dataLines.join('\n'),
  }
}
