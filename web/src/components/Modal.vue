<script setup>
import { t } from '../i18n'
import Icon from './Icon.vue'

defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  width: { type: String, default: '640px' },
  hideFooter: { type: Boolean, default: false }
})
const emit = defineEmits(['close'])
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @mousedown.self="emit('close')">
      <div class="modal" :style="{ width }">
        <div class="modal-head">
          <div>
            <h3>{{ title }}</h3>
            <div v-if="subtitle" class="tiny muted" style="margin-top: 2px">{{ subtitle }}</div>
          </div>
          <div class="spacer" />
          <button class="icon-btn" @click="emit('close')" :aria-label="t('common.close')" :title="t('common.close')">
            <Icon name="close" :size="17" />
          </button>
        </div>
        <div class="modal-body">
          <slot />
        </div>
        <div v-if="!hideFooter" class="modal-foot">
          <slot name="footer">
            <button class="btn" @click="emit('close')">{{ t('common.close') }}</button>
          </slot>
        </div>
      </div>
    </div>
  </Teleport>
</template>
