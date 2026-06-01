export type BackendErrorPayload = {
  code?: string
  message?: string
  debug_message?: string
}

export class ApiError extends Error {
  code?: string
  status?: number
  payload?: unknown

  constructor(message: string, options: { code?: string; status?: number; payload?: unknown } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = options.code
    this.status = options.status
    this.payload = options.payload
  }
}

// 与 vue-i18n 的 localStorage key 保持一致，让后端也能按当前界面语言返回文案。
export const currentApiLocale = () => localStorage.getItem('comaic-locale') || 'zh'

export const apiHeaders = (headers: HeadersInit = {}): HeadersInit => ({
  'Content-Type': 'application/json',
  'X-Locale': currentApiLocale(),
  'Accept-Language': currentApiLocale(),
  ...headers,
})

export const parseApiErrorResponse = async (response: Response): Promise<ApiError> => {
  const text = await response.text()
  let payload: unknown = text

  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  const backendError = normalizeBackendError(payload)
  return new ApiError(backendError.message || response.statusText, {
    code: backendError.code,
    status: response.status,
    payload,
  })
}

export const normalizeBackendError = (payload: unknown): BackendErrorPayload => {
  if (payload !== null && typeof payload === 'object') {
    const record = payload as Record<string, unknown>
    const detail = record.detail
    if (typeof detail === 'string') {
      return {
        message: detail,
      }
    }
    if (detail !== null && typeof detail === 'object') {
      const detailRecord = detail as Record<string, unknown>
      return {
        code: typeof detailRecord.code === 'string' ? detailRecord.code : undefined,
        message: typeof detailRecord.message === 'string' ? detailRecord.message : undefined,
        debug_message:
          typeof detailRecord.debug_message === 'string' ? detailRecord.debug_message : undefined,
      }
    }
    return {
      code: typeof record.code === 'string' ? record.code : undefined,
      message: typeof record.message === 'string' ? record.message : undefined,
      debug_message: typeof record.debug_message === 'string' ? record.debug_message : undefined,
    }
  }

  return {
    message: typeof payload === 'string' ? payload : undefined,
  }
}

export const apiErrorMessage = (
  error: unknown,
  t: (key: string) => string,
  fallback: string,
): string => {
  if (error instanceof ApiError && error.code) {
    const key = `backendErrors.${error.code}`
    const translated = t(key)
    if (translated !== key) {
      return translated
    }
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}
