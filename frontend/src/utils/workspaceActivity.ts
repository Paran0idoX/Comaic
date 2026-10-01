export type ActivityKind =
  | 'script'
  | 'imageSpec'
  | 'characterReference'
  | 'referenceImage'
  | 'imageGeneration'
  | 'consistencyEvaluation'

export type ActivityStatus = 'pending' | 'running' | 'suspended' | 'failed' | 'succeeded'

export type WorkspaceActivity = {
  id: string
  kind: ActivityKind
  label: string
  status: ActivityStatus
  progress: number | null
  route: string
  projectId: number | null
  scriptTaskId?: number
  batchId?: number
  characterId?: number
  referenceTaskId?: number
  referenceSubjectId?: number
  entityType?: 'character' | 'scene' | 'prop'
  compilationId?: number
  evaluationTaskId?: number
  updatedAt: string
  refreshFailed?: boolean
}

/** 只接受正整数主键，防止缺失参数或数组被当作另一个业务对象。 */
export const positiveId = (value: unknown): number | null => {
  const first = Array.isArray(value) ? value[0] : value
  if (typeof first !== 'string' && typeof first !== 'number') return null
  const id = Number(first)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

const locatorFields = {
  projectId: 'project_id',
  scriptTaskId: 'script_task_id',
  batchId: 'batch_id',
  characterId: 'character_id',
  referenceTaskId: 'reference_task_id',
  referenceSubjectId: 'reference_subject_id',
  compilationId: 'compilation_id',
  evaluationTaskId: 'evaluation_task_id',
} as const

/** 旧记录可能已把定位信息写入 route；先读取显式信息，再合并结构化字段。 */
export const activityLocator = (activity: WorkspaceActivity) => {
  const query = new URL(activity.route, 'http://workspace.local').searchParams
  return Object.fromEntries(
    Object.entries(locatorFields).map(([field, key]) => [
      field,
      positiveId(activity[field as keyof WorkspaceActivity]) ?? positiveId(query.get(key)),
    ]),
  ) as Record<keyof typeof locatorFields, number | null>
}

export const hasExactActivityLocation = (activity: WorkspaceActivity): boolean => {
  const ids = activityLocator(activity)
  if (!ids.projectId) return false
  if (activity.kind === 'script') return ids.scriptTaskId !== null
  if (activity.kind === 'characterReference' || activity.kind === 'referenceImage') return !!ids.referenceTaskId && (!!ids.characterId || !!ids.referenceSubjectId)
  if (activity.kind === 'imageSpec') return !!ids.scriptTaskId && !!ids.compilationId
  if (activity.kind === 'imageGeneration') return !!ids.scriptTaskId && !!ids.batchId
  return !!ids.scriptTaskId && !!ids.batchId && !!ids.evaluationTaskId
}

/** 精确记录恢复对象；旧记录只打开所属项目的任务列表，不猜测第一项。 */
export const activityRoute = (activity: WorkspaceActivity): string => {
  const ids = activityLocator(activity)
  const pathByKind: Record<ActivityKind, string> = {
    script: '/scripts',
    imageSpec: '/image-specs',
    characterReference: '/visual-bible',
    referenceImage: '/visual-bible',
    imageGeneration: '/image-generation',
    consistencyEvaluation: '/image-generation',
  }
  const params = new URLSearchParams()
  if (ids.projectId) params.set('project_id', String(ids.projectId))
  const original = new URL(activity.route, 'http://workspace.local')
  const defaultTab = activity.kind === 'characterReference' || activity.kind === 'referenceImage' ? 'references'
    : activity.kind === 'consistencyEvaluation' ? 'consistency' : null
  const tab = original.searchParams.get('tab') ?? defaultTab
  if (tab) params.set('tab', tab)
  if (activity.kind === 'referenceImage') params.set('reference_task_kind', 'referenceImage')
  if (hasExactActivityLocation(activity)) {
    if (activity.entityType) params.set('entity_type', activity.entityType)
    for (const [field, key] of Object.entries(locatorFields)) {
      const id = ids[field as keyof typeof locatorFields]
      if (id) params.set(key, String(id))
    }
  } else {
    params.set('activity_legacy', '1')
  }
  return `${pathByKind[activity.kind]}?${params}`
}

export const normalizeActivityStatus = (status: string): ActivityStatus => {
  if (status === 'waiting_resource' || status === 'queued') return 'pending'
  if (status === 'pending' || status === 'running' || status === 'suspended'
    || status === 'failed' || status === 'succeeded') return status
  // 未知状态不应误报任务已完成。
  return 'pending'
}

export const taskProgressPercent = (progress: Record<string, unknown>): number | null => {
  const total = Number(progress.total ?? progress.total_tracks ?? 0)
  const completed = Number(progress.completed ?? progress.completed_tracks ?? 0)
  return total > 0 && Number.isFinite(completed)
    ? Math.max(0, Math.min(100, Math.round(completed / total * 100))) : null
}
