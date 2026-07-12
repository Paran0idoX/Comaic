<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import en from 'element-plus/es/locale/lang/en'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import AppShell from '@/components/layout/AppShell.vue'

const { locale } = useI18n()

// Element Plus 与业务文案使用同一语言，避免中文界面混入 Select、No Data 等默认英文。
const elementLocale = computed(() => (locale.value === 'en' ? en : zhCn))
</script>

<template>
  <el-config-provider :locale="elementLocale">
    <AppShell />
  </el-config-provider>
</template>
