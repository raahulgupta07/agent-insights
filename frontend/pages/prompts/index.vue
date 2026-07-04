<template>
  <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
    <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto text-[#1f2328]">

      <!-- header -->
      <div class="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
            {{ $t('prompts.title') }}
          </h2>
          <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[480px]">{{ $t('prompts.subtitle') }}</p>
        </div>
        <button
          class="shrink-0 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-white text-[13px] font-medium"
          style="background:#C2683F"
          @click="openCreate"
        >
          <span class="text-base leading-none">+</span> {{ $t('prompts.new') }}
        </button>
      </div>

      <!-- loading -->
      <div v-if="isLoading" class="py-16 text-center text-[#9a958c] text-xs">{{ $t('prompts.loading') }}</div>

      <!-- empty -->
      <div v-else-if="!prompts.length" class="py-16 text-center">
        <p class="text-sm text-[#6b6b6b]">{{ $t('prompts.empty') }}</p>
        <button class="mt-3 text-[13px] font-medium" style="color:#C2683F" @click="openCreate">{{ $t('prompts.new') }}</button>
      </div>

      <!-- list -->
      <div v-else class="grid gap-3 sm:grid-cols-2">
        <div
          v-for="p in prompts"
          :key="p.id"
          class="border border-[#EAE8E4] rounded-xl p-4 bg-white flex flex-col gap-2"
        >
          <div class="flex items-start justify-between gap-2">
            <h3 class="text-[14px] font-semibold text-[#1f2328] truncate">{{ p.title || $t('prompts.untitled') }}</h3>
            <div class="flex items-center gap-1 shrink-0">
              <button class="text-[11px] px-2 py-1 rounded border border-[#EAE8E4] text-[#6b6b6b] hover:bg-[#F6F1EA]" @click="openEdit(p)">{{ $t('prompts.edit') }}</button>
              <button class="text-[11px] px-2 py-1 rounded border border-[#EAE8E4] text-[#b4462d] hover:bg-[#FBEFE4]" @click="removePrompt(p)">{{ $t('prompts.delete') }}</button>
            </div>
          </div>
          <p class="text-[12px] text-[#6b6b6b] line-clamp-3 whitespace-pre-wrap">{{ p.text }}</p>
          <div class="flex flex-wrap items-center gap-1.5 mt-auto pt-1">
            <span class="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-[#F4EEE5] text-[#8a6a4f] border border-[#EAE8E4]">{{ p.scope || 'agent' }}</span>
            <span class="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-[#F4EEE5] text-[#8a6a4f] border border-[#EAE8E4]">{{ p.mode || 'chat' }}</span>
            <span v-if="p.is_starter" class="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-[#FBEFE4] text-[#C2683F] border border-[#EAD9CB]">{{ $t('prompts.starter') }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- create / edit modal -->
    <div v-if="showModal" class="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4" @click.self="closeModal">
      <div class="w-full max-w-lg bg-[#FBFAF6] border border-[#EAE8E4] rounded-2xl p-6 shadow-xl">
        <h3 class="text-base font-semibold text-[#1f2328] mb-4" style="font-family: 'Spectral', ui-serif, Georgia, serif">
          {{ editing ? $t('prompts.editTitle') : $t('prompts.newTitle') }}
        </h3>

        <label class="block text-[12px] font-medium text-[#6b6b6b] mb-1">{{ $t('prompts.fieldTitle') }}</label>
        <input v-model="form.title" type="text" class="w-full mb-3 px-3 py-2 text-[13px] rounded-lg border border-[#EAE8E4] bg-white focus:outline-none focus:border-[#C2683F]" :placeholder="$t('prompts.fieldTitlePh')" />

        <label class="block text-[12px] font-medium text-[#6b6b6b] mb-1">{{ $t('prompts.fieldText') }}</label>
        <textarea v-model="form.text" rows="5" class="w-full mb-3 px-3 py-2 text-[13px] rounded-lg border border-[#EAE8E4] bg-white focus:outline-none focus:border-[#C2683F] resize-y" :placeholder="$t('prompts.fieldTextPh')"></textarea>

        <div class="grid grid-cols-2 gap-3 mb-3">
          <div>
            <label class="block text-[12px] font-medium text-[#6b6b6b] mb-1">{{ $t('prompts.fieldMode') }}</label>
            <select v-model="form.mode" class="w-full px-3 py-2 text-[13px] rounded-lg border border-[#EAE8E4] bg-white focus:outline-none focus:border-[#C2683F]">
              <option value="chat">chat</option>
              <option value="deep">deep</option>
              <option value="training">training</option>
            </select>
          </div>
          <div>
            <label class="block text-[12px] font-medium text-[#6b6b6b] mb-1">{{ $t('prompts.fieldScope') }}</label>
            <select v-model="form.scope" class="w-full px-3 py-2 text-[13px] rounded-lg border border-[#EAE8E4] bg-white focus:outline-none focus:border-[#C2683F]">
              <option value="agent">agent</option>
              <option value="global">global</option>
              <option value="private">private</option>
            </select>
          </div>
        </div>

        <label class="flex items-center gap-2 text-[13px] text-[#6b6b6b] mb-5 cursor-pointer">
          <input v-model="form.is_starter" type="checkbox" class="accent-[#C2683F]" />
          {{ $t('prompts.fieldStarter') }}
        </label>

        <div class="flex justify-end gap-2">
          <button class="px-3.5 py-2 rounded-lg text-[13px] border border-[#EAE8E4] text-[#6b6b6b] hover:bg-[#F6F1EA]" @click="closeModal">{{ $t('prompts.cancel') }}</button>
          <button
            class="px-3.5 py-2 rounded-lg text-white text-[13px] font-medium disabled:opacity-50"
            style="background:#C2683F"
            :disabled="!form.text || saving"
            @click="save"
          >
            {{ saving ? $t('prompts.saving') : $t('prompts.save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ auth: true })

const { t } = useI18n()
const toast = useToast()

const prompts = ref<any[]>([])
const isLoading = ref(true)
const showModal = ref(false)
const editing = ref<any>(null)
const saving = ref(false)

const form = ref<{ title: string; text: string; mode: string; scope: string; is_starter: boolean }>({
  title: '', text: '', mode: 'chat', scope: 'agent', is_starter: false,
})

const loadPrompts = async () => {
  isLoading.value = true
  try {
    const { data } = await useMyFetch('/prompts', { method: 'GET' })
    prompts.value = (data.value as any[]) || []
  } catch (e) {
    prompts.value = []
  } finally {
    isLoading.value = false
  }
}

const openCreate = () => {
  editing.value = null
  form.value = { title: '', text: '', mode: 'chat', scope: 'agent', is_starter: false }
  showModal.value = true
}

const openEdit = (p: any) => {
  editing.value = p
  form.value = {
    title: p.title || '',
    text: p.text || '',
    mode: p.mode || 'chat',
    scope: p.scope || 'agent',
    is_starter: !!p.is_starter,
  }
  showModal.value = true
}

const closeModal = () => { showModal.value = false }

const save = async () => {
  saving.value = true
  try {
    const body = {
      title: form.value.title || null,
      text: form.value.text,
      mode: form.value.mode,
      scope: form.value.scope,
      is_starter: form.value.is_starter,
    }
    if (editing.value) {
      await useMyFetch(`/prompts/${editing.value.id}`, { method: 'PUT', body })
    } else {
      await useMyFetch('/prompts', { method: 'POST', body })
    }
    showModal.value = false
    await loadPrompts()
  } catch (e) {
    toast?.error?.(t('prompts.saveError'))
  } finally {
    saving.value = false
  }
}

const removePrompt = async (p: any) => {
  if (!confirm(t('prompts.deleteConfirm'))) return
  try {
    await useMyFetch(`/prompts/${p.id}`, { method: 'DELETE' })
    await loadPrompts()
  } catch (e) {
    toast?.error?.(t('prompts.deleteError'))
  }
}

onMounted(loadPrompts)
</script>
