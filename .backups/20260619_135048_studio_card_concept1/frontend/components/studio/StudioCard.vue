<template>
    <button
        type="button"
        class="block text-left p-4 rounded-lg border border-gray-100 bg-white transition-all group hover:border-gray-200 hover:shadow-md w-full"
        @click="$emit('open')"
    >
        <!-- Header: avatar + name -->
        <div class="flex items-start gap-2.5 mb-2">
            <div class="shrink-0 flex items-center justify-center w-8 h-8 rounded-md bg-gray-100 text-base overflow-hidden">
                <img v-if="isImageAvatar" :src="studio.avatar || ''" alt="" class="w-full h-full object-cover" />
                <span v-else-if="studio.avatar">{{ studio.avatar }}</span>
                <UIcon v-else name="i-heroicons-film" class="w-4 h-4 text-gray-400" />
            </div>
            <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                    <span class="font-medium text-gray-900 text-sm leading-tight truncate">{{ studio.name }}</span>
                    <span :class="scopeBadgeClass" class="shrink-0 text-[9px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded">
                        {{ scopeLabel }}
                    </span>
                </div>
                <span v-if="studio.role" class="text-[11px] text-gray-400">{{ roleLabel }}</span>
            </div>
        </div>

        <!-- Description -->
        <p v-if="studio.description" class="text-xs text-gray-500 leading-relaxed line-clamp-2 mb-3">
            {{ studio.description }}
        </p>
        <p v-else class="text-xs text-gray-300 italic mb-3">{{ $t('studio.descriptionPlaceholder') }}</p>

        <!-- Footer counts -->
        <div class="flex items-center gap-3 text-[11px] text-gray-400">
            <span class="inline-flex items-center gap-1">
                <UIcon name="i-heroicons-circle-stack" class="w-3.5 h-3.5" />
                {{ $t('studio.sourceCount', { count: studio.source_count ?? 0 }, studio.source_count ?? 0) }}
            </span>
            <span class="inline-flex items-center gap-1">
                <UIcon name="i-heroicons-users" class="w-3.5 h-3.5" />
                {{ $t('studio.memberCount', { count: studio.member_count ?? 0 }, studio.member_count ?? 0) }}
            </span>
        </div>
    </button>
</template>

<script setup lang="ts">
interface Studio {
    id: string
    name: string
    description?: string | null
    avatar?: string | null
    share_scope: string
    source_count?: number
    member_count?: number
    role?: string
}

const props = defineProps<{ studio: Studio }>()
defineEmits<{ open: [] }>()

const { t } = useI18n()

const isImageAvatar = computed(() => {
    const a = props.studio.avatar || ''
    return /^https?:\/\//.test(a) || a.startsWith('/')
})

const scopeLabel = computed(() => {
    const s = (props.studio.share_scope || 'private').toLowerCase()
    if (s === 'org') return t('studio.scopeOrg')
    if (s === 'link') return t('studio.scopeLink')
    return t('studio.scopePrivate')
})

const scopeBadgeClass = computed(() => {
    const s = (props.studio.share_scope || 'private').toLowerCase()
    if (s === 'org') return 'bg-blue-100 text-blue-700'
    if (s === 'link') return 'bg-purple-100 text-purple-700'
    return 'bg-gray-100 text-gray-600'
})

const roleLabel = computed(() => {
    const r = (props.studio.role || '').toLowerCase()
    if (r === 'owner') return t('studio.roleOwner')
    if (r === 'editor') return t('studio.roleEditor')
    if (r === 'viewer') return t('studio.roleViewer')
    return ''
})
</script>

<style scoped>
.line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
</style>
