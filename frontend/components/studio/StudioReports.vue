<template>
    <div>
        <div class="mb-4 flex items-start justify-between gap-3">
            <div>
                <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Reports</h2>
                <p class="text-xs text-[#6b6b6b] mt-0.5">
                    Schedule <span class="font-medium text-[#1f2328]">this agent</span> to run a prompt on a cadence and email the result to subscribers — sent from the agent's own email identity (see <span class="font-medium text-[#1f2328]">Email / SMTP</span>).
                </p>
            </div>
            <button
                v-if="canEdit && !unavailable"
                @click="openCreate"
                class="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-[#C2541E] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#A8330F] transition-colors"
            >
                <UIcon name="i-heroicons-plus" class="w-4 h-4" /> New report
            </button>
        </div>

        <!-- flag off / not enabled -->
        <div v-if="unavailable" class="rounded-2xl border border-[#E9E0D3] bg-white p-6 text-[12px] text-[#9a958c] flex items-center gap-2">
            <UIcon name="i-heroicons-information-circle" class="w-4 h-4" /> Scheduled reports aren't enabled for this org yet.
        </div>

        <template v-else>
            <!-- loading -->
            <div v-if="loading" class="rounded-2xl border border-[#E9E0D3] bg-white flex items-center justify-center py-10 text-[#9a958c]">
                <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">Loading…</span>
            </div>

            <!-- empty state -->
            <div v-else-if="!reports.length" class="rounded-2xl border border-[#E9E0D3] bg-white p-8 text-center">
                <div class="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-[#F6EFEA]">
                    <UIcon name="i-heroicons-paper-airplane" class="w-5 h-5 text-[#C2541E]" />
                </div>
                <h3 class="text-sm font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">No scheduled reports yet</h3>
                <p class="mx-auto mt-1 max-w-md text-[12px] leading-relaxed text-[#9a958c]">
                    Set a cadence, write what to send, and pick who receives it. Delivery uses this agent's email identity.
                </p>
                <button
                    v-if="canEdit"
                    @click="openCreate"
                    class="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[#C2541E] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#A8330F] transition-colors"
                >
                    <UIcon name="i-heroicons-plus" class="w-4 h-4" /> New report
                </button>
            </div>

            <!-- list -->
            <div v-else class="space-y-2">
                <div
                    v-for="r in reports"
                    :key="r.id"
                    class="rounded-2xl border border-[#E9E0D3] bg-white p-4 flex items-start gap-3"
                >
                    <div class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#F6EFEA]">
                        <UIcon :name="formatIcon(r.format)" class="w-4 h-4 text-[#C2541E]" />
                    </div>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="text-[13px] font-medium text-[#1f2328] truncate">{{ r.title || 'Scheduled report' }}</span>
                            <span
                                class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                                :class="r.is_active ? 'bg-[#E7F2EA] text-[#2E6B43]' : 'bg-[#F1EFEA] text-[#8a857c]'"
                            >
                                <span class="h-1.5 w-1.5 rounded-full" :class="r.is_active ? 'bg-[#2E9E55]' : 'bg-[#b7b1a6]'" />
                                {{ r.is_active ? 'Active' : 'Paused' }}
                            </span>
                        </div>
                        <div class="mt-1 flex items-center gap-3 flex-wrap text-[11px] text-[#9a958c]">
                            <span class="inline-flex items-center gap-1"><UIcon name="i-heroicons-clock" class="w-3.5 h-3.5" /> {{ humanCron(r.cron_schedule) }}</span>
                            <span class="inline-flex items-center gap-1"><UIcon name="i-heroicons-users" class="w-3.5 h-3.5" /> {{ recipientsLabel(r.subscribers) }}</span>
                            <span class="inline-flex items-center gap-1"><UIcon name="i-heroicons-arrow-path" class="w-3.5 h-3.5" /> {{ lastRunLabel(r.last_run_at) }}</span>
                        </div>
                        <p v-if="r.prompt_content" class="mt-1 text-[11px] text-[#6b6b6b] line-clamp-2">{{ r.prompt_content }}</p>
                    </div>
                    <div v-if="canEdit" class="flex shrink-0 items-center gap-1">
                        <button @click="runNow(r)" :disabled="busyId === r.id" title="Send test now" class="rounded-lg p-1.5 text-[#6b6b6b] hover:bg-[#F6EFEA] hover:text-[#C2541E] disabled:opacity-50">
                            <UIcon name="i-heroicons-paper-airplane" class="w-4 h-4" />
                        </button>
                        <button @click="toggleActive(r)" :disabled="busyId === r.id" :title="r.is_active ? 'Pause' : 'Resume'" class="rounded-lg p-1.5 text-[#6b6b6b] hover:bg-[#F6EFEA] hover:text-[#C2541E] disabled:opacity-50">
                            <UIcon :name="r.is_active ? 'i-heroicons-pause' : 'i-heroicons-play'" class="w-4 h-4" />
                        </button>
                        <button @click="openEdit(r)" title="Edit" class="rounded-lg p-1.5 text-[#6b6b6b] hover:bg-[#F6EFEA] hover:text-[#C2541E]">
                            <UIcon name="i-heroicons-pencil-square" class="w-4 h-4" />
                        </button>
                        <button @click="remove(r)" :disabled="busyId === r.id" title="Delete" class="rounded-lg p-1.5 text-[#6b6b6b] hover:bg-[#FBECEC] hover:text-[#b3261e] disabled:opacity-50">
                            <UIcon name="i-heroicons-trash" class="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </div>
        </template>

        <!-- create / edit modal -->
        <UModal v-model="modalOpen" :ui="{ width: 'sm:max-w-lg' }">
            <div class="p-5">
                <h3 class="text-base font-semibold text-[#1f2328] mb-3" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                    {{ editing ? 'Edit scheduled report' : 'New scheduled report' }}
                </h3>

                <div class="space-y-3.5">
                    <div>
                        <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Title <span class="text-[#9a958c]">(optional)</span></label>
                        <UInput v-model="form.title" size="sm" placeholder="Daily revenue summary" />
                    </div>

                    <div>
                        <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Prompt</label>
                        <textarea
                            v-model="form.prompt_content"
                            rows="3"
                            placeholder="Summarize yesterday's sales by region and flag anything unusual."
                            class="w-full text-xs text-[#1f2328] bg-white border border-[#E9E0D3] rounded-lg px-3 py-2 focus:outline-none focus:border-[#C2541E] resize-y"
                        />
                    </div>

                    <div>
                        <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Cadence</label>
                        <div class="flex flex-wrap gap-1.5 mb-2">
                            <button
                                v-for="p in cadencePresets"
                                :key="p.value"
                                @click="form.cron_schedule = p.value; cadenceMode = p.key"
                                type="button"
                                class="rounded-lg border px-2.5 py-1 text-[11px] transition-colors"
                                :class="cadenceMode === p.key ? 'border-[#E8C9B5] bg-[#F6EFEA] text-[#A8330F]' : 'border-[#E9E0D3] text-[#6b6b6b] hover:border-[#dcd9cf]'"
                            >{{ p.label }}</button>
                            <button
                                @click="cadenceMode = 'custom'"
                                type="button"
                                class="rounded-lg border px-2.5 py-1 text-[11px] transition-colors"
                                :class="cadenceMode === 'custom' ? 'border-[#E8C9B5] bg-[#F6EFEA] text-[#A8330F]' : 'border-[#E9E0D3] text-[#6b6b6b] hover:border-[#dcd9cf]'"
                            >Custom cron</button>
                        </div>
                        <UInput v-if="cadenceMode === 'custom'" v-model="form.cron_schedule" size="sm" placeholder="0 8 * * 1-5" />
                        <p class="text-[10px] text-[#9a958c] mt-1">{{ humanCron(form.cron_schedule) }} · <code class="text-[#8a857c]">{{ form.cron_schedule }}</code></p>
                    </div>

                    <div>
                        <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Recipients</label>
                        <div class="flex gap-1.5">
                            <UInput v-model="emailDraft" size="sm" placeholder="person@acme.com" class="flex-1" @keydown.enter.prevent="addEmail" />
                            <button @click="addEmail" type="button" class="rounded-lg border border-[#E9E0D3] px-2.5 text-xs text-[#6b6b6b] hover:border-[#dcd9cf]">Add</button>
                        </div>
                        <div v-if="form.subscribers.length" class="mt-2 flex flex-wrap gap-1.5">
                            <span v-for="(s, i) in form.subscribers" :key="i" class="inline-flex items-center gap-1 rounded-full bg-[#F1EFEA] px-2 py-0.5 text-[11px] text-[#1f2328]">
                                {{ s.address || s.id }}
                                <button @click="form.subscribers.splice(i, 1)" type="button" class="text-[#9a958c] hover:text-[#b3261e]"><UIcon name="i-heroicons-x-mark" class="w-3 h-3" /></button>
                            </span>
                        </div>
                        <div v-if="members.length" class="mt-2">
                            <span class="text-[10px] text-[#9a958c]">Org members:</span>
                            <div class="mt-1 flex flex-wrap gap-1.5">
                                <button v-for="m in members" :key="m.id" @click="addMember(m)" type="button" class="rounded-full border border-[#E9E0D3] px-2 py-0.5 text-[11px] text-[#6b6b6b] hover:border-[#dcd9cf]">+ {{ m.name || m.email }}</button>
                            </div>
                        </div>
                    </div>

                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Format</label>
                            <select v-model="form.format" class="w-full text-xs text-[#1f2328] bg-white border border-[#E9E0D3] rounded-lg px-3 py-2 focus:outline-none focus:border-[#C2541E]">
                                <option value="auto">Auto</option>
                                <option value="table">Table</option>
                                <option value="dashboard">Dashboard</option>
                                <option value="artifact">Artifact</option>
                                <option value="workflow">Workflow</option>
                            </select>
                            <p class="mt-1 text-[10px] leading-snug text-[#8a857c]">{{ formatHint(form.format) }}</p>
                        </div>
                        <div class="flex items-end">
                            <label class="flex items-center gap-2 cursor-pointer">
                                <UToggle v-model="form.is_active" />
                                <span class="text-[11px] text-[#1f2328]">{{ form.is_active ? 'Active' : 'Paused' }}</span>
                            </label>
                        </div>
                    </div>
                </div>

                <div class="mt-5 flex items-center justify-end gap-2">
                    <button @click="modalOpen = false" class="rounded-lg border border-[#E9E0D3] px-3 py-1.5 text-xs text-[#6b6b6b] hover:border-[#dcd9cf]">Cancel</button>
                    <button @click="save" :disabled="saving || !canSave" class="rounded-lg bg-[#C2541E] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#A8330F] disabled:opacity-50">
                        {{ saving ? 'Saving…' : (editing ? 'Save changes' : 'Create report') }}
                    </button>
                </div>
            </div>
        </UModal>
    </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'

const props = defineProps<{ studioId: string; sources?: any[]; canEdit?: boolean }>()
const toast = useToast()

const loading = ref(true)
const unavailable = ref(false)
const reports = ref<any[]>([])
const members = ref<any[]>([])
const busyId = ref<string | null>(null)

const modalOpen = ref(false)
const editing = ref<any>(null)
const saving = ref(false)
const emailDraft = ref('')
const cadenceMode = ref<'daily' | 'weekly' | 'monthly' | 'custom'>('daily')

const cadencePresets = [
    { key: 'daily', label: 'Daily 8am', value: '0 8 * * *' },
    { key: 'weekly', label: 'Weekly (Mon)', value: '0 8 * * 1' },
    { key: 'monthly', label: 'Monthly (1st)', value: '0 8 1 * *' },
]

const form = reactive<any>({
    title: '',
    prompt_content: '',
    cron_schedule: '0 8 * * *',
    subscribers: [] as any[],
    format: 'auto',
    is_active: true,
})

const canSave = computed(() => form.prompt_content.trim().length > 0 && form.cron_schedule.trim().length > 0)

function formatIcon(fmt: string) {
    if (fmt === 'table') return 'i-heroicons-table-cells'
    if (fmt === 'dashboard') return 'i-heroicons-presentation-chart-bar'
    if (fmt === 'artifact') return 'i-heroicons-document-chart-bar'
    if (fmt === 'workflow') return 'i-heroicons-bolt'
    return 'i-heroicons-sparkles'
}

function formatHint(fmt: string) {
    if (fmt === 'table') return 'Single result table in the email body.'
    if (fmt === 'dashboard') return 'Inline image plus a PDF of a multi-widget dashboard.'
    if (fmt === 'artifact') return 'A preview with the deck or PDF attached.'
    if (fmt === 'workflow') return 'A workflow run timeline with its outputs.'
    return 'Let the system auto-detect the best layout.'
}

function humanCron(cron: string) {
    if (!cron) return 'No schedule'
    const parts = cron.trim().split(/\s+/)
    if (parts.length < 5) return cron
    const [min, hour, dom, , dow] = parts
    const time = (!isNaN(+hour) && !isNaN(+min)) ? `${String(+hour).padStart(2, '0')}:${String(+min).padStart(2, '0')}` : ''
    const dowNames: Record<string, string> = { '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun' }
    if (dom !== '*' && dow === '*') return `Monthly on day ${dom}${time ? ' at ' + time : ''}`
    if (dow !== '*') {
        const days = dow.split(',').map((d) => dowNames[d] || d).join(', ')
        return `Weekly on ${days}${time ? ' at ' + time : ''}`
    }
    return `Daily${time ? ' at ' + time : ''}`
}

function recipientsLabel(subs: any[]) {
    if (!subs || !subs.length) return 'No recipients'
    const n = subs.length
    const first = subs[0].address || subs[0].id || ''
    return n === 1 ? first : `${first} +${n - 1}`
}

function lastRunLabel(ts: string | null) {
    if (!ts) return 'Never run'
    const d = new Date(ts)
    const diff = Date.now() - d.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'Just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
}

async function load() {
    loading.value = true
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/scheduled-reports`, { method: 'GET' })
        if (error.value) {
            if (error.value.statusCode === 404 || error.value.status === 404) { unavailable.value = true; return }
            throw error.value
        }
        reports.value = data.value || []
    } catch (e: any) {
        if (e?.statusCode === 404 || e?.status === 404) unavailable.value = true
    } finally {
        loading.value = false
    }
}

async function loadMembers() {
    try {
        const { data } = await useMyFetch<any>(`/studios/${props.studioId}/members`, { method: 'GET' })
        members.value = (data.value || []).map((m: any) => ({ id: m.user_id, name: m.user_name, email: m.user_email }))
    } catch { /* fail-soft: members are optional */ }
}

function resetForm() {
    form.title = ''
    form.prompt_content = ''
    form.cron_schedule = '0 8 * * *'
    form.subscribers = []
    form.format = 'auto'
    form.is_active = true
    cadenceMode.value = 'daily'
    emailDraft.value = ''
}

function openCreate() {
    editing.value = null
    resetForm()
    modalOpen.value = true
}

function openEdit(r: any) {
    editing.value = r
    form.title = r.title === 'Scheduled report' ? '' : (r.title || '')
    form.prompt_content = r.prompt_content || ''
    form.cron_schedule = r.cron_schedule || '0 8 * * *'
    form.subscribers = [...(r.subscribers || [])]
    form.format = r.format || 'auto'
    form.is_active = r.is_active
    const preset = cadencePresets.find((p) => p.value === r.cron_schedule)
    cadenceMode.value = (preset?.key as any) || 'custom'
    emailDraft.value = ''
    modalOpen.value = true
}

function addEmail() {
    const v = emailDraft.value.trim().toLowerCase()
    if (!v) return
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) { toast.add({ title: 'Enter a valid email', color: 'red' }); return }
    if (form.subscribers.some((s: any) => s.address === v)) { emailDraft.value = ''; return }
    form.subscribers.push({ type: 'email', address: v })
    emailDraft.value = ''
}

function addMember(m: any) {
    if (form.subscribers.some((s: any) => s.id === m.id || (m.email && s.address === m.email))) return
    form.subscribers.push({ type: 'user', id: m.id })
}

async function save() {
    if (!canSave.value) return
    saving.value = true
    try {
        const body = {
            prompt_content: form.prompt_content,
            cron_schedule: form.cron_schedule,
            subscribers: form.subscribers,
            format: form.format,
            title: form.title || null,
            is_active: form.is_active,
        }
        if (editing.value) {
            const { error } = await useMyFetch(`/studios/${props.studioId}/scheduled-reports/${editing.value.id}`, { method: 'PUT', body })
            if (error.value) throw error.value
            toast.add({ title: 'Report updated', color: 'green', icon: 'i-heroicons-check-circle' })
        } else {
            const { error } = await useMyFetch(`/studios/${props.studioId}/scheduled-reports`, { method: 'POST', body })
            if (error.value) throw error.value
            toast.add({ title: 'Report scheduled', color: 'green', icon: 'i-heroicons-check-circle' })
        }
        modalOpen.value = false
        await load()
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || 'Could not save report', color: 'red' })
    } finally {
        saving.value = false
    }
}

async function toggleActive(r: any) {
    busyId.value = r.id
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/scheduled-reports/${r.id}`, { method: 'PUT', body: { is_active: !r.is_active } })
        if (error.value) throw error.value
        r.is_active = !r.is_active
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || 'Could not update', color: 'red' })
    } finally {
        busyId.value = null
    }
}

async function remove(r: any) {
    if (!confirm('Delete this scheduled report?')) return
    busyId.value = r.id
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/scheduled-reports/${r.id}`, { method: 'DELETE' })
        if (error.value) throw error.value
        reports.value = reports.value.filter((x) => x.id !== r.id)
        toast.add({ title: 'Report deleted', color: 'green', icon: 'i-heroicons-check-circle' })
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || 'Could not delete', color: 'red' })
    } finally {
        busyId.value = null
    }
}

async function runNow(r: any) {
    busyId.value = r.id
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/scheduled-reports/${r.id}/run-now`, { method: 'POST' })
        if (error.value) throw error.value
        toast.add({ title: 'Test run sent', description: 'The report ran and was emailed to subscribers.', color: 'green', icon: 'i-heroicons-paper-airplane' })
        setTimeout(load, 1500)
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || 'Could not run report', color: 'red' })
    } finally {
        busyId.value = null
    }
}

onMounted(() => {
    load()
    loadMembers()
})
</script>
