import type { ScriptTask } from './scripts'
import { ApiError, apiHeaders, normalizeBackendError, parseApiErrorResponse } from './errors'

export type ImageGenerationTool = {
  id: number
  name: string
  provider: 'comfyui' | 'openai_images_compatible'
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  description: string | null
  comfy_base_url: string | null
  workflow_json: string | null
  is_default: boolean
  capabilities: { features?: string[]; limits?: Record<string, number> }
  bindings: { schema_version?: number; bindings?: Array<{ source: string; node_id: string; input_name: string }> }
  positive_node_id: string | null
  positive_input_name: string | null
  negative_node_id: string | null
  negative_input_name: string | null
  seed_node_id: string | null
  seed_input_name: string | null
  api_base_url: string | null
  endpoint_path: string | null
  api_key: string | null
  model: string | null
  size: string | null
  response_format: string | null
  seed_field_name: string | null
  negative_prompt_field_name: string | null
  extra_body_json: string | null
  created_at: string
  updated_at: string
}

export type ImageGenerationToolPayload = {
  name: string
  provider: 'comfyui' | 'openai_images_compatible'
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  description?: string | null
  is_default: boolean
  capabilities?: Record<string, unknown>
  bindings?: Record<string, unknown>
  comfy_base_url?: string | null
  workflow_json?: string | null
  positive_node_id?: string | null
  positive_input_name?: string | null
  negative_node_id?: string | null
  negative_input_name?: string | null
  seed_node_id?: string | null
  seed_input_name?: string | null
  api_base_url?: string | null
  endpoint_path?: string | null
  api_key?: string | null
  model?: string | null
  size?: string | null
  response_format?: string | null
  seed_field_name?: string | null
  negative_prompt_field_name?: string | null
  extra_body_json?: string | null
}

export type GeneratedImage = {
  id: number
  page_id: number
  generation_run_id: number | null
  image_url: string | null
  local_path: string | null
  seed: number | null
  workflow_name: string | null
  prompt: string | null
  negative_prompt: string | null
  score: number | null
  sha256: string | null
  width: number | null
  height: number | null
  is_selected: boolean
  created_at: string
}

export type ImageGenerationPage = {
  page_id: number
  page_no: number
  prompt_type: 'tag' | 'natural_language' | 'hybrid' | null
  positive_prompt: string | null
  status: string
  selected_image_id: number | null
  latest_spec_id: number | null
  spec_warnings: Array<{ code?: string; message?: string }>
  completed_candidates: number
  images: GeneratedImage[]
}

export type GenerateImagesPayload = {
  tool_preset_id: number
  poll_interval_seconds: number
  wait_timeout_seconds: number
  candidates_per_page: number
  generation_mode: 'preview' | 'final'
  seed_strategy: 'per_page' | 'shared_candidate'
}

export type GenerationRun = {
  id: number
  generation_task_id: number
  page_id: number
  image_spec_id: number
  tool_preset_id: number
  provider: 'comfyui' | 'openai_images_compatible'
  prompt_type: 'tag' | 'natural_language' | 'hybrid'
  candidate_index: number
  seed: number | null
  seed_applied: boolean
  seed_strategy: string
  generation_mode: string
  status: string
  external_request_id: string | null
  workflow: Record<string, unknown> | null
  workflow_hash: string | null
  bindings: Record<string, unknown>
  resolved_assets: unknown[]
  degradations: unknown[]
  applied_spec: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

export type GenerationTask = {
  id: number
  project_id: number
  page_id: number | null
  comfy_prompt_id: string | null
  status: string
  batch_size: number
  error_message: string | null
  created_at: string
  updated_at: string
}

type SseEvent = {
  event: string
  data: string
}

export type ImageGenerationStreamCallbacks = {
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

export const listImageGenerationTools = async (): Promise<ImageGenerationTool[]> => {
  const result = await requestJson<{ items: ImageGenerationTool[] }>('/api/image-generation/tools')
  return result.items
}

export const createImageGenerationTool = (
  payload: ImageGenerationToolPayload,
): Promise<ImageGenerationTool> =>
  requestJson<ImageGenerationTool>('/api/image-generation/tools', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateImageGenerationTool = (
  toolId: number,
  payload: ImageGenerationToolPayload,
): Promise<ImageGenerationTool> =>
  requestJson<ImageGenerationTool>(`/api/image-generation/tools/${toolId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const deleteImageGenerationTool = (toolId: number): Promise<void> =>
  requestJson<void>(`/api/image-generation/tools/${toolId}`, {
    method: 'DELETE',
  })

export const listImageGenerationPages = async (
  taskId: number,
  options: {
    promptType?: 'tag' | 'natural_language' | 'hybrid'
    generationMode?: 'preview' | 'final'
  } = {},
): Promise<ImageGenerationPage[]> => {
  const params = new URLSearchParams()
  if (options.promptType) params.set('prompt_type', options.promptType)
  if (options.generationMode) params.set('generation_mode', options.generationMode)
  const query = params.size ? `?${params.toString()}` : ''
  const result = await requestJson<{ items: ImageGenerationPage[] }>(
    `/api/image-generation/script-tasks/${taskId}/pages${query}`,
  )
  return result.items
}

export const suspendImageGenerationTask = (taskId: number): Promise<GenerationTask> =>
  requestJson<GenerationTask>(`/api/image-generation/tasks/${taskId}/suspend`, {
    method: 'POST',
  })

export const selectGeneratedImage = (
  pageId: number,
  imageId: number,
): Promise<ImageGenerationPage> =>
  requestJson<ImageGenerationPage>(`/api/image-generation/pages/${pageId}/images/${imageId}/select`, {
    method: 'POST',
  })

export const getGenerationRun = (runId: number): Promise<GenerationRun> =>
  requestJson<GenerationRun>(`/api/image-generation/runs/${runId}`)

export const streamGenerateImagesForTask = (
  taskId: number,
  payload: GenerateImagesPayload,
  callbacks: ImageGenerationStreamCallbacks,
): Promise<void> =>
  streamSse(`/api/image-generation/script-tasks/${taskId}/generate/stream`, payload, callbacks)

export const streamContinueImagesForTask = (
  taskId: number,
  payload: GenerateImagesPayload,
  callbacks: ImageGenerationStreamCallbacks,
): Promise<void> =>
  streamSse(`/api/image-generation/script-tasks/${taskId}/continue/stream`, payload, callbacks)

export const streamGenerateImagesForPage = (
  pageId: number,
  payload: GenerateImagesPayload,
  callbacks: ImageGenerationStreamCallbacks,
): Promise<void> =>
  streamSse(`/api/image-generation/pages/${pageId}/generate/stream`, payload, callbacks)

const streamSse = async (
  url: string,
  payload: GenerateImagesPayload,
  callbacks: ImageGenerationStreamCallbacks,
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
    const parsedPayload = event.data ? JSON.parse(event.data) : {}
    if (event.event === 'error') {
      const backendError = normalizeBackendError(parsedPayload)
      callbacks.onError(
        new ApiError(backendError.message || 'Image generation stream error', {
          code: backendError.code,
          payload: parsedPayload,
        }),
      )
      return
    }
    callbacks.onEvent(event.event, parsedPayload as Record<string, unknown>)
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

export type { ScriptTask }
