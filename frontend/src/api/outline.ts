export type OutlineVersion = {
  version_id: number
  version_no: number
  outline: string
  status: string
  created_at: string
}

export type OutlineSession = {
  session_id: number
  project_id: number
  thread_id: string
  purpose: string
  outline_versions: OutlineVersion[]
  messages: OutlineMessage[]
}

export type OutlineMessage = {
  role: 'user' | 'agent'
  content: string
}

type StreamOutlineChatOptions = {
  threadId: string
  message: string
  onToken: (text: string) => void
  onOutline: (outline: OutlineVersion) => void
  onDone: (threadId: string) => void
  onError: (message: string) => void
}

type SseEvent = {
  event: string
  data: string
}

const requestJson = async <T>(url: string, options: RequestInit): Promise<T> => {
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

export const resolveOutlineSession = (projectId: number): Promise<OutlineSession> =>
  requestJson<OutlineSession>('/api/outline/sessions/resolve', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  })

// 后端使用 POST SSE，浏览器原生 EventSource 不支持 POST，所以这里手动解析 ReadableStream。
export const streamOutlineChat = async ({
  threadId,
  message,
  onToken,
  onOutline,
  onDone,
  onError,
}: StreamOutlineChatOptions): Promise<void> => {
  const response = await fetch('/api/outline/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      thread_id: threadId,
      message,
    }),
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

    if (event.event === 'token') {
      onToken(String(payload.text ?? ''))
    } else if (event.event === 'outline') {
      onOutline(payload as OutlineVersion)
    } else if (event.event === 'done') {
      onDone(String(payload.thread_id ?? threadId))
    } else if (event.event === 'error') {
      onError(String(payload.message ?? 'Stream error'))
    }
  }

  // SSE 以空行分隔事件块，读取流时可能会把半个事件切开，所以用 buffer 拼接。
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
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart())
    }
  }

  return {
    event,
    data: dataLines.join('\n'),
  }
}
