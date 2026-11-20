import { createRouter, createWebHistory } from 'vue-router'

import KnowledgeEvidenceView from '@/views/KnowledgeEvidenceView.vue'
import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 固定路径必须在通配模块路由之前，否则会被 :moduleKey 抢先匹配。
    { path: '/knowledge-evidence', name: 'knowledge-evidence', component: KnowledgeEvidenceView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
