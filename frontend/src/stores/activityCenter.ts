import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { getScriptTask } from '@/api/scripts'
import { getCharacterReferenceTask } from '@/api/characterReference'
import { getReferenceImageTask } from '@/api/referenceImages'
import { listGenerationBatches } from '@/api/imageGeneration'
import { listImageSpecCompilations } from '@/api/imageSpecs'
import { getConsistencyEvaluation } from '@/api/consistencyEvaluation'
import { activityLocator, normalizeActivityStatus, taskProgressPercent } from '@/utils/workspaceActivity'
import type { WorkspaceActivity } from '@/utils/workspaceActivity'

export type { ActivityKind, ActivityStatus, WorkspaceActivity } from '@/utils/workspaceActivity'

const STORAGE_KEY = 'comaic-workspace-activities'
const MAX_ACTIVITIES = 20

const readStoredActivities = (): WorkspaceActivity[] => {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (item): item is WorkspaceActivity =>
        item !== null &&
        typeof item === 'object' &&
        typeof (item as WorkspaceActivity).id === 'string' &&
        typeof (item as WorkspaceActivity).route === 'string' &&
        ['script', 'imageSpec', 'characterReference', 'referenceImage', 'imageGeneration', 'consistencyEvaluation']
          .includes((item as WorkspaceActivity).kind),
    )
  } catch {
    return []
  }
}

/**
 * 保存用户最近见过的后台任务快照，让路由切换后仍能找到暂停、失败或已完成的任务。
 * 数据只包含任务标识与状态，不保存 Prompt、图片路径或任何敏感配置。
 */
export const useActivityCenterStore = defineStore('activityCenter', () => {
  const activities = ref<WorkspaceActivity[]>(readStoredActivities())
  const refreshing = ref(false)
  let refreshPromise: Promise<void> | null = null

  const upsertActivity = (
    activity: Omit<WorkspaceActivity, 'updatedAt'> & { updatedAt?: string },
  ) => {
    const next: WorkspaceActivity = {
      ...activity,
      progress:
        activity.progress === null
          ? null
          : Math.max(0, Math.min(100, Math.round(activity.progress))),
      updatedAt: activity.updatedAt ?? new Date().toISOString(),
    }
    activities.value = [
      next,
      ...activities.value.filter((item) => item.id !== next.id),
    ].slice(0, MAX_ACTIVITIES)
  }

  const clearFinished = () => {
    activities.value = activities.value.filter((item) => item.status !== 'succeeded')
  }

  const removeActivity = (id: string) => {
    activities.value = activities.value.filter((item) => item.id !== id)
  }

  /** 离页后 SSE 会关闭，打开任务中心时用查询接口恢复真实终态。 */
  const refreshActivities = (): Promise<void> => {
    if (refreshPromise) return refreshPromise
    refreshing.value = true
    const snapshots = [...activities.value]
    // 同一脚本的多个批次/编译记录共用一次列表请求。
    const batches = new Map<number, ReturnType<typeof listGenerationBatches>>()
    const compilations = new Map<number, ReturnType<typeof listImageSpecCompilations>>()
    refreshPromise = (async () => {
      const results = await Promise.allSettled(snapshots.map(async (activity) => {
        const ids = activityLocator(activity)
        let task: { status: string; updated_at: string } | undefined
        let progress = activity.progress
        if (activity.kind === 'script' && ids.scriptTaskId) {
          const result = await getScriptTask(ids.scriptTaskId)
          if (result.project_id !== ids.projectId) throw new Error('Project mismatch')
          task = result
        } else if ((activity.kind === 'characterReference' || activity.kind === 'referenceImage') && ids.referenceTaskId) {
          const result = activity.kind === 'referenceImage' ? await getReferenceImageTask(ids.referenceTaskId) : await getCharacterReferenceTask(ids.referenceTaskId)
          if (result.project_id !== ids.projectId) throw new Error('Project mismatch')
          task = result
          progress = taskProgressPercent(result.progress)
        } else if (activity.kind === 'imageGeneration' && ids.scriptTaskId && ids.batchId) {
          if (!batches.has(ids.scriptTaskId)) {
            batches.set(ids.scriptTaskId, listGenerationBatches(ids.scriptTaskId))
          }
          task = (await batches.get(ids.scriptTaskId))?.find((item) => item.id === ids.batchId
            && item.project_id === ids.projectId)
        } else if (activity.kind === 'imageSpec' && ids.scriptTaskId && ids.compilationId) {
          if (!compilations.has(ids.scriptTaskId)) {
            compilations.set(ids.scriptTaskId, listImageSpecCompilations(ids.scriptTaskId))
          }
          const result = (await compilations.get(ids.scriptTaskId))?.find((item) => item.id === ids.compilationId)
          task = result
          if (result) progress = result.total_pages > 0
            ? Math.round(result.completed_pages / result.total_pages * 100) : null
        } else if (activity.kind === 'consistencyEvaluation' && ids.evaluationTaskId) {
          const result = await getConsistencyEvaluation(ids.evaluationTaskId)
          if (result.script_task_id !== ids.scriptTaskId) throw new Error('Task mismatch')
          task = result
          progress = taskProgressPercent(result.progress)
        } else {
          return null // 旧记录缺少主键时保留快照，点击后说明无法精确定位。
        }
        if (!task) throw new Error('Task unavailable')
        const status = normalizeActivityStatus(task.status)
        return { ...activity, status, progress: status === 'succeeded' ? 100 : progress,
          updatedAt: task.updated_at, refreshFailed: false }
      }))
      activities.value = activities.value.map((activity) => {
        const index = snapshots.findIndex((snapshot) => snapshot.id === activity.id)
        const snapshot = snapshots[index]
        // 查询期间页面可能收到更新的流式事件，不用旧查询覆盖该快照。
        if (!snapshot || activity !== snapshot || activity.updatedAt !== snapshot.updatedAt || activity.status !== snapshot.status) return activity
        const result = results[index]
        return result?.status === 'fulfilled' ? result.value ?? activity
          : { ...activity, refreshFailed: true }
      })
    })().finally(() => {
      refreshing.value = false
      refreshPromise = null
    })
    return refreshPromise
  }

  watch(
    activities,
    (value) => localStorage.setItem(STORAGE_KEY, JSON.stringify(value)),
    { deep: true },
  )

  return { activities, refreshing, upsertActivity, refreshActivities, clearFinished, removeActivity }
})
