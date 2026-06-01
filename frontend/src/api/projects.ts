import { apiHeaders, parseApiErrorResponse } from './errors'

export type Project = {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export type ProjectListResponse = {
  items: Project[]
}

export type CreateProjectPayload = {
  title: string
}

export type UpdateProjectPayload = {
  title: string
}

// 统一封装项目 API 请求，让页面只关心业务数据和交互状态。
const request = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
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

export const listProjects = async (): Promise<Project[]> => {
  const result = await request<ProjectListResponse>('/api/projects')
  return result.items
}

export const createProject = (payload: CreateProjectPayload): Promise<Project> =>
  request<Project>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateProject = (
  projectId: number,
  payload: UpdateProjectPayload,
): Promise<Project> =>
  request<Project>(`/api/projects/${projectId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const deleteProject = (projectId: number): Promise<void> =>
  request<void>(`/api/projects/${projectId}`, {
    method: 'DELETE',
  })
