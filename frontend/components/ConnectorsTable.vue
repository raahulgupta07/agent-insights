<template>
  <div class="overflow-x-auto rounded-[12px] border border-[#E9E0D3] bg-white">
    <table class="w-full text-[13px] border-collapse">
      <thead>
        <tr class="text-left text-[11px] uppercase tracking-wide text-[#9a958c] border-b border-[#F0EAE0]">
          <th class="font-medium px-3.5 py-2.5">Connector</th>
          <th class="font-medium px-3.5 py-2.5">Type</th>
          <th class="font-medium px-3.5 py-2.5">Owner</th>
          <th class="font-medium px-3.5 py-2.5">Who can use</th>
          <th v-if="context === 'studio'" class="font-medium px-3.5 py-2.5">Active</th>
          <th v-else class="font-medium px-3.5 py-2.5">Agents</th>
          <th class="font-medium px-3.5 py-2.5">Sync</th>
          <th class="font-medium px-3.5 py-2.5 text-right">Actions</th>
        </tr>
      </thead>
      <tbody>
        <!-- Empty state -->
        <tr v-if="rows.length === 0">
          <td :colspan="8" class="px-3.5 py-8 text-center text-[#9a958c] text-xs">
            No connectors yet.
          </td>
        </tr>

        <tr
          v-for="row in rows"
          :key="row.id"
          class="border-b border-[#F4EEE3] last:border-0 hover:bg-[#FBFAF6] transition-colors"
        >
          <!-- Connector (emoji + name) -->
          <td class="px-3.5 py-2.5">
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="w-8 h-8 rounded-[9px] grid place-items-center text-base shrink-0" style="background:#F0E9DB;">
                {{ typeEmoji(row.type) }}
              </span>
              <span class="font-semibold text-[#1f2328] truncate">{{ row.name }}</span>
            </div>
          </td>

          <!-- Type -->
          <td class="px-3.5 py-2.5 text-[#6b6b6b] whitespace-nowrap">{{ row.type || 'connector' }}</td>

          <!-- Owner -->
          <td class="px-3.5 py-2.5 text-[#6b6b6b] whitespace-nowrap">
            {{ row.can_edit && !row.is_org ? 'you' : 'admin' }}
          </td>

          <!-- Who can use -->
          <td class="px-3.5 py-2.5">
            <button
              v-if="row.can_edit && !row.is_org"
              type="button"
              class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full hover:brightness-95 transition"
              :style="visBadge(row).style"
              @click="emit('share', row)"
            >{{ visBadge(row).label }}</button>
            <span
              v-else
              class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full"
              :style="visBadge(row).style"
            >{{ visBadge(row).label }}</span>
          </td>

          <!-- Active (studio) -->
          <td v-if="context === 'studio'" class="px-3.5 py-2.5">
            <button
              v-if="!row.active"
              type="button"
              class="text-[12px] px-2.5 py-1 rounded-lg font-semibold text-white bg-[#2F6F4F] hover:bg-[#255b41]"
              @click="emit('activate', row)"
            >Activate for agent</button>
            <button
              v-else
              type="button"
              class="text-[12px] px-2.5 py-1 rounded-lg bg-white border text-[#2F6F4F] hover:bg-[#f4f8f4] whitespace-nowrap"
              style="border-color:#cfe0d2;"
              @click="emit('deactivate', row)"
            >✓ Active · Deactivate</button>
          </td>

          <!-- Agents (org) -->
          <td v-else class="px-3.5 py-2.5 text-[#6b6b6b] whitespace-nowrap">
            {{ row.agent_count ?? 0 }}
          </td>

          <!-- Sync -->
          <td class="px-3.5 py-2.5 text-[#9a958c] whitespace-nowrap">
            {{ row.last_synced_at ? shortDate(row.last_synced_at) : '—' }}
          </td>

          <!-- Actions -->
          <td class="px-3.5 py-2.5 text-right">
            <div v-if="row.can_edit" class="inline-block">
              <button
                type="button"
                class="w-7 h-7 grid place-items-center rounded-lg text-[#6b6b6b] hover:bg-[#F0EAE0] transition"
                @click.stop="toggleMenu(row.id, $event)"
                aria-label="Actions"
              >⋯</button>
              <!-- Teleport to body + fixed position so the menu escapes the
                   table's overflow-x-auto clip context (Delete was cut off). -->
              <Teleport to="body">
                <div
                  v-if="openMenuId === row.id"
                  class="fixed z-50 w-36 rounded-lg border border-[#E9E0D3] bg-white shadow-lg py-1 text-left"
                  :style="{ top: menuPos.top + 'px', left: menuPos.left + 'px' }"
                >
                  <button type="button" class="block w-full px-3 py-1.5 text-[13px] text-[#1f2328] hover:bg-[#FBFAF6]"
                    @click="pick('test', row)">Test</button>
                  <button type="button" class="block w-full px-3 py-1.5 text-[13px] text-[#1f2328] hover:bg-[#FBFAF6]"
                    @click="pick('edit', row)">Edit</button>
                  <button type="button" class="block w-full px-3 py-1.5 text-[13px] text-[#a13d3d] hover:bg-[#fdf6f6]"
                    @click="pick('delete', row)">Delete</button>
                </div>
              </Teleport>
            </div>
            <span v-else class="text-[#cbb9a0]">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'

defineProps<{
  rows: any[]
  context: 'studio' | 'org'
}>()

const emit = defineEmits<{
  (e: 'activate', row: any): void
  (e: 'deactivate', row: any): void
  (e: 'test', row: any): void
  (e: 'edit', row: any): void
  (e: 'delete', row: any): void
  (e: 'share', row: any): void
}>()

const openMenuId = ref<string | null>(null)
const menuPos = ref<{ top: number; left: number }>({ top: 0, left: 0 })
const MENU_W = 144   // w-36
const MENU_H = 112   // ~3 items + padding

function toggleMenu(id: string, ev: MouseEvent) {
  if (openMenuId.value === id) { openMenuId.value = null; return }
  const btn = ev.currentTarget as HTMLElement
  const r = btn.getBoundingClientRect()
  // Right-align under the trigger; flip up if it would run off the bottom.
  let top = r.bottom + 4
  if (top + MENU_H > window.innerHeight) top = r.top - MENU_H - 4
  let left = r.right - MENU_W
  if (left < 8) left = 8
  menuPos.value = { top, left }
  openMenuId.value = id
}
function closeMenu() { openMenuId.value = null }
function pick(action: 'test' | 'edit' | 'delete', row: any) {
  openMenuId.value = null
  emit(action, row)
}

// Close on any outside click / scroll / resize / Escape so a body-teleported
// menu never lingers detached from its row.
function onDocClick() { if (openMenuId.value) closeMenu() }
function onScroll() { if (openMenuId.value) closeMenu() }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') closeMenu() }
onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('scroll', onScroll, true)
  window.addEventListener('resize', onScroll)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('scroll', onScroll, true)
  window.removeEventListener('resize', onScroll)
  document.removeEventListener('keydown', onKey)
})

// ── Helpers ──────────────────────────────────────────────────────────────────
const EMOJI: Record<string, string> = {
  postgresql: '🐘', mysql: '🐬', snowflake: '❄️', ms_fabric: '🟦', ms_fabric_user: '🟦',
  powerbi_report_server: '📊', rest_api: '📦', custom_api: '📦', csv: '📁', bigquery: '🔷',
  databricks: '🧱', redshift: '🟥', clickhouse: '🟡', mssql: '🟦', oracle: '🟧', sqlite: '🗃️',
}
function typeEmoji(t: string) {
  return EMOJI[t] || '🔌'
}
function shortDate(s: string) {
  try { return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) } catch { return '' }
}

function connVisibility(row: any): 'private' | 'shared' | 'org' {
  const v = row?.visibility
  if (v === 'private' || v === 'shared' || v === 'org') return v
  return row?.is_org ? 'org' : 'private'
}
function visBadge(row: any): { label: string; style: string } {
  switch (connVisibility(row)) {
    case 'org':
      return { label: '🌐 Org-wide', style: 'background:#ECF1EC;color:#2F6F4F;border:1px solid #d4e3d4;' }
    case 'shared':
      return { label: '👥 Shared', style: 'background:#E4F0F4;color:#1F6F8B;border:1px solid #cfe2e8;' }
    default:
      return { label: '🔒 Private', style: 'background:#FBF3E2;color:#8a6d3b;border:1px solid #ECDCBB;' }
  }
}
</script>
