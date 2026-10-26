import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'workbench', component: () => import('../views/Workbench.vue') },
  { path: '/console', name: 'console', component: () => import('../views/Console.vue') },
  { path: '/skills', name: 'skills', component: () => import('../views/Skills.vue') },
  { path: '/plugins', name: 'plugins', component: () => import('../views/Plugins.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/Settings.vue') },
  { path: '/usage', name: 'usage', component: () => import('../views/Usage.vue') },
  { path: '/orchestrator', name: 'orchestrator', component: () => import('../views/Orchestrator.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})
