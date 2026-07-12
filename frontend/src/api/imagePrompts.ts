import type { ScriptTask } from './scripts'
import { ApiError, apiHeaders, normalizeBackendError, parseApiErrorResponse } from './errors'

export const IMAGE_PROMPT_PRESET_KINDS = {
  system: 'script_to_image_system_prompt',
  shot: 'shot_planner_system_prompt',
  negative: 'negative_prompt',
} as const

export type ImagePromptPresetKind =
  (typeof IMAGE_PROMPT_PRESET_KINDS)[keyof typeof IMAGE_PROMPT_PRESET_KINDS]

export type ImagePromptPreset = {
  id: number
  name: string
  description: string | null
  kind: ImagePromptPresetKind
  content: string
  is_default: boolean
  created_at: string
  updated_at: string
}

export type ImagePromptPresetPayload = {
  name: string
  description?: string | null
  kind: ImagePromptPresetKind
  content: string
  is_default: boolean
}

export type GenerateImagePromptsPayload = {
  system_prompt_preset_id: number
  concurrency: number
}

export type ImagePromptGenerationItem = {
  page_id: number
  page_no: number
  image_prompt: string | null
  status: string
  scene_key?: string | null
  character_keys?: string[]
  error: string | null
  error_code?: string | null
}

export type GenerateImagePromptsResponse = {
  task_id: number
  total: number
  succeeded: number
  failed: number
  items: ImagePromptGenerationItem[]
}

type SseEvent = {
  event: string
  data: string
}

export type ImagePromptStreamCallbacks = {
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

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export const listImagePromptPresets = async (
  kind?: ImagePromptPresetKind,
): Promise<ImagePromptPreset[]> => {
  const query = kind === undefined ? '' : `?kind=${encodeURIComponent(kind)}`
  const result = await requestJson<{ items: ImagePromptPreset[] }>(
    `/api/image-prompts/presets${query}`,
  )
  return result.items
}

export const createImagePromptPreset = (
  payload: ImagePromptPresetPayload,
): Promise<ImagePromptPreset> =>
  requestJson<ImagePromptPreset>('/api/image-prompts/presets', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateImagePromptPreset = (
  presetId: number,
  payload: ImagePromptPresetPayload,
): Promise<ImagePromptPreset> =>
  requestJson<ImagePromptPreset>(`/api/image-prompts/presets/${presetId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const deleteImagePromptPreset = (presetId: number): Promise<void> =>
  requestJson<void>(`/api/image-prompts/presets/${presetId}`, {
    method: 'DELETE',
  })

export const listCompletedScriptTasks = (projectId: number): Promise<ScriptTask[]> =>
  requestJson<ScriptTask[]>(`/api/image-prompts/projects/${projectId}/script-tasks`)

export const listScriptTaskImagePrompts = (taskId: number): Promise<GenerateImagePromptsResponse> =>
  requestJson<GenerateImagePromptsResponse>(`/api/image-prompts/script-tasks/${taskId}/pages`)

export const generateImagePromptsForTask = (
  taskId: number,
  payload: GenerateImagePromptsPayload,
): Promise<GenerateImagePromptsResponse> =>
  requestJson<GenerateImagePromptsResponse>(`/api/image-prompts/script-tasks/${taskId}/generate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const generateImagePromptForPage = (
  pageId: number,
  payload: GenerateImagePromptsPayload,
): Promise<ImagePromptGenerationItem> =>
  requestJson<ImagePromptGenerationItem>(`/api/image-prompts/pages/${pageId}/generate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const streamGenerateImagePromptsForTask = async (
  taskId: number,
  payload: GenerateImagePromptsPayload,
  callbacks: ImagePromptStreamCallbacks,
): Promise<void> => {
  const response = await fetch(`/api/image-prompts/script-tasks/${taskId}/generate/stream`, {
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
        new ApiError(backendError.message || 'Image prompt stream error', {
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
