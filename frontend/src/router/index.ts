import { createRouter, createWebHistory } from 'vue-router'

import OutlineWorkspaceView from '@/views/OutlineWorkspaceView.vue'
import ImagePromptWorkspaceView from '@/views/ImagePromptWorkspaceView.vue'
import ImageSpecWorkspaceView from '@/views/ImageSpecWorkspaceView.vue'
import ImageGenerationWorkspaceView from '@/views/ImageGenerationWorkspaceView.vue'
import SettingsView from '@/views/SettingsView.vue'
import ScriptWorkspaceView from '@/views/ScriptWorkspaceView.vue'
import VisualBibleWorkspaceView from '@/views/VisualBibleWorkspaceView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
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
    {
      path: '/prompts',
      name: 'prompts',
      component: ImagePromptWorkspaceView,
      meta: {
        titleKey: 'routeTitles.prompts',
      },
    },
    {
      path: '/visual-bible',
      name: 'visualBible',
      component: VisualBibleWorkspaceView,
      meta: {
        titleKey: 'routeTitles.visualBible',
      },
    },
    {
      path: '/image-specs',
      name: 'imageSpecs',
      component: ImageSpecWorkspaceView,
      meta: {
        titleKey: 'routeTitles.imageSpecs',
      },
    },
    {
      path: '/image-generation',
      name: 'imageGeneration',
      component: ImageGenerationWorkspaceView,
      meta: {
        titleKey: 'routeTitles.imageGeneration',
      },
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsView,
      meta: {
        titleKey: 'routeTitles.settings',
      },
    },
  ],
})

export default router
