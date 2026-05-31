export type ScriptPage = {
  id: number
  project_id: number
  section_id: number | null
  section_no: number | null
  task_id: number | null
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
  created_at: string
  updated_at: string
  pages: ScriptPage[]
}

export type ScriptSectionListResponse = {
  items: ScriptSection[]
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

export type CreatePageScriptPayload = {
  page_no: number
  summary: string
  characters: string
  clothing: string
  scene: string
  composition: string
  character_action: string
  dialogue: string
}

export type UpdatePageScriptPayload = {
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

  return (await response.json()) as T
}

export const listProjectPages = async (projectId: number): Promise<ScriptPage[]> => {
  const result = await requestJson<ScriptPageListResponse>(`/api/projects/${projectId}/pages`)
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

export const clearPageScript = (projectId: number, pageNo: number): Promise<ScriptPage> =>
  requestJson<ScriptPage>(`/api/projects/${projectId}/pages/${pageNo}/script`, {
    method: 'DELETE',
  })

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
  const response = await fetch('/api/scripts/batch/stream', {
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
    const payload = event.data ? JSON.parse(event.data) : {}
    if (event.event === 'error') {
      callbacks.onError(String(payload.message ?? 'Script stream error'))
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
