<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { closePalette, selectSession, setTheme, state } from '../stores/app'
import { kindLabel, statusLabel, t } from '../i18n'
import Icon from './Icon.vue'

const router = useRouter()
const query = ref('')
const active = ref(0)
const input = ref(null)

const baseCommands = [
  { id: 'new', titleKey: 'command.new', hintKey: 'command.newHint', icon: 'plus', run: () => { state.newTaskOpen = true } },
  { id: 'workbench', titleKey: 'command.workbench', hintKey: 'command.workbenchHint', icon: 'terminal', run: () => router.push('/') },
  { id: 'console', titleKey: 'command.console', hintKey: 'command.consoleHint', icon: 'activity', run: () => router.push('/console') },
  { id: 'skills', titleKey: 'command.skills', hintKey: 'command.skillsHint', icon: 'sparkles', run: () => router.push('/skills') },
  { id: 'plugins', titleKey: 'command.plugins', hintKey: 'command.pluginsHint', icon: 'puzzle', run: () => router.push('/plugins') },
  { id: 'orchestrator', titleKey: 'command.orchestrator', hintKey: 'command.orchestratorHint', icon: 'network', run: () => router.push('/orchestrator') },
  { id: 'usage', titleKey: 'command.usage', hintKey: 'command.usageHint', icon: 'chart', run: () => router.push('/usage') },
  { id: 'settings', titleKey: 'command.settings', hintKey: 'command.settingsHint', icon: 'settings', run: () => router.push('/settings') },
  { id: 'theme', titleKey: 'command.theme', hintKey: 'command.themeHint', icon: 'moon', run: () => setTheme(state.theme === 'dark' ? 'light' : 'dark') }
]

const commands = computed(() => {
  const search = query.value.trim().toLowerCase()
  const sessionCommands = state.sessions.slice(0, 30).map((session) => ({
    id: `s-${session.id}`,
    title: session.title || t('session.untitled'),
    hint: `${kindLabel(session.kind)} · ${statusLabel(session.status)}`,
    icon: 'message',
    run: () => {
      selectSession(session.id)
      router.push('/')
    }
  }))
  const all = [
    ...baseCommands.map((item) => ({ ...item, title: t(item.titleKey), hint: t(item.hintKey) })),
    ...sessionCommands
  ]
  if (!search) return all
  return all.filter((item) => `${item.title} ${item.hint}`.toLowerCase().includes(search))
})

watch(
  () => state.paletteOpen,
  async (open) => {
    if (open) {
      query.value = ''
      active.value = 0
      await nextTick()
      input.value?.focus()
    }
  }
)

watch(commands, () => {
  active.value = Math.min(active.value, Math.max(0, commands.value.length - 1))
})

function execute(command) {
  if (!command) return
  closePalette()
  setTimeout(() => command.run(), 10)
}

function onKey(event) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    active.value = (active.value + 1) % Math.max(1, commands.value.length)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    active.value = (active.value - 1 + commands.value.length) % Math.max(1, commands.value.length)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    execute(commands.value[active.value])
  } else if (event.key === 'Escape') {
    closePalette()
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="state.paletteOpen" class="overlay command-overlay" @mousedown.self="closePalette">
      <div class="command-modal">
        <div class="command-search">
          <Icon name="search" :size="18" />
          <input
            ref="input"
            v-model="query"
            class="command-input"
            :placeholder="t('command.search')"
            @keydown="onKey"
          />
          <span class="kbd">ESC</span>
        </div>
        <div class="command-list">
          <button
            v-for="(command, index) in commands"
            :key="command.id"
            class="command-item"
            :class="{ active: index === active }"
            @mouseenter="active = index"
            @click="execute(command)"
          >
            <span class="command-icon"><Icon :name="command.icon" :size="16" /></span>
            <span class="command-copy">
              <span class="command-title">{{ command.title }}</span>
              <span class="command-hint">{{ command.hint }}</span>
            </span>
            <Icon name="arrow-right" :size="14" class="command-arrow" />
          </button>
          <div v-if="!commands.length" class="command-empty">{{ t('common.noResults') }}</div>
        </div>
        <div class="command-foot">
          <span><span class="kbd">↑↓</span> {{ t('command.navigate') }}</span>
          <span><span class="kbd">↵</span> {{ t('command.run') }}</span>
          <span><span class="kbd">esc</span> {{ t('command.close') }}</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.command-overlay { align-items: start; padding-top: min(16vh, 150px); }
.command-modal {
  width: min(620px, calc(100vw - 32px));
  background: var(--surface); border: 1px solid var(--line-strong);
  border-radius: 18px; box-shadow: var(--shadow-soft); overflow: hidden;
  animation: slide-up .2s var(--ease);
}
.command-search { display: flex; align-items: center; gap: 11px; padding: 15px 17px; border-bottom: 1px solid var(--line); color: var(--muted); }
.command-input { flex: 1; background: transparent; border: none; outline: none; font-size: 15px; color: var(--ink); }
.command-list { max-height: min(52vh, 430px); overflow-y: auto; padding: 7px; }
.command-item {
  width: 100%; display: flex; align-items: center; gap: 11px; padding: 9px 10px;
  border-radius: 10px; border: 1px solid transparent; background: transparent;
  text-align: left; color: var(--ink-2);
}
.command-item.active { background: var(--brand-soft); border-color: var(--brand-line); color: var(--ink); }
.command-icon { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; background: var(--surface-2); color: var(--muted); flex: 0 0 30px; }
.command-item.active .command-icon { color: var(--brand); background: color-mix(in srgb, var(--brand) 14%, transparent); }
.command-copy { display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1; }
.command-title { font-size: 13.5px; font-weight: 550; }
.command-hint { font-size: 11.5px; color: var(--faint); }
.command-arrow { opacity: 0; color: var(--brand); }
.command-item.active .command-arrow { opacity: 1; }
.command-empty { padding: 24px; text-align: center; color: var(--faint); }
.command-foot { display: flex; gap: 16px; padding: 9px 16px; border-top: 1px solid var(--line); color: var(--faint); font-size: 11px; background: var(--surface-2); }
.kbd { display: inline-grid; place-items: center; min-width: 20px; height: 19px; padding: 0 5px; border-radius: 5px; border: 1px solid var(--line-strong); background: var(--surface-3); color: var(--muted); font-size: 10px; font-family: var(--font-mono); }
</style>
