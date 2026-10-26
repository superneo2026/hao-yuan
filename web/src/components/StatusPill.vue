<script setup>
import { computed } from 'vue'
import { t } from '../i18n'

const props = defineProps({
  status: { type: String, default: 'idle' },
  health: { type: String, default: '' }
})

const effective = computed(() => {
  if (['done', 'error', 'cancelled', 'queued', 'idle'].includes(props.status)) return props.status
  return props.health || props.status
})
const label = computed(() => {
  const map = {
    waiting_input: 'status.approval',
    cancelled: 'status.stopped',
    stale: 'status.stalled',
    ok: 'status.healthy'
  }
  const key = map[effective.value] || `status.${effective.value}`
  return t(key, {}, effective.value)
})
const dotClass = computed(() => (effective.value === 'waiting' ? 'waiting' : effective.value))
const badgeClass = computed(() => {
  if (['running', 'queued'].includes(effective.value)) return 'brand'
  if (effective.value === 'done') return 'good'
  if (effective.value === 'error' || effective.value === 'cancelled') return 'bad'
  if (effective.value === 'waiting_input' || effective.value === 'stale' || effective.value === 'waiting') return 'warn'
  return ''
})
</script>

<template>
  <span class="badge status-pill" :class="badgeClass">
    <span class="status-dot" :class="dotClass" />
    {{ label }}
  </span>
</template>

<style scoped>
.status-pill { gap: 7px; }
</style>
