import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import { i18n } from './i18n'
import router from './router'
import '@/assets/styles/global.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 全局注册 Element Plus，页面组件可以直接使用 el-* 组件。
app.use(ElementPlus)
// 全局注册 vue-i18n，当前支持中文和英文。
app.use(i18n)

app.mount('#app')
