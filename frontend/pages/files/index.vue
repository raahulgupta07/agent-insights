<template>
    <div class="flex justify-center ps-2 md:ps-4 text-sm bg-[#F6F1EA] min-h-full">
        <div class="w-full max-w-7xl px-4 ps-0 py-2 text-[#1f2328]">
            <div>
                <h1
                    class="text-[32px] font-medium text-[#211B14] tracking-tight flex items-center"
                    style="font-family: 'Spectral', ui-serif, Georgia, serif"
                >
                    <GoBackChevron v-if="isExcel" />
                    {{ $t('files.title') }}
                </h1>
                <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">{{ $t('files.subtitle') }}</p>
            </div>

            <!-- Empty state -->
            <div v-if="files.length === 0" class="mt-12 flex flex-col items-center text-center">
                <div class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] text-[#C2541E]">
                    <Icon name="heroicons:document-text" class="w-6 h-6" />
                </div>
                <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                    {{ $t('files.empty') }}
                </h3>
                <p class="mt-1 text-sm text-[#9a958c]">{{ $t('files.emptyDescription') }}</p>
            </div>

            <div v-else class="bg-white border border-[#E9E0D3] rounded-2xl overflow-hidden mt-8">
                <table class="min-w-full divide-y divide-[#E9E0D3]">
                    <thead class="bg-[#F4EEE5]">
                        <tr>
                            <th class="px-6 py-3 text-start text-xs font-medium text-[#6b6b6b] uppercase tracking-wider">{{ $t('files.file') }}</th>
                            <th class="px-6 py-3 text-start text-xs font-medium text-[#6b6b6b] uppercase tracking-wider">{{ $t('files.metadata') }}</th>
                            <th class="px-6 py-3 text-start text-xs font-medium text-[#6b6b6b] uppercase tracking-wider">{{ $t('files.createdAt') }}</th>
                            <th class="px-6 py-3 text-start text-xs font-medium text-[#6b6b6b] uppercase tracking-wider">{{ $t('files.actions') }}</th>
                        </tr>
                    </thead>

                    <tbody class="bg-white divide-y divide-[#E9E0D3]">
                        <tr v-for="file in files" :key="file.id" class="hover:bg-[#faf8f3] transition-colors">
                            <td class="px-6 py-4 whitespace-nowrap text-[#1f2328]">
                                <div class="flex items-center">
                                    <UIcon name="heroicons-document-text" class="w-5 h-5 text-[#9a958c] me-2" />
                                    {{ file.filename }}.
                                </div>
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-[#1f2328]">
                                <div v-if="file.schemas.length > 0">
                                    <div v-for="schema in file.schemas" :key="schema.id">
                                        <UTooltip :text="Object.keys(schema.schema.fields).join(', ')">
                                            <div class="flex items-center">
                                                <Icon name="heroicons-view-columns" class="w-5 h-5 text-[#9a958c] me-2" />
                                                {{ $t(Object.keys(schema.schema.fields).length === 1 ? 'files.metadataFieldsOne' : 'files.metadataFieldsMany', { count: Object.keys(schema.schema.fields).length }) }}
                                            </div>
                                        </UTooltip>
                                    </div>
                                </div>
                                <div v-else-if="file.tags.length > 0">
                                     <UTooltip :text="file.tags.map(tag => tag.key).join(', ')">
                                         <div class="flex items-center">
                                            <Icon name="heroicons-view-columns" class="w-5 h-5 text-[#9a958c] me-2" />
                                            {{ $t(file.tags.length === 1 ? 'files.metadataTagsOne' : 'files.metadataTagsMany', { count: file.tags.length }) }}
                                        </div>
                                     </UTooltip>
                                </div>
                                <div v-else class="text-[#9a958c]">
                                    {{ $t('files.noMetadata') }}
                                </div>
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-[#6b6b6b]">{{ file.created_at }}</td>
                            <td class="px-6 py-4 whitespace-nowrap">
                                <button @click="downloadFile(file)" class="text-[#9a958c] hover:text-[#C2541E] transition-colors">
                                    <Icon name="heroicons-arrow-down-tray" class="w-5 h-5 me-2" />
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">

const files = ref([]);

definePageMeta({ auth: true })

const getFiles = async () => {
  const response = await useMyFetch('/api/files', {
    method: 'GET',
    headers: {
        'Content-Type': 'application/json',
    },
  })
  files.value = response.data.value
}

const downloadFile = async (file: any) => {
  const response = await useMyFetch(`/api/files/${file.path}`, {
    method: 'GET',
  })
}

onMounted(() => {
  getFiles();
})
</script>
