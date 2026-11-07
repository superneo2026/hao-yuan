import { createRouter, createWebHashHistory } from 'vue-router'

const remoteViews = import.meta.glob('../views/RemoteManagement.vue')
const remoteView = remoteViews['../views/RemoteManagement.vue']

const routes = [
  { path: '/', name: 'workbench', component: () => import('../views/Workbench.vue') },
  { path: '/s/:id', name: 'session', component: () => import('../views/Workbench.vue') },
  { path: '/console', name: 'console', component: () => import('../views/Console.vue') },
  { path: '/skills', name: 'skills', component: () => import('../views/Skills.vue') },
  { path: '/plugins', name: 'plugins', component: () => import('../views/Plugins.vue') },
  { path: '/plugins/center', name: 'plugin-center', component: () => import('../views/Plugins.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/Settings.vue') },
  { path: '/usage', name: 'usage', component: () => import('../views/Usage.vue') },
  { path: '/orchestrator', name: 'orchestrator', component: () => import('../views/Orchestrator.vue') }
]

if (remoteView) {
  routes.push({ path: '/remote', name: 'remote', component: remoteView })
  routes.push({ path: '/remote/system/:id', name: 'remote-system', component: remoteView })
}

routes.push({ path: '/:pathMatch(.*)*', redirect: '/' })

export default createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})
