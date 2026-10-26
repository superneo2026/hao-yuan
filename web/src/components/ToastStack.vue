<script setup>
import { state, dismissToast } from '../stores/app'
import Icon from './Icon.vue'
</script>

<template>
  <div class="toast-stack">
    <div v-for="toastItem in state.toasts" :key="toastItem.id" class="toast" :class="toastItem.type">
      <Icon
        :name="toastItem.type === 'bad' ? 'alert' : toastItem.type === 'warn' ? 'alert' : toastItem.type === 'good' ? 'check' : 'sparkles'"
        :size="16"
        :style="{ color: toastItem.type === 'bad' ? 'var(--bad)' : toastItem.type === 'warn' ? 'var(--warn)' : toastItem.type === 'good' ? 'var(--good)' : 'var(--brand)' }"
      />
      <div style="flex: 1">{{ toastItem.message }}</div>
      <button class="icon-btn" style="width: 22px; height: 22px" @click="dismissToast(toastItem.id)">
        <Icon name="close" :size="13" />
      </button>
    </div>
  </div>
</template>
