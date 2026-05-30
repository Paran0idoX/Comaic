import { createI18n } from 'vue-i18n'

import { messages } from './messages'

export type SupportedLocale = keyof typeof messages

const savedLocale = localStorage.getItem('comaic-locale') as SupportedLocale | null

// i18n 实例集中管理中英文文案，组件只通过 key 获取展示文本。
export const i18n = createI18n({
  legacy: false,
  locale: savedLocale ?? 'zh',
  fallbackLocale: 'zh',
  messages,
})

export const setLocale = (locale: SupportedLocale) => {
  i18n.global.locale.value = locale
  localStorage.setItem('comaic-locale', locale)
}
