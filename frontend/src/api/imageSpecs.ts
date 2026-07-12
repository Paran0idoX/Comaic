import { ApiError, apiHeaders, normalizeBackendError, parseApiErrorResponse } from './errors'

export type GenerationMode = 'preview' | 'final'
export type ImagePromptType = 'tag' | 'natural_language' | 'hybrid'
export type ImageSpecPresetKind = 'shot_planner_system_prompt' | 'negative_prompt'

export type ImageSpecPreset = {
  id: number
  name: string
  kind: ImageSpecPresetKind
  content: string
  tag_content: string
  natural_language_content: string
  description: string | null
  is_default: boolean
  created_at: string
  updated_at: string
}

export type ImageSpecPresetPayload = Omit<ImageSpecPreset, 'id' | 'created_at' | 'updated_at'>

export type ContinuityEvent = {
  id: number
  page_id: number
  page_no: number
  sequence_no: number
  event_type: string
  target_type: string
  target_key: string
  timing: 'before_page' | 'after_page'
  payload: Record<string, unknown>
  source: string
}

export type VisualSnapshot = {
  id: number
  page_id: number
  page_no: number
  state: Record<string, unknown>
  state_hash: string
  warnings: unknown[]
  created_at: string
}

export type ContinuityCompilation = {
  id: number
  task_id: number
  source_hash: string
  status: string
  events: ContinuityEvent[]
  snapshots: VisualSnapshot[]
  created_at: string
}

export type ImageSpecCompilation = {
  id: number
  task_id: number
  continuity_compilation_id: number
  source_hash: string
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  generation_mode: GenerationMode
  total_pages: number
  completed_pages: number
  total_specs: number
  completed_specs: number
  failed_pages: Array<{
    page_id: number
    page_no: number
    error_type?: string
    message?: string
  }>
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export type ImageSpec = {
  id: number
  page_id: number
  page_no: number
  snapshot_id: number
  shot_plan_id: number
  prompt_type: ImagePromptType
  generation_mode: GenerationMode
  spec: Record<string, unknown>
  positive_prompt: string
  negative_prompt: string
  required_capabilities: string[]
  warnings: Array<Record<string, string>>
  source_hash: string
  spec_hash: string
  compiler_key: string
  compiler_version: string
  created_at: string
}

export type CompileImageSpecsPayload = {
  style_profile_id: number | null
  shot_planner_preset_id: number | null
  negative_prompt_preset_id: number | null
  generation_mode: GenerationMode
  concurrency: number
  regenerate_continuity: boolean
  resume_existing: boolean
}

const requestJson = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, { ...options, headers: apiHeaders(options.headers) })
  if (!response.ok) throw await parseApiErrorResponse(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const listImageSpecs = (taskId: number): Promise<ImageSpec[]> =>
  requestJson(`/api/image-specs/script-tasks/${taskId}`)

export const listImageSpecPresets = (): Promise<ImageSpecPreset[]> =>
  requestJson('/api/image-specs/presets')

export const createImageSpecPreset = (
  payload: ImageSpecPresetPayload,
): Promise<ImageSpecPreset> =>
  requestJson('/api/image-specs/presets', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateImageSpecPreset = (
  id: number,
  payload: ImageSpecPresetPayload,
): Promise<ImageSpecPreset> =>
  requestJson(`/api/image-specs/presets/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const deleteImageSpecPreset = (id: number): Promise<void> =>
  requestJson(`/api/image-specs/presets/${id}`, { method: 'DELETE' })

export const listContinuityCompilations = (taskId: number): Promise<ContinuityCompilation[]> =>
  requestJson(`/api/image-specs/script-tasks/${taskId}/continuity`)

export const listImageSpecCompilations = (taskId: number): Promise<ImageSpecCompilation[]> =>
  requestJson(`/api/image-specs/script-tasks/${taskId}/compilations`)

export const replaceContinuityEvents = (
  compilationId: number,
  events: Array<Omit<ContinuityEvent, 'id' | 'page_id' | 'source'>>,
): Promise<ContinuityCompilation> =>
  requestJson(`/api/image-specs/compilations/${compilationId}/events`, {
    method: 'PUT',
    body: JSON.stringify({ events }),
  })

export const streamCompileImageSpecs = async (
  taskId: number,
  payload: CompileImageSpecsPayload,
  callbacks: {
    onEvent: (event: string, payload: Record<string, unknown>) => void
    onError: (error: ApiError) => void
  },
): Promise<void> => {
  const response = await fetch(`/api/image-specs/script-tasks/${taskId}/compile/stream`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify(payload),
  })
  if (!response.ok || response.body === null) throw await parseApiErrorResponse(response)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const handleChunk = (chunk: string) => {
    let event = 'message'
    const data: string[] = []
    for (const line of chunk.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (data.length === 0) return
    const parsed = JSON.parse(data.join('\n')) as Record<string, unknown>
    if (event === 'error') {
      const normalized = normalizeBackendError(parsed)
      callbacks.onError(new ApiError(normalized.message || 'ImageSpec stream error', { code: normalized.code, payload: parsed }))
    } else {
      callbacks.onEvent(event, parsed)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split(/\r?\n\r?\n/)
    buffer = chunks.pop() ?? ''
    chunks.forEach(handleChunk)
  }
  if (buffer.trim()) handleChunk(buffer)
}
