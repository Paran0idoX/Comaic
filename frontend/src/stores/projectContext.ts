import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

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

  watch(selectedProjectId, (projectId) => {
    if (projectId === null) {
      localStorage.removeItem(STORAGE_KEY)
      return
    }
    localStorage.setItem(STORAGE_KEY, String(projectId))
  })

  return { selectedProjectId }
})
