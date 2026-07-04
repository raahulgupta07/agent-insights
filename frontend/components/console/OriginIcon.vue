<template>
    <!-- Origin platform mark for a run. Web UI (null/empty) renders nothing.
         Uses inline brand SVGs (Slack/WhatsApp) + heroicons for the rest, never emoji. -->
    <span
        v-if="normalized"
        :title="label"
        class="inline-flex items-center justify-center shrink-0 align-middle"
    >
        <!-- Slack -->
        <svg v-if="normalized === 'slack'" :class="iconClass" style="color:#4A154B" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z" />
        </svg>
        <!-- WhatsApp -->
        <svg v-else-if="normalized === 'whatsapp'" :class="iconClass" style="color:#25D366" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.372-.025-.521-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.885-9.885 9.885M20.52 3.449C18.24 1.245 15.24 0 12.045 0 5.463 0 .104 5.334.101 11.892c0 2.096.549 4.14 1.595 5.945L0 24l6.335-1.652a12.062 12.062 0 0 0 5.71 1.447h.005c6.585 0 11.946-5.335 11.949-11.893A11.821 11.821 0 0 0 20.52 3.45" />
        </svg>
        <!-- Microsoft Teams -->
        <UIcon v-else-if="normalized === 'teams'" name="i-heroicons-user-group" :class="iconClass" style="color:#5059C9" />
        <!-- Email -->
        <UIcon v-else-if="normalized === 'email'" name="i-heroicons-envelope" :class="[iconClass, 'text-gray-500']" />
        <!-- MCP -->
        <UIcon v-else-if="normalized === 'mcp'" name="i-heroicons-puzzle-piece" :class="[iconClass, 'text-gray-500']" />
        <!-- Telegram -->
        <UIcon v-else-if="normalized === 'telegram'" name="i-heroicons-paper-airplane" :class="iconClass" style="color:#229ED9" />
        <!-- Any other non-web origin -->
        <UIcon v-else name="i-heroicons-globe-alt" :class="[iconClass, 'text-gray-400']" />
    </span>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
    platform?: string | null
    size?: string
}>(), {
    platform: null,
    size: 'w-3.5 h-3.5',
})

const iconClass = computed(() => props.size)

// Treat blank / explicit web-UI markers as "no origin" (renders nothing).
const normalized = computed(() => {
    const p = (props.platform || '').trim().toLowerCase()
    if (!p || p === 'web' || p === 'ui' || p === 'web_ui' || p === 'webui') return ''
    return p
})

const label = computed(() => {
    switch (normalized.value) {
        case 'slack': return 'Slack'
        case 'teams': return 'Microsoft Teams'
        case 'whatsapp': return 'WhatsApp'
        case 'email': return 'Email'
        case 'mcp': return 'MCP'
        case 'telegram': return 'Telegram'
        default: return normalized.value.charAt(0).toUpperCase() + normalized.value.slice(1)
    }
})
</script>
