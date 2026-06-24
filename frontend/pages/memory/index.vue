<template>
    <div class="flex justify-center px-4 md:px-6 text-sm bg-[#FBFAF6] min-h-full">
        <div class="w-full max-w-7xl py-2 text-[#1f2328]">
            <!-- Header -->
            <div class="flex items-start justify-between gap-4 mb-6">
                <div>
                    <h1
                        class="text-2xl font-semibold text-[#1f2328] tracking-tight flex items-center"
                        style="font-family: ui-serif, Georgia, 'Times New Roman', serif"
                    >Agent Memory</h1>
                    <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">
                        Facts the agent learned mid-chat. Shared memories need your approval before
                        any chat can recall them.
                    </p>
                </div>
            </div>

            <!-- Tabs -->
            <div class="flex items-center gap-1 border-b border-[#E7E5DD] mb-5">
                <button
                    v-for="tab in tabs"
                    :key="tab.key"
                    type="button"
                    @click="setTab(tab.key)"
                    class="-mb-px flex items-center gap-1.5 rounded-t-lg px-3 py-2 text-sm transition"
                    :class="tab.key === activeTab
                        ? 'bg-[#ECEAE1] text-[#1f2328] font-medium border-b-2 border-[#C2683F]'
                        : 'text-[#6b6b6b] hover:text-[#1f2328] hover:bg-[#F4F1EA] border-b-2 border-transparent'"
                >
                    {{ tab.label }}
                    <span
                        class="rounded-full px-1.5 py-0.5 text-[11px]"
                        :class="tab.key === activeTab ? 'bg-white text-[#6b6b6b]' : 'bg-[#ECEAE1] text-[#9a958c]'"
                    >{{ tab.key === activeTab ? memories.length : '' }}</span>
                </button>
            </div>

            <!-- Loading -->
            <div v-if="loading" class="flex items-center justify-center py-20 text-[#9a958c]">
                <Icon name="heroicons:arrow-path" class="w-5 h-5 animate-spin me-2" />
                <span class="text-sm">Loading memories…</span>
            </div>

            <!-- Error -->
            <div v-else-if="error" class="rounded-2xl border border-[#E7E5DD] bg-[#F3E7DF] p-4 text-sm text-[#A8542F]">
                {{ error }}
                <button
                    type="button"
                    class="ms-2 rounded-lg px-2 py-0.5 text-xs font-medium text-[#C2683F] hover:bg-white/60"
                    @click="fetchMemories"
                >
                    Retry
                </button>
            </div>

            <template v-else>
                <!-- Empty state -->
                <div v-if="memories.length === 0" class="flex flex-col items-center justify-center py-20 text-center">
                    <span class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4F1EA] border border-[#E7E5DD] text-[#C2683F]">
                        <UIcon name="i-heroicons-bookmark-square" class="w-6 h-6" />
                    </span>
                    <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: ui-serif, Georgia, 'Times New Roman', serif">{{ emptyTitle }}</h3>
                    <p class="mt-1 text-sm text-[#9a958c] max-w-md leading-relaxed">
                        {{ emptyHint }}
                    </p>
                    <p class="mt-3 text-xs text-[#9a958c] max-w-md leading-relaxed">
                        Agent memory may be off — enable it in Feature Flags.
                    </p>
                </div>

                <!-- Memory rows -->
                <div v-else class="flex flex-col gap-3">
                    <div
                        v-for="mem in memories"
                        :key="mem.id"
                        class="flex flex-col gap-3 rounded-2xl border border-[#E7E5DD] bg-white p-4 transition hover:shadow-sm"
                    >
                        <!-- Text -->
                        <div class="flex items-start gap-2">
                            <Icon name="heroicons:sparkles" class="w-[17px] h-[17px] text-[#C2683F] shrink-0 mt-0.5" />
                            <p class="text-[15px] text-[#1f2328] leading-relaxed" style="font-family: ui-serif, Georgia, 'Times New Roman', serif">
                                {{ mem.text }}
                            </p>
                        </div>

                        <!-- Meta line -->
                        <div class="flex flex-wrap items-center gap-2 text-[11px] text-[#9a958c]">
                            <span
                                class="inline-flex items-center rounded-full border border-[#E7E5DD] bg-[#F4F1EA] px-2 py-0.5 font-medium text-[#6b6b6b]"
                            >{{ scopeLabel(mem.scope) }}</span>
                            <span v-if="mem.source" class="inline-flex items-center">
                                <Icon name="heroicons:bolt" class="w-3 h-3 me-0.5 text-[#9a958c]" />
                                {{ mem.source }}
                            </span>
                            <span v-if="mem.mem_key" style="font-family: ui-monospace, monospace">{{ mem.mem_key }}</span>
                            <span v-if="mem.created_at" class="ms-auto">{{ relativeTime(mem.created_at) }}</span>
                        </div>

                        <!-- Actions (pending only) -->
                        <div v-if="activeTab === 'pending'" class="pt-3 border-t border-[#E7E5DD] flex items-center gap-2">
                            <button
                                type="button"
                                class="inline-flex items-center gap-1.5 rounded-xl bg-[#C2683F] px-3 py-1.5 font-medium text-white transition hover:bg-[#A8542F] disabled:opacity-50 disabled:cursor-not-allowed"
                                :disabled="acting[mem.id]"
                                @click="approve(mem)"
                            >
                                <Icon
                                    :name="acting[mem.id] === 'approve' ? 'heroicons:arrow-path' : 'heroicons:check'"
                                    class="w-4 h-4"
                                    :class="{ 'animate-spin': acting[mem.id] === 'approve' }"
                                />
                                Approve
                            </button>
                            <button
                                type="button"
                                class="inline-flex items-center gap-1.5 rounded-xl border border-[#E7E5DD] bg-white px-3 py-1.5 font-medium text-[#1f2328] transition hover:bg-[#F3E7DF] disabled:opacity-50 disabled:cursor-not-allowed"
                                :disabled="acting[mem.id]"
                                @click="reject(mem)"
                            >
                                <Icon
                                    :name="acting[mem.id] === 'reject' ? 'heroicons:arrow-path' : 'heroicons:x-mark'"
                                    class="w-4 h-4 text-[#A8542F]"
                                    :class="{ 'animate-spin': acting[mem.id] === 'reject' }"
                                />
                                Reject
                            </button>
                        </div>
                    </div>
                </div>
            </template>
        </div>
    </div>
</template>

<script setup lang="ts">
definePageMeta({
    auth: true,
    layout: 'default'
})

interface Memory {
    id: string
    text: string
    mem_key?: string
    scope?: string
    status?: string
    source?: string
    user_id?: string
    data_source_id?: string
    created_at?: string
}

type TabKey = 'pending' | 'approved' | 'personal'

const toast = useToast()

const tabs: { key: TabKey; label: string }[] = [
    { key: 'pending', label: 'Pending' },
    { key: 'approved', label: 'Approved' },
    { key: 'personal', label: 'Personal' },
]

const activeTab = ref<TabKey>('pending')
const memories = ref<Memory[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const acting = ref<Record<string, 'approve' | 'reject' | undefined>>({})

const scopeLabel = (scope?: string) => {
    const s = (scope || '').toLowerCase()
    if (s === 'org' || s === 'organization' || s === 'shared') return 'Shared'
    if (s === 'global') return 'Global'
    return 'Personal'
}

const emptyTitle = computed(() => {
    if (activeTab.value === 'pending') return 'No pending memories'
    if (activeTab.value === 'approved') return 'No approved memories'
    return 'No personal memories'
})

const emptyHint = computed(() => {
    if (activeTab.value === 'pending') return "The agent hasn't proposed anything to share yet."
    if (activeTab.value === 'approved') return 'Approved shared memories the agent can recall will appear here.'
    return 'Facts the agent learned just for you will appear here.'
})

const relativeTime = (iso: string) => {
    const then = new Date(iso).getTime()
    if (Number.isNaN(then)) return ''
    const diff = Date.now() - then
    const sec = Math.floor(diff / 1000)
    if (sec < 60) return 'just now'
    const min = Math.floor(sec / 60)
    if (min < 60) return `${min}m ago`
    const hr = Math.floor(min / 60)
    if (hr < 24) return `${hr}h ago`
    const day = Math.floor(hr / 24)
    if (day < 30) return `${day}d ago`
    return new Date(iso).toLocaleDateString()
}

const queryFor = (tab: TabKey) => {
    if (tab === 'pending') return '?status=pending'
    if (tab === 'approved') return '?status=approved'
    return '?scope=personal'
}

const fetchMemories = async () => {
    loading.value = true
    error.value = null
    try {
        const { data, error: fetchErr } = await useMyFetch<Memory[]>(`/api/agent/memories${queryFor(activeTab.value)}`, { method: 'GET' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        memories.value = data.value || []
    } catch (e: any) {
        console.error('Failed to fetch memories:', e)
        error.value = 'Failed to load memories.'
    } finally {
        loading.value = false
    }
}

const setTab = (tab: TabKey) => {
    if (tab === activeTab.value) return
    activeTab.value = tab
    fetchMemories()
}

const approve = async (mem: Memory) => {
    acting.value = { ...acting.value, [mem.id]: 'approve' }
    try {
        const { error: fetchErr } = await useMyFetch(`/api/agent/memories/${mem.id}/approve`, { method: 'POST' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        memories.value = memories.value.filter(m => m.id !== mem.id)
        toast.add({ title: 'Memory approved', description: 'The agent can now recall this.', color: 'green' })
    } catch (e: any) {
        console.error('Failed to approve memory:', e)
        toast.add({ title: 'Could not approve', description: 'Please try again.', color: 'red' })
    } finally {
        const next = { ...acting.value }
        delete next[mem.id]
        acting.value = next
    }
}

const reject = async (mem: Memory) => {
    acting.value = { ...acting.value, [mem.id]: 'reject' }
    try {
        const { error: fetchErr } = await useMyFetch(`/api/agent/memories/${mem.id}/reject`, { method: 'POST' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        memories.value = memories.value.filter(m => m.id !== mem.id)
        toast.add({ title: 'Memory rejected', description: 'It was retired.', color: 'orange' })
    } catch (e: any) {
        console.error('Failed to reject memory:', e)
        toast.add({ title: 'Could not reject', description: 'Please try again.', color: 'red' })
    } finally {
        const next = { ...acting.value }
        delete next[mem.id]
        acting.value = next
    }
}

onMounted(() => {
    fetchMemories()
})
</script>
