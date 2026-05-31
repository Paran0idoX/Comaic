import { createRouter, createWebHistory } from 'vue-router'

import OutlineWorkspaceView from '@/views/OutlineWorkspaceView.vue'
import ProjectListView from '@/views/ProjectListView.vue'
import ScriptWorkspaceView from '@/views/ScriptWorkspaceView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/projects',
    },
    {
      path: '/projects',
      name: 'projects',
      component: ProjectListView,
      meta: {
        titleKey: 'routeTitles.projects',
      },
    },
    {
      path: '/outline',
      name: 'outline',
      component: OutlineWorkspaceView,
      meta: {
        titleKey: 'routeTitles.outline',
      },
    },
    {
      path: '/scripts',
      name: 'scripts',
      component: ScriptWorkspaceView,
      meta: {
        titleKey: 'routeTitles.scripts',
      },
    },
  ],
})

export default router
