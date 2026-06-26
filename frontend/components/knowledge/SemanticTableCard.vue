<template>
  <div class="rounded-lg border border-gray-200 bg-white overflow-hidden">
    <!-- Collapsed header -->
    <button
      type="button"
      class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      @click="expanded = !expanded"
    >
      <Icon
        :name="expanded ? 'heroicons:chevron-down' : 'heroicons:chevron-right'"
        class="w-4 h-4 text-gray-400 shrink-0"
      />
      <Icon name="heroicons:table-cells" class="w-4 h-4 text-gray-400 shrink-0" />
      <span class="text-sm font-medium text-gray-900 truncate">{{ table.table_name }}</span>
      <span class="text-xs text-gray-400">{{ (table.columns || []).length }} cols</span>
      <span class="ml-auto shrink-0">
        <span
          v-if="table.described"
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-green-50 text-green-700"
        >
          <Icon name="heroicons:check-circle" class="w-3 h-3" /> Described
        </span>
        <span
          v-else
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-gray-100 text-gray-500"
        >
          Undescribed
        </span>
      </span>
    </button>

    <!-- Expanded body -->
    <div v-if="expanded" class="border-t border-gray-100 px-4 py-4 space-y-5">
      <!-- Approval -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2 text-xs">
          <span
            :class="[
              'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium',
              table.status === 'approved' ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'
            ]"
          >{{ table.status || 'draft' }}</span>
          <span
            v-if="table.status === 'approved'"
            class="inline-flex items-center gap-1 text-[11px] text-green-600"
            title="This table is injected into the agent's context."
          >
            <span class="text-green-500">&bull;</span> in agent context
          </span>
        </div>
        <UButton
          v-if="table.status === 'approved'"
          size="2xs"
          variant="ghost"
          color="gray"
          icon="i-heroicons-arrow-uturn-left"
          :loading="savingStatus"
          @click="setStatus('draft')"
        >Unapprove</UButton>
        <UButton
          v-else
          size="2xs"
          variant="soft"
          color="green"
          icon="i-heroicons-check"
          :loading="savingStatus"
          @click="setStatus('approved')"
        >Approve</UButton>
      </div>

      <!-- Description -->
      <div>
        <div class="flex items-center justify-between mb-1.5">
          <label class="text-xs font-semibold uppercase tracking-wide text-gray-500">Description</label>
          <button
            v-if="!editingDesc"
            type="button"
            class="inline-flex items-center gap-1 text-xs text-[#C2541E] hover:text-[#A8330F]"
            @click="startDesc"
          >
            <Icon name="heroicons:pencil-square" class="w-3.5 h-3.5" /> Edit
          </button>
        </div>
        <div v-if="editingDesc">
          <UTextarea
            v-model="descDraft"
            :rows="3"
            autoresize
            placeholder="What does this table represent?"
          />
          <div class="mt-2 flex items-center gap-2">
            <UButton size="2xs" :loading="savingDesc" @click="saveDesc">Save</UButton>
            <UButton size="2xs" variant="ghost" color="gray" @click="editingDesc = false">Cancel</UButton>
          </div>
        </div>
        <p
          v-else
          class="text-sm text-gray-700 whitespace-pre-line"
          :class="{ 'text-gray-400 italic': !table.description }"
        >
          {{ table.description || 'No description yet.' }}
        </p>
      </div>

      <!-- Use cases -->
      <div>
        <div class="flex items-center justify-between mb-1.5">
          <label class="text-xs font-semibold uppercase tracking-wide text-gray-500">Use cases</label>
          <button
            v-if="!editingUseCases"
            type="button"
            class="inline-flex items-center gap-1 text-xs text-[#C2541E] hover:text-[#A8330F]"
            @click="startUseCases"
          >
            <Icon name="heroicons:pencil-square" class="w-3.5 h-3.5" /> Edit
          </button>
        </div>
        <div v-if="editingUseCases">
          <UTextarea
            v-model="useCasesDraft"
            :rows="2"
            autoresize
            placeholder="One use case per line, or comma-separated"
          />
          <div class="mt-2 flex items-center gap-2">
            <UButton size="2xs" :loading="savingUseCases" @click="saveUseCases">Save</UButton>
            <UButton size="2xs" variant="ghost" color="gray" @click="editingUseCases = false">Cancel</UButton>
          </div>
        </div>
        <div v-else-if="(table.use_cases || []).length" class="flex flex-wrap gap-1.5">
          <span
            v-for="(uc, i) in table.use_cases"
            :key="i"
            class="inline-flex px-2 py-0.5 rounded-md text-xs bg-[#F6EFEA] text-[#A8330F]"
          >{{ uc }}</span>
        </div>
        <p v-else class="text-sm text-gray-400 italic">None yet.</p>
      </div>

      <!-- Quality notes -->
      <div>
        <div class="flex items-center justify-between mb-1.5">
          <label class="text-xs font-semibold uppercase tracking-wide text-gray-500">Quality notes</label>
          <button
            v-if="!editingQuality"
            type="button"
            class="inline-flex items-center gap-1 text-xs text-[#C2541E] hover:text-[#A8330F]"
            @click="startQuality"
          >
            <Icon name="heroicons:pencil-square" class="w-3.5 h-3.5" /> Edit
          </button>
        </div>
        <div v-if="editingQuality">
          <UTextarea
            v-model="qualityDraft"
            :rows="2"
            autoresize
            placeholder="One note per line, or comma-separated"
          />
          <div class="mt-2 flex items-center gap-2">
            <UButton size="2xs" :loading="savingQuality" @click="saveQuality">Save</UButton>
            <UButton size="2xs" variant="ghost" color="gray" @click="editingQuality = false">Cancel</UButton>
          </div>
        </div>
        <ul v-else-if="(table.quality_notes || []).length" class="space-y-1">
          <li
            v-for="(qn, i) in table.quality_notes"
            :key="i"
            class="flex items-start gap-1.5 text-sm text-gray-700"
          >
            <Icon name="heroicons:exclamation-triangle" class="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
            <span>{{ qn }}</span>
          </li>
        </ul>
        <p v-else class="text-sm text-gray-400 italic">None.</p>
      </div>

      <!-- Columns -->
      <div>
        <label class="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          Columns ({{ (table.columns || []).length }})
        </label>
        <div class="rounded-md border border-gray-200 overflow-hidden">
          <table class="w-full text-sm">
            <thead class="bg-gray-50 text-gray-500">
              <tr>
                <th class="text-left font-medium px-3 py-1.5 w-1/4">Name</th>
                <th class="text-left font-medium px-3 py-1.5 w-1/6">Type</th>
                <th class="text-left font-medium px-3 py-1.5">Meaning</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="col in (table.columns || [])"
                :key="col.id"
                class="border-t border-gray-100 align-top"
              >
                <td class="px-3 py-1.5 font-mono text-gray-800 text-xs">{{ col.name }}</td>
                <td class="px-3 py-1.5 text-gray-500 text-xs">{{ col.type }}</td>
                <td class="px-3 py-1.5">
                  <div v-if="editingCol === col.id" class="flex items-start gap-2">
                    <UInput
                      v-model="colDraft"
                      size="2xs"
                      class="flex-1"
                      placeholder="What does this column mean?"
                      @keydown.enter="saveCol(col)"
                    />
                    <UButton size="2xs" :loading="savingCol" @click="saveCol(col)">Save</UButton>
                    <UButton size="2xs" variant="ghost" color="gray" @click="editingCol = null">Cancel</UButton>
                  </div>
                  <div v-else class="group flex items-start gap-2">
                    <span
                      class="text-gray-700 flex-1"
                      :class="{ 'text-gray-400 italic': !col.meaning }"
                    >{{ col.meaning || 'No meaning yet.' }}</span>
                    <button
                      type="button"
                      class="opacity-0 group-hover:opacity-100 transition-opacity text-[#C2541E] hover:text-[#A8330F] shrink-0"
                      @click="startCol(col)"
                    >
                      <Icon name="heroicons:pencil-square" class="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="!(table.columns || []).length">
                <td colspan="3" class="px-3 py-3 text-center text-xs text-gray-400">No columns.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Column {
  id: string
  name: string
  type: string
  meaning?: string
  status?: string
}
interface SemanticTable {
  id: string
  table_name: string
  description?: string
  use_cases?: string[]
  quality_notes?: string[]
  status?: string
  described?: boolean
  columns?: Column[]
}

const props = defineProps<{
  table: SemanticTable
  // Handlers return true on success, false on failure (so the editor stays open).
  onPatchTable: (id: string, body: Record<string, any>) => Promise<boolean>
  onPatchColumn: (id: string, body: Record<string, any>) => Promise<boolean>
}>()

const expanded = ref(false)

// --- approval status ---
const savingStatus = ref(false)
async function setStatus(status: string) {
  savingStatus.value = true
  await props.onPatchTable(props.table.id, { status })
  savingStatus.value = false
}

// --- description ---
const editingDesc = ref(false)
const savingDesc = ref(false)
const descDraft = ref('')
function startDesc() {
  descDraft.value = props.table.description || ''
  editingDesc.value = true
}
async function saveDesc() {
  savingDesc.value = true
  const ok = await props.onPatchTable(props.table.id, { description: descDraft.value })
  savingDesc.value = false
  if (ok !== false) editingDesc.value = false
}

// --- use cases ---
const editingUseCases = ref(false)
const savingUseCases = ref(false)
const useCasesDraft = ref('')
function startUseCases() {
  useCasesDraft.value = (props.table.use_cases || []).join('\n')
  editingUseCases.value = true
}
function splitList(s: string): string[] {
  return s
    .split(/[\n,]/)
    .map(x => x.trim())
    .filter(Boolean)
}
async function saveUseCases() {
  savingUseCases.value = true
  const ok = await props.onPatchTable(props.table.id, { use_cases: splitList(useCasesDraft.value) })
  savingUseCases.value = false
  if (ok !== false) editingUseCases.value = false
}

// --- quality notes ---
const editingQuality = ref(false)
const savingQuality = ref(false)
const qualityDraft = ref('')
function startQuality() {
  qualityDraft.value = (props.table.quality_notes || []).join('\n')
  editingQuality.value = true
}
async function saveQuality() {
  savingQuality.value = true
  const ok = await props.onPatchTable(props.table.id, { quality_notes: splitList(qualityDraft.value) })
  savingQuality.value = false
  if (ok !== false) editingQuality.value = false
}

// --- column meaning ---
const editingCol = ref<string | null>(null)
const savingCol = ref(false)
const colDraft = ref('')
function startCol(col: Column) {
  colDraft.value = col.meaning || ''
  editingCol.value = col.id
}
async function saveCol(col: Column) {
  savingCol.value = true
  const ok = await props.onPatchColumn(col.id, { meaning: colDraft.value })
  savingCol.value = false
  if (ok !== false) editingCol.value = null
}
</script>
