import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { left: 0, top: 0 }
  },
  routes: [
    {
      path: '/',
      redirect: '/outline',
    },
    {
      path: '/projects',
      redirect: '/outline',
    },
    {
      path: '/outline',
      name: 'outline',
      component: () => import('@/views/OutlineWorkspaceView.vue'),
      meta: {
        titleKey: 'routeTitles.outline',
      },
    },
    {
      path: '/scripts',
      name: 'scripts',
      component: () => import('@/views/ScriptWorkspaceView.vue'),
      meta: {
        titleKey: 'routeTitles.scripts',
      },
    },
    {
      path: '/visual-bible',
      name: 'visualBible',
      component: () => import('@/views/VisualBibleWorkspaceView.vue'),
      meta: {
        titleKey: 'routeTitles.visualBible',
      },
    },
    {
      path: '/image-specs',
      name: 'imageSpecs',
      component: () => import('@/views/ImageSpecWorkspaceView.vue'),
      meta: {
        titleKey: 'routeTitles.imageSpecs',
      },
    },
    {
      path: '/image-generation',
      name: 'imageGeneration',
      component: () => import('@/views/ImageGenerationWorkspaceView.vue'),
      meta: {
        titleKey: 'routeTitles.imageGeneration',
      },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: {
        titleKey: 'routeTitles.settings',
      },
    },
  ],
})

export default router
