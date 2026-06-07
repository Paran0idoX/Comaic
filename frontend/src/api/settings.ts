import { apiHeaders, parseApiErrorResponse } from './errors'

export type LLMProvider =
  | 'openai_compatible'
  | 'deepseek'
  | 'anthropic'
  | 'google_genai'
  | 'mistralai'
  | 'groq'
  | 'cohere'
  | 'ollama'
  | 'aws_bedrock'
  | 'xai'

export type LLMConfig = {
  id: number
  name: string
  provider: LLMProvider
  base_url: string
  model_names: string[]
  default_model: string
  api_key: string | null
  api_key_set: boolean
  is_active: boolean
  updated_at: string
}

export type LLMProviderOption = {
  value: LLMProvider
  label: string
  requires_base_url: boolean
  model_prefixes: string[]
}

export type LLMConfigListResponse = {
  items: LLMConfig[]
  active_config_id: number | null
}

export type CreateLLMConfigPayload = {
  name: string
  provider: LLMProvider
  base_url?: string | null
  model_names: string[]
  default_model?: string | null
  api_key?: string | null
  is_active?: boolean
}

export type UpdateLLMConfigPayload = {
  name: string
  provider: LLMProvider
  base_url?: string | null
  model_names: string[]
  default_model?: string | null
  api_key?: string | null
  clear_api_key?: boolean
}

export type TestLLMConfigPayload = {
  config_id?: number | null
  provider?: LLMProvider | null
  base_url?: string | null
  model?: string | null
  api_key?: string | null
  clear_api_key?: boolean
}

export type AppSettings = {
  script_section_max_concurrency: number
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

export const listLLMConfigs = (): Promise<LLMConfigListResponse> =>
  requestJson<LLMConfigListResponse>('/api/settings/llm')

export const getAppSettings = (): Promise<AppSettings> =>
  requestJson<AppSettings>('/api/settings/app')

export const updateAppSettings = (payload: AppSettings): Promise<AppSettings> =>
  requestJson<AppSettings>('/api/settings/app', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const listLLMProviders = (): Promise<LLMProviderOption[]> =>
  requestJson<LLMProviderOption[]>('/api/settings/llm/providers')

export const createLLMConfig = (payload: CreateLLMConfigPayload): Promise<LLMConfig> =>
  requestJson<LLMConfig>('/api/settings/llm/configs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateLLMConfig = (
  configId: number,
  payload: UpdateLLMConfigPayload,
): Promise<LLMConfig> =>
  requestJson<LLMConfig>(`/api/settings/llm/configs/${configId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const deleteLLMConfig = (configId: number): Promise<void> =>
  requestJson<void>(`/api/settings/llm/configs/${configId}`, {
    method: 'DELETE',
  })

export const activateLLMConfig = (configId: number): Promise<LLMConfig> =>
  requestJson<LLMConfig>(`/api/settings/llm/configs/${configId}/activate`, {
    method: 'POST',
  })

export const testLLMConfig = (payload: TestLLMConfigPayload): Promise<{ ok: boolean }> =>
  requestJson<{ ok: boolean }>('/api/settings/llm/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
