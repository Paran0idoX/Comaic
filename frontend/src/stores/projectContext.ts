import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { listProjects, type Project } from '@/api/projects'

const STORAGE_KEY = 'comaic-selected-project-id'

const savedProjectId = Number(localStorage.getItem(STORAGE_KEY))

/**
 * 在各工作台之间共享当前项目，避免路由切换后悄悄回退到项目列表第一项。
 * 本地持久化只保存项目主键，不保存任何项目内容或敏感配置。
 */
export const useProjectContextStore = defineStore('projectContext', () => {
  const selectedProjectId = ref<number | null>(
    Number.isInteger(savedProjectId) && savedProjectId > 0 ? savedProjectId : null,
  )
  const projects = ref<Project[]>([])
  const loadingProjects = ref(false)
  let refreshPromise: Promise<void> | null = null

  /** 全局项目入口刷新失败时保留当前上下文，避免运行任务被重置。 */
  const refreshProjects = (options: { force?: boolean } = {}): Promise<void> => {
    if (refreshPromise) {
      // 项目增删改后不能复用修改前发出的列表，否则新项目会被旧列表丢弃。
      return options.force
        ? refreshPromise.catch(() => undefined).then(() => refreshProjects())
        : refreshPromise
    }
    loadingProjects.value = true
    refreshPromise = listProjects().then((items) => {
      projects.value = items
      if (!items.some((project) => project.id === selectedProjectId.value)) {
        selectedProjectId.value = items[0]?.id ?? null
      }
    }).finally(() => {
      loadingProjects.value = false
      refreshPromise = null
    })
    return refreshPromise
  }

  watch(selectedProjectId, (projectId) => {
    if (projectId === null) {
      localStorage.removeItem(STORAGE_KEY)
      return
    }
    localStorage.setItem(STORAGE_KEY, String(projectId))
  })

  return { selectedProjectId, projects, loadingProjects, refreshProjects }
})
