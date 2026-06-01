import type { ScriptTask } from './scripts'

export type ComfyWorkflowPreset = {
  id: number
  name: string
  description: string | null
  workflow_json: string
  is_default: boolean
  positive_node_id: string
  positive_input_name: string
  negative_node_id: string | null
  negative_input_name: string | null
  seed_node_id: string | null
  seed_input_name: string | null
  created_at: string
  updated_at: string
}

export type ComfyWorkflowPresetPayload = {
  name: string
  description?: string | null
  workflow_json: string
  is_default: boolean
  positive_node_id: string
  positive_input_name: string
  negative_node_id?: string | null
  negative_input_name?: string | null
  seed_node_id?: string | null
  seed_input_name?: string | null
}

export type GeneratedImage = {
  id: number
  page_id: number
  image_url: string | null
  local_path: string | null
  seed: number | null
  workflow_name: string | null
  prompt: string | null
  negative_prompt: string | null
  score: number | null
  is_selected: boolean
  created_at: string
}

export type ImageGenerationPage = {
  page_id: number
  page_no: number
  image_prompt: string | null
  status: string
  selected_image_id: number | null
  images: GeneratedImage[]
}

export type GenerateImagesPayload = {
  workflow_preset_id: number
  poll_interval_seconds: number
  candidates_per_page: number
  negative_prompt?: string | null
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
  onError: (message: string) => void
}

const requestJson = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(errorText || response.statusText)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export const listComfyWorkflows = async (): Promise<ComfyWorkflowPreset[]> => {
  const result = await requestJson<{ items: ComfyWorkflowPreset[] }>('/api/image-generation/workflows')
  return result.items
}

export const createComfyWorkflow = (
  payload: ComfyWorkflowPresetPayload,
): Promise<ComfyWorkflowPreset> =>
  requestJson<ComfyWorkflowPreset>('/api/image-generation/workflows', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateComfyWorkflow = (
  workflowId: number,
  payload: ComfyWorkflowPresetPayload,
): Promise<ComfyWorkflowPreset> =>
  requestJson<ComfyWorkflowPreset>(`/api/image-generation/workflows/${workflowId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const deleteComfyWorkflow = (workflowId: number): Promise<void> =>
  requestJson<void>(`/api/image-generation/workflows/${workflowId}`, {
    method: 'DELETE',
  })

export const listImageGenerationPages = async (taskId: number): Promise<ImageGenerationPage[]> => {
  const result = await requestJson<{ items: ImageGenerationPage[] }>(
    `/api/image-generation/script-tasks/${taskId}/pages`,
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

export const streamGenerateImagesForTask = (
  taskId: number,
  payload: GenerateImagesPayload,
  callbacks: ImageGenerationStreamCallbacks,
): Promise<void> =>
  streamSse(`/api/image-generation/script-tasks/${taskId}/generate/stream`, payload, callbacks)

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
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok || response.body === null) {
    const errorText = await response.text()
    throw new Error(errorText || response.statusText)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const handleEvent = (event: SseEvent) => {
    const parsedPayload = event.data ? JSON.parse(event.data) : {}
    if (event.event === 'error') {
      callbacks.onError(String(parsedPayload.message ?? 'Image generation stream error'))
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
