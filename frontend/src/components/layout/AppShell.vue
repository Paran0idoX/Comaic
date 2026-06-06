<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import SidebarNav from '@/components/layout/SidebarNav.vue'
import TopBar from '@/components/layout/TopBar.vue'

const route = useRoute()
const { t } = useI18n()

// 路由 meta 中的标题用于顶部栏显示当前工作区名称。
const pageTitle = computed(() => t(String(route.meta.titleKey ?? 'routeTitles.outline')))
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
        <!-- 分页脚本页有长 SSE 连接，缓存组件实例可以避免路由切换时中断生成进度消费。 -->
        <RouterView v-slot="{ Component, route }">
          <KeepAlive include="ScriptWorkspaceView">
            <component :is="Component" :key="route.name" />
          </KeepAlive>
        </RouterView>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: transparent;
}

.app-shell__aside {
  background: #0d2336;
  color: #fff;
  box-shadow: 18px 0 48px rgba(7, 17, 31, 0.18);
}

.app-shell__main {
  min-width: 0;
}

.app-shell__header {
  height: 68px;
  padding: 0;
  border-bottom: 1px solid var(--panel-border);
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(14px);
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
