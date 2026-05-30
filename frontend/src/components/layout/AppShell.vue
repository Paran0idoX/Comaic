<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import SidebarNav from '@/components/layout/SidebarNav.vue'
import TopBar from '@/components/layout/TopBar.vue'

const route = useRoute()
const { t } = useI18n()

// 路由 meta 中的标题用于顶部栏显示当前工作区名称。
const pageTitle = computed(() => t(String(route.meta.titleKey ?? 'routeTitles.projects')))
</script>

<template>
  <el-container class="app-shell">
    <el-aside class="app-shell__aside" width="252px">
      <SidebarNav />
    </el-aside>

    <el-container class="app-shell__main">
      <el-header class="app-shell__header">
        <TopBar :title="pageTitle" />
      </el-header>

      <el-main class="app-shell__content">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.app-shell__aside {
  background: #111827;
  color: #fff;
}

.app-shell__main {
  min-width: 0;
}

.app-shell__header {
  height: 68px;
  padding: 0;
  border-bottom: 1px solid var(--panel-border);
  background: #fff;
}

.app-shell__content {
  padding: 28px;
}

@media (max-width: 860px) {
  .app-shell {
    display: block;
  }

  .app-shell__aside {
    width: 100% !important;
  }

  .app-shell__content {
    padding: 18px;
  }
}
</style>
