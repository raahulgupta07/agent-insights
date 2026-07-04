<template>

    <header class="sticky top-0 bg-white z-10 flex flex-col border-gray-200">
        <!-- Top row: back, title, share, dashboard toggle -->
        <div class="flex flex-row pt-1 h-[40px] pb-1 pe-2 items-center">
            <GoBackChevron />
            <UTooltip v-if="report" :text="report.is_starred ? t('reports.tooltips.unstar') : t('reports.tooltips.star')">
                <button @click="toggleStar" class="p-1.5 rounded hover:bg-gray-100 focus:outline-none">
                    <UIcon
                        :name="report.is_starred ? 'heroicons-star-solid' : 'heroicons-star'"
                        class="w-5 h-5 transition-colors"
                        :class="report.is_starred ? 'text-yellow-400 hover:text-yellow-500' : 'text-gray-400 hover:text-gray-500'"
                    />
                </button>
            </UTooltip>
            <h1 class="text-sm md:text-start text-center w-[500px]">
                <span class="font-semibold text-sm">
                    <input
                        type="text"
                        class="inline hover:bg-gray-100 p-1 pt-1 outline-none active:bg-gray-100 hover:cursor-pointer text-start w-full transition-all duration-300 ease-in-out transform motion-safe:hover:scale-[1.01]"
                        :class="{ 'cai-title-flash': titleFlash }"
                        v-if="report"
                        v-model="localTitle"
                        :disabled="isSaving"
                        @keyup.enter="saveReportTitle"
                        @blur="saveReportTitle"
                        ref="reportTitleInput"
                    />
                    <span v-else></span>
                </span>
            </h1>
            <div class="ms-auto flex items-center gap-2">
                <UTooltip :text="runSound.enabled.value ? 'Run sounds on (click to mute)' : 'Play a sound when a run starts and finishes'">
                    <button
                        @click="runSound.toggle()"
                        class="hidden md:flex p-1.5 rounded items-center transition-colors"
                        :class="runSound.enabled.value ? 'text-[#C2541E] hover:bg-[#F6EFEA]' : 'text-gray-400 hover:text-gray-700 hover:bg-gray-100'"
                        aria-label="Toggle run sounds"
                    >
                        <Icon :name="runSound.enabled.value ? 'heroicons:speaker-wave' : 'heroicons:speaker-x-mark'" class="w-5 h-5" />
                    </button>
                </UTooltip>
                <!-- Save as workflow (HYBRID_WORKFLOWS_V2): turn this finished analysis into a reusable workflow -->
                <div v-if="workflowsEnabled && report" class="relative">
                    <UTooltip text="Save this analysis as a reusable workflow">
                        <button
                            @click="toggleSaveWorkflow"
                            class="hidden md:flex p-1.5 rounded items-center transition-colors text-gray-500 hover:text-[#C2541E] hover:bg-[#F6EFEA]"
                            aria-label="Save as workflow"
                        >
                            <Icon name="heroicons:bookmark-square" class="w-5 h-5" />
                        </button>
                    </UTooltip>
                    <div
                        v-if="showSaveWorkflow"
                        class="absolute right-0 top-full mt-1 z-30 w-72 p-3 rounded-xl border border-[#E9E0D3] bg-[#FBFAF6] shadow-lg"
                    >
                        <p class="text-xs font-medium text-[#211B14] mb-1.5">Save as workflow</p>
                        <input
                            v-model="workflowName"
                            type="text"
                            placeholder="Workflow name"
                            class="w-full text-sm px-2 py-1.5 rounded-lg border border-[#E9E0D3] bg-white outline-none focus:border-[#C2541E]"
                            @keyup.enter="saveAsWorkflow"
                        />
                        <div class="flex items-center gap-1.5 mt-2">
                            <button
                                v-for="opt in [{v:'private',l:'Private'},{v:'org',l:'Organization'}]"
                                :key="opt.v"
                                @click="workflowScope = opt.v"
                                class="flex-1 text-[11px] py-1 rounded-lg border transition-colors"
                                :class="workflowScope === opt.v
                                    ? 'border-[#C2541E] bg-[#F6EFEA] text-[#C2541E] font-medium'
                                    : 'border-[#E9E0D3] text-gray-500 hover:bg-gray-50'"
                            >{{ opt.l }}</button>
                        </div>
                        <div class="flex items-center gap-2 mt-2.5">
                            <button
                                @click="showSaveWorkflow = false"
                                class="text-[11px] px-2 py-1 rounded-lg text-gray-500 hover:bg-gray-100"
                            >Cancel</button>
                            <button
                                @click="saveAsWorkflow"
                                :disabled="isSavingWorkflow || !workflowName.trim()"
                                class="ms-auto text-[11px] px-3 py-1 rounded-lg bg-[#C2541E] text-white font-medium disabled:opacity-50 hover:bg-[#A8330F]"
                            >{{ isSavingWorkflow ? 'Saving…' : 'Save' }}</button>
                        </div>
                    </div>
                </div>
                <ShareModal v-if="report" :report="report" share-type="conversation" title="Share Conversation" />
                <UTooltip :text="isSplitScreen ? t('reportView.closeSidebar') : t('reportView.openSidebar')">
                    <button
                        @click="$emit('toggleSplitScreen')"
                        class="hidden md:flex p-1.5 rounded text-gray-500 hover:text-gray-900 hover:bg-gray-100 items-center"
                        :title="t('reportView.sidebar')"
                        :aria-label="t('reportView.sidebar')"
                    >
                        <Icon name="heroicons:view-columns" class="w-5 h-5" />
                    </button>
                </UTooltip>
            </div>
        </div>
        <!-- Mobile tabs -->
        <div v-if="isMobile" class="flex items-center gap-1 px-2 pb-1.5 border-b border-gray-100">
            <button
                v-for="tab in mobileTabs"
                :key="tab.value"
                @click="$emit('update:mobileView', tab.value)"
                class="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors"
                :class="mobileView === tab.value
                    ? 'text-gray-900 bg-gray-100'
                    : 'text-gray-400 hover:text-gray-600'"
            >
                <Icon :name="tab.icon" class="w-3 h-3" />
                {{ tab.label }}
            </button>
            <button
                v-if="mobileView !== 'chat'"
                @click="$emit('update:mobileView', 'chat')"
                class="ms-auto p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
            >
                <Icon name="heroicons:x-mark" class="w-4 h-4" />
            </button>
        </div>
    </header>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import GoBackChevron from '@/components/excel/GoBackChevron.vue'
import ShareModal from '@/components/ShareModal.vue'
import { useRunSound } from '~/composables/useRunSound'

const runSound = useRunSound()

const props = defineProps<{
    report: any | null,
    isSplitScreen: boolean,
    isStreaming: boolean,
    isMobile?: boolean,
    mobileView?: string,
}>()

defineEmits(['toggleSplitScreen', 'stop', 'update:mobileView'])

const mobileTabs = computed(() => [
    { value: 'chat', label: t('reportView.tabChat'), icon: 'heroicons:chat-bubble-left-right' },
    { value: 'summary', label: t('reportView.tabSummary'), icon: 'heroicons:queue-list' },
    { value: 'dashboard', label: t('reportView.tabDashboard'), icon: 'heroicons:chart-bar-square' },
    { value: 'agent', label: t('reportView.tabAgent'), icon: 'heroicons:cog-6-tooth' },
])

const { t } = useI18n()
const route = useRoute()
const report_id = route.params.id
const reportTitleInput = ref<HTMLInputElement | null>(null)
const localTitle = ref('')
const isSaving = ref(false)
// Brief fade when the title is updated externally (backend report:updated).
const titleFlash = ref(false)
const toast = useToast()

// HYBRID_WORKFLOWS_V2: "Save as workflow" — turn this finished analysis into a reusable workflow.
const workflowsEnabled = ref(false)
const showSaveWorkflow = ref(false)
const workflowName = ref('')
const workflowScope = ref('private')
const isSavingWorkflow = ref(false)

onMounted(async () => {
    try {
        const { data } = await useMyFetch<any[]>('/api/organization/hybrid-flags')
        const rows = (data.value || []) as any[]
        workflowsEnabled.value = !!rows.find(r => r?.env_name === 'HYBRID_WORKFLOWS_V2')?.effective
    } catch { workflowsEnabled.value = false }
})

function toggleSaveWorkflow() {
    showSaveWorkflow.value = !showSaveWorkflow.value
    if (showSaveWorkflow.value) {
        workflowName.value = (props.report?.title || '').trim() || 'Untitled workflow'
    }
}

async function saveAsWorkflow() {
    const name = workflowName.value.trim()
    if (!name || isSavingWorkflow.value) return
    isSavingWorkflow.value = true
    try {
        const res: any = await useMyFetch(`/workflows-v2/from-report/${report_id}`, {
            method: 'POST',
            body: { name, scope: workflowScope.value },
        })
        if (res?.error?.value) throw res.error.value
        showSaveWorkflow.value = false
        toast.add({
            title: 'Saved as workflow',
            description: "Use it from the composer's ‘Use a workflow’.",
            color: 'green',
        })
    } catch (error: any) {
        const status = error?.status || error?.statusCode || error?.response?.status
        toast.add({
            title: status === 400 ? 'No analysis steps to save yet' : 'Could not save workflow',
            color: 'red',
        })
    }
    isSavingWorkflow.value = false
}

// Watch for changes in report prop to update local title
watch(() => props.report?.title, (newTitle, oldTitle) => {
    if (newTitle) {
        localTitle.value = newTitle
        // Subtle fade-in when the title changes after initial load (e.g. the
        // backend just generated a real title in place).
        if (oldTitle !== undefined && oldTitle !== newTitle) {
            titleFlash.value = false
            requestAnimationFrame(() => { titleFlash.value = true })
            setTimeout(() => { titleFlash.value = false }, 600)
        }
    }
}, { immediate: true })

async function saveReportTitle() {
    // disable submit button
    isSaving.value = true

    if (!props.report || !localTitle.value.trim()) {
        isSaving.value = false
        toast.add({
            title: 'Title is required',
            color: 'red',
        })
        return
    }
    
    const requestBody = {
        title: localTitle.value.trim()
    }

    try {
        await useMyFetch(`/api/reports/${report_id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        })
        
        // Update the report object
        if (props.report) {
            props.report.title = localTitle.value.trim()


        }
        
        // Blur the input
        if (reportTitleInput.value) {
            reportTitleInput.value.blur()
            toast.add({
                title: 'Report title updated',
                color: 'green',
            })
        }
        


    } catch (error) {
        console.error('Failed to save report title:', error)
        // Revert to original title on error
        if (props.report?.title) {
            localTitle.value = props.report.title
        }
        toast.add({
            title: 'Failed to update report title',
            color: 'red',
        })
    }
    isSaving.value = false
}

async function toggleStar() {
    if (!props.report) return
    const next = !props.report.is_starred
    // Optimistic update
    props.report.is_starred = next
    try {
        const response: any = await useMyFetch(`/reports/${props.report.id}/star`, {
            method: next ? 'POST' : 'DELETE',
        })
        if (response?.error?.value) {
            throw response.error.value
        }
    } catch (error: any) {
        // Revert on failure
        props.report.is_starred = !next
        console.error('Error toggling star', error)
        toast.add({
            title: t('reports.toasts.starFailed'),
            description: String(error?.data?.detail || error?.message || ''),
            color: 'red',
        })
    }
}
</script>

<style scoped>
/* Subtle fade-in when the report title is set/updated in place. */
@keyframes cai-title-fade {
    from { opacity: 0.35; }
    to   { opacity: 1; }
}
.cai-title-flash {
    animation: cai-title-fade 0.55s ease-in-out;
}
@media (prefers-reduced-motion: reduce) {
    .cai-title-flash { animation: none; }
}
</style>


