import { computed, reactive, type Ref } from 'vue'

export type PromptLanguage = 'original' | 'zh' | 'en'
const languages = reactive<Record<number, PromptLanguage>>({})

/** 生图准备按脚本任务记住输出语言，与界面语言无关。 */
export const usePromptLanguage = (taskId: Ref<number | null>) => computed<PromptLanguage>({
  get: () => {
    if (taskId.value === null) return 'original'
    const cached = languages[taskId.value]
    if (cached) return cached
    try {
      const stored = localStorage.getItem(`comaic-prompt-language-${taskId.value}`)
      return stored === 'zh' || stored === 'en' ? stored : 'original'
    } catch { return 'original' }
  },
  set: (language) => {
    if (taskId.value === null) return
    languages[taskId.value] = language
    try { localStorage.setItem(`comaic-prompt-language-${taskId.value}`, language) } catch { /* 保留会话选择。 */ }
  },
})
