<template>
  <UModal v-model="isOpen" :ui="{ width: 'sm:max-w-md' }">
    <div class="cag-profile-modal p-6">
      <div class="flex items-start justify-between mb-5">
        <div>
          <h3 class="text-[17px] font-semibold text-[#211B14]">{{ $t('profile.title') }}</h3>
          <p class="text-[12px] text-gray-500 mt-0.5">{{ $t('profile.subtitle') }}</p>
        </div>
        <button
          class="text-gray-400 hover:text-gray-700 transition-colors"
          :aria-label="$t('common.close')"
          @click="isOpen = false"
        >
          <UIcon name="heroicons-x-mark" class="w-5 h-5" />
        </button>
      </div>

      <!-- Avatar preview + actions -->
      <div class="flex items-center gap-4">
        <div class="relative shrink-0">
          <img
            v-if="avatarUrl"
            :src="avatarUrl"
            alt=""
            class="w-20 h-20 rounded-full object-cover bg-[#F4EEE5] border border-[#EAE8E4]"
          />
          <div
            v-else
            class="flex items-center justify-center w-20 h-20 rounded-full text-white text-2xl font-semibold cag-avatar"
          >
            {{ userInitial }}
          </div>
          <div
            v-if="avatarBusy"
            class="absolute inset-0 rounded-full bg-white/60 flex items-center justify-center"
          >
            <Spinner class="w-5 h-5 text-[#C2683F]" />
          </div>
        </div>

        <div class="flex-1 min-w-0">
          <div class="text-[14px] font-medium text-[#211B14] truncate">{{ currentUserName }}</div>
          <div class="text-[12px] text-gray-500 truncate">{{ currentUserEmail }}</div>

          <div class="flex items-center gap-2 mt-3">
            <button
              type="button"
              :disabled="avatarBusy"
              class="cag-btn-primary"
              @click="selectAvatar"
            >
              <UIcon name="heroicons-arrow-up-tray" class="w-4 h-4" />
              {{ avatarUrl ? $t('profile.changePhoto') : $t('profile.uploadPhoto') }}
            </button>
            <button
              v-if="avatarUrl"
              type="button"
              :disabled="avatarBusy"
              class="cag-btn-ghost"
              @click="removeAvatar"
            >
              {{ $t('profile.removePhoto') }}
            </button>
          </div>
          <input ref="avatarInput" type="file" accept="image/*" class="hidden" @change="onAvatarSelected" />
        </div>
      </div>

      <p class="text-[11px] text-gray-400 mt-4">{{ $t('profile.avatarHint') }}</p>
    </div>
  </UModal>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const isOpen = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const { t } = useI18n()
const toast = useToast()
const { data: currentUser, getSession } = useAuth()

const currentUserName = computed<string>(() => {
  const u = currentUser.value as any
  return u?.name || u?.email || 'User'
})
const currentUserEmail = computed<string>(() => (currentUser.value as any)?.email || '')
const userInitial = computed<string>(() => currentUserName.value.charAt(0).toUpperCase())
const avatarUrl = computed<string | null>(() => (currentUser.value as any)?.image_url || null)

const avatarInput = ref<HTMLInputElement | null>(null)
const avatarBusy = ref(false)

function selectAvatar() {
  avatarInput.value?.click()
}

async function onAvatarSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > 5 * 1024 * 1024) {
    toast.add({ title: t('profile.avatarTooLarge'), color: 'red' })
    input.value = ''
    return
  }
  avatarBusy.value = true
  try {
    const formData = new FormData()
    formData.append('avatar', file)
    const res = await useMyFetch('/users/me/avatar', { method: 'POST', body: formData })
    if (res.status.value !== 'success') {
      throw new Error((res.error?.value as any)?.data?.detail || t('profile.avatarFailed'))
    }
    await getSession({ force: true })
    toast.add({ title: t('profile.avatarUpdated'), color: 'green' })
  } catch (err: any) {
    toast.add({ title: err?.message || t('profile.avatarFailed'), color: 'red' })
  } finally {
    avatarBusy.value = false
    input.value = ''
  }
}

async function removeAvatar() {
  avatarBusy.value = true
  try {
    const res = await useMyFetch('/users/me/avatar', { method: 'DELETE' })
    if (res.status.value !== 'success') {
      throw new Error((res.error?.value as any)?.data?.detail || t('profile.avatarFailed'))
    }
    await getSession({ force: true })
    toast.add({ title: t('profile.avatarRemoved'), color: 'green' })
  } catch (err: any) {
    toast.add({ title: err?.message || t('profile.avatarFailed'), color: 'red' })
  } finally {
    avatarBusy.value = false
  }
}
</script>

<style scoped>
.cag-avatar {
  background: linear-gradient(150deg, #C2683F, #A8330F);
}
.cag-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #fff;
  background: #C2683F;
  transition: background .15s;
}
.cag-btn-primary:hover:not(:disabled) { background: #A8330F; }
.cag-btn-primary:disabled { opacity: .5; cursor: default; }
.cag-btn-ghost {
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  color: #6b7280;
  border: 1px solid #EAE8E4;
  transition: color .15s, border-color .15s;
}
.cag-btn-ghost:hover:not(:disabled) { color: #A8330F; border-color: #E4C9BC; }
.cag-btn-ghost:disabled { opacity: .5; cursor: default; }
</style>
