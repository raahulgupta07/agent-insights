<template>
    <div class="flex justify-center px-4 md:px-6 text-sm bg-[#F6F1EA] min-h-full">
        <div class="w-full max-w-7xl py-2 text-[#1f2328]">
            <!-- Header -->
            <div class="flex items-start justify-between gap-4 mb-6">
                <div>
                    <h1
                        class="text-[32px] font-medium text-[#211B14] tracking-tight"
                        style="font-family: 'Spectral', ui-serif, Georgia, serif"
                    >Connectors</h1>
                    <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">
                        Configure data connections for your organization. Users pin these inside their Studios — they never see credentials.
                    </p>
                </div>
                <button
                    v-if="canCreateDataSource"
                    @click="selectedDataSourceType = undefined; showAddConnectionModal = true"
                    class="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors whitespace-nowrap shrink-0"
                >
                    <UIcon name="heroicons-plus" class="w-4 h-4" />
                    Add Connection
                </button>
            </div>

            <!-- Admin-only gate -->
            <div v-if="!canCreateDataSource" class="flex flex-col items-center justify-center py-20 text-center">
                <span class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] text-[#C2541E]">
                    <UIcon name="heroicons-lock-closed" class="w-6 h-6" />
                </span>
                <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Admins only</h3>
                <p class="mt-1 text-sm text-[#9a958c] max-w-md leading-relaxed">
                    Connectors are configured by your organization admins. You can use the configured
                    sources by pinning them inside a Studio.
                </p>
            </div>

            <template v-else>
                <!-- Loading -->
                <div v-if="loading" class="flex items-center justify-center py-20">
                    <Spinner class="w-6 h-6 text-[#C2541E] animate-spin" />
                </div>

                <template v-else>
                    <!-- Upload File / Spreadsheet — instant Data Agent (always available) -->
                    <button
                        @click="showUploadModal = true"
                        class="group mb-4 flex w-full items-center gap-4 rounded-2xl border border-[#E8C9B5] bg-[#F6EFEA] p-4 text-start transition hover:-translate-y-0.5 hover:shadow-md"
                    >
                        <span class="inline-flex w-11 h-11 items-center justify-center rounded-xl bg-white border border-[#E9E0D3] text-[#C2541E] shrink-0">
                            <UIcon name="i-heroicons-cloud-arrow-up" class="w-6 h-6" />
                        </span>
                        <div class="min-w-0">
                            <div class="flex items-center gap-2">
                                <span class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                                    Upload File / Spreadsheet
                                </span>
                                <span class="inline-flex items-center rounded-full bg-[#C2541E] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-white">new</span>
                            </div>
                            <p class="mt-0.5 text-xs text-[#6b6b6b]">.xlsx · .xls · .csv → instant Data Agent</p>
                        </div>
                        <UIcon name="i-heroicons-arrow-right" class="ms-auto w-5 h-5 text-[#A8330F] opacity-0 transition group-hover:opacity-100 shrink-0" />
                    </button>

                    <!-- Connection cards (when connections exist) -->
                    <div v-if="connections.length > 0" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                        <button
                            v-for="conn in connections"
                            :key="conn.id"
                            @click="openConnectionDetail(conn)"
                            class="flex flex-col gap-3 rounded-2xl border border-[#E9E0D3] bg-white p-4 text-start cursor-pointer transition hover:-translate-y-0.5 hover:shadow-md"
                        >
                            <div class="flex items-center justify-between gap-2 rounded-xl border border-[#E9E0D3] bg-[#F4EEE5] px-3 py-2">
                                <span class="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-white border border-[#E9E0D3]">
                                    <DataSourceIcon class="h-4" :type="conn.type" />
                                </span>
                                <span class="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium"
                                    :class="isConnectionHealthy(conn) ? 'border-[#d7ebde] bg-[#eef6f0] text-[#3f9e6a]' : 'border-red-200 bg-red-50 text-red-600'">
                                    <span :class="['w-1.5 h-1.5 rounded-full', isConnectionHealthy(conn) ? 'bg-[#3f9e6a]' : 'bg-red-500']"></span>
                                    {{ isConnectionHealthy(conn) ? 'Connected' : 'Error' }}
                                </span>
                            </div>
                            <div class="text-[15px] font-semibold text-[#1f2328] truncate" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                                {{ conn.name }}
                            </div>
                            <p class="text-xs text-[#6b6b6b] leading-relaxed capitalize">{{ conn.type }}</p>
                            <div class="border-t border-[#E9E0D3] pt-2 mt-1 text-[11px] text-[#9a958c] flex items-center gap-1.5">
                                <UIcon name="heroicons-film" class="w-3 h-3" />
                                Pin in a Studio to use
                            </div>
                        </button>
                    </div>

                    <!-- Empty state - pick a type -->
                    <div v-else>
                        <DataSourceGrid
                            :show-demos="true"
                            :navigate-on-demo="false"
                            @select="handleDataSourceSelect"
                            @demo-installed="handleDemoInstalled"
                        />
                    </div>
                </template>
            </template>

            <!-- Modals -->
            <ConnectionDetailModal
                v-model="showConnectionModal"
                :connection="selectedConnection"
                @updated="refreshConnections"
            />
            <AddConnectionModal
                v-model="showAddConnectionModal"
                :initial-selected-type="selectedDataSourceType"
                @created="handleConnectionCreated"
            />
            <UploadSpreadsheetModal
                :open="showUploadModal"
                @close="showUploadModal = false"
                @created="handleSpreadsheetCreated"
            />
        </div>
    </div>
</template>

<script lang="ts" setup>
import ConnectionDetailModal from '~/components/ConnectionDetailModal.vue'
import AddConnectionModal from '~/components/AddConnectionModal.vue'
import UploadSpreadsheetModal from '~/components/data/UploadSpreadsheetModal.vue'
import DataSourceGrid from '~/components/datasources/DataSourceGrid.vue'
import DataSourceIcon from '~/components/DataSourceIcon.vue'
import Spinner from '~/components/Spinner.vue'
import { useCan } from '~/composables/usePermissions'

const canCreateDataSource = computed(() => useCan('create_data_source'))

const loading = ref(false)
const connections = ref<any[]>([])
const selectedConnection = ref<any>(null)
const showConnectionModal = ref(false)
const showAddConnectionModal = ref(false)
const showUploadModal = ref(false)
const selectedDataSourceType = ref<string | undefined>(undefined)

async function refreshConnections() {
    loading.value = true
    try {
        const res = await useMyFetch('/connections', { method: 'GET' })
        if (res.data.value) connections.value = res.data.value as any[]
    } catch (e) {
        console.error('Failed to load connectors:', e)
    } finally {
        loading.value = false
    }
}

function isConnectionHealthy(conn: any): boolean {
    if (conn.last_status === 'success' || conn.status === 'success') return true
    if (conn.last_status === 'error' || conn.status === 'error') return false
    const userStatus = conn.user_status?.connection
    if (userStatus === 'success') return true
    if (userStatus === 'error' || userStatus === 'offline') return false
    return true
}

function openConnectionDetail(conn: any) {
    selectedConnection.value = conn
    showConnectionModal.value = true
}
function handleDataSourceSelect(ds: any) {
    selectedDataSourceType.value = ds.type
    showAddConnectionModal.value = true
}
function handleConnectionCreated() {
    selectedDataSourceType.value = undefined
    refreshConnections()
}
function handleDemoInstalled() {
    refreshConnections()
}
function handleSpreadsheetCreated(_ds: any) {
    showUploadModal.value = false
    refreshConnections()
}

onMounted(() => {
    if (canCreateDataSource.value) refreshConnections()
})
</script>
