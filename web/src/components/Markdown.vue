<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { i18n, t } from '../i18n'

const props = defineProps({
  content: { type: String, default: '' }
})

const root = ref(null)

function render(value) {
  const raw = marked.parse(value || '', { gfm: true, breaks: true, async: false })
  return DOMPurify.sanitize(raw, { ADD_ATTR: ['target', 'rel'] })
}

const html = ref(render(props.content))

function decorate() {
  nextTick(() => {
    const el = root.value
    if (!el) return
    el.querySelectorAll('a[href]').forEach((link) => {
      if (link.getAttribute('href')?.startsWith('http')) {
        link.setAttribute('target', '_blank')
        link.setAttribute('rel', 'noopener noreferrer')
      }
    })
    el.querySelectorAll('pre').forEach((pre) => {
      if (pre.querySelector('.code-copy')) return
      const button = document.createElement('button')
      button.className = 'code-copy'
      button.type = 'button'
      button.textContent = t('markdown.copy')
      button.addEventListener('click', async () => {
        const code = pre.querySelector('code')?.innerText ?? pre.innerText
        try {
          await navigator.clipboard.writeText(code)
          button.textContent = t('markdown.copied')
          setTimeout(() => { button.textContent = t('markdown.copy') }, 1200)
        } catch {
          button.textContent = t('markdown.failed')
        }
      })
      pre.appendChild(button)
    })
  })
}

watch(
  () => props.content,
  (value) => {
    html.value = render(value)
    decorate()
  }
)

watch(
  () => i18n.locale,
  () => {
    html.value = render(props.content)
    decorate()
  }
)

onMounted(decorate)
</script>

<template>
  <div ref="root" class="markdown" v-html="html" />
</template>
