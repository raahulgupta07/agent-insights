<template>
  <!-- Contextual left rail: shows ONLY the active top-nav group's items.
       Hidden on pages with no group. When the active group has sub-sections +
       a railHeader (currently Workspace), it renders as a studio-style rounded
       #FBFAF6 card with a header card + section eyebrows + count badges. -->
  <aside
    v-if="activeGroup"
    :class="hasSections
      ? 'cag-rail-card shrink-0 self-stretch min-h-0 overflow-y-auto m-2'
      : 'cag-rail shrink-0 self-stretch min-h-0 overflow-y-auto'"
  >
    <!-- Studio-style header card (only on sectioned groups) -->
    <div v-if="hasSections && activeGroup.railHeader" class="px-3 pt-3 pb-2.5 border-b border-[#E9E0D3]">
      <button class="text-[11px] text-[#9a958c] hover:text-[#6b6b6b] mb-1.5 inline-flex items-center gap-1" @click="router.push('/')">
        <UIcon name="i-heroicons-arrow-left" class="w-3 h-3" /> Back to Home
      </button>
      <div class="flex items-center gap-2">
        <div class="shrink-0 flex items-center justify-center w-7 h-7 rounded-lg bg-[#F4F1EA] border border-[#E9E0D3] text-[#C2541E]">
          <UIcon :name="activeGroup.railHeader.icon || 'i-heroicons-squares-2x2'" class="w-4 h-4" />
        </div>
        <div class="min-w-0">
          <div class="flex items-center gap-1.5">
            <span class="text-sm font-semibold text-[#1f2328] truncate" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ $t(activeGroup.title) }}</span>
            <span v-if="activeGroup.railHeader.badge" class="text-[9px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded bg-[#EDEBE3] text-[#6b6b6b] shrink-0">{{ activeGroup.railHeader.badge }}</span>
          </div>
          <p v-if="activeGroup.railHeader.subtitle" class="text-[11px] text-[#9a958c] truncate">{{ activeGroup.railHeader.subtitle }}</p>
        </div>
      </div>
    </div>

    <!-- Group title eyebrow (only when the group has NO sub-sections) -->
    <div v-if="!hasSections" class="px-2.5 pt-5 pb-3">
      <div class="cag-rail-eyebrow">{{ $t(activeGroup.title) }}</div>
    </div>

    <nav :class="hasSections ? 'px-2 py-2 space-y-px' : 'px-2.5 pt-2 pb-4 space-y-0.5'">
      <template v-for="(row, i) in railRows" :key="row.item.key">
        <!-- Sub-section eyebrow (WORKSPACE / OUTPUTS / AUTOMATE …) -->
        <div v-if="row.eyebrow" class="cag-rail-eyebrow px-2" :class="i === 0 ? 'pb-1 pt-1' : 'pt-3 pb-1'">{{ row.eyebrow }}</div>

        <!-- Action item (e.g. MCP Server modal) -->
        <button
          v-if="row.item.action"
          @click="row.item.action && row.item.action()"
          :class="hasSections ? 'cag-sec-link' : 'cag-rail-link'"
        >
          <span :class="hasSections ? 'cag-sec-ic' : 'cag-rail-ic'">
            <UIcon v-if="row.item.icon" :name="row.item.icon" />
            <component v-else-if="row.item.component" :is="row.item.component" class="w-[17px] h-[17px]" />
          </span>
          <span class="flex-1 text-start truncate">{{ $t(row.item.label) }}</span>
        </button>

        <!-- Route item -->
        <NuxtLink
          v-else
          :to="row.item.href"
          :class="[
            hasSections ? 'cag-sec-link' : 'cag-rail-link',
            isRouteActive(row.item.activePath || row.item.href!) ? (hasSections ? 'cag-sec-active' : 'cag-rail-active') : '',
          ]"
        >
          <span :class="hasSections ? 'cag-sec-ic' : 'cag-rail-ic'">
            <UIcon v-if="row.item.icon" :name="row.item.icon" />
            <component v-else-if="row.item.component" :is="row.item.component" class="w-[17px] h-[17px]" />
          </span>
          <span class="flex-1 truncate">{{ $t(row.item.label) }}</span>
          <span v-if="railCounts[row.item.key]" class="text-[11px] text-[#9a958c] shrink-0">{{ railCounts[row.item.key] }}</span>
        </NuxtLink>
      </template>
    </nav>
  </aside>
</template>

<script setup lang="ts">
  const router = useRouter()
  const { activeGroup, isRouteActive, railCounts } = useAppNav()

  const hasSections = computed(() => (activeGroup.value?.items || []).some(i => !!i.section))

  // Map each item to { item, eyebrow } — eyebrow set when the section changes.
  const railRows = computed(() => {
    const items = activeGroup.value?.items || []
    let prev = ''
    return items.map((item) => {
      const eyebrow = item.section && item.section !== prev ? item.section : ''
      if (item.section) prev = item.section
      return { item, eyebrow }
    })
  })
</script>

<style scoped>
/* ---- legacy flat rail (Build / Manage groups) ---- */
.cag-rail {
  width: 224px;
  background: #F2EBE0;
  border-right: 1px solid #E9E0D3;
  font-family: 'Hanken Grotesk', system-ui, sans-serif;
}
/* ---- studio-style rounded card rail (sectioned groups) ---- */
.cag-rail-card {
  width: 240px;
  background: #FBFAF6;
  border: 1px solid #E9E0D3;
  border-radius: 16px;
  font-family: 'Hanken Grotesk', system-ui, sans-serif;
}
.cag-rail-eyebrow {
  font-size: 9px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: #9a958c;
  font-weight: 700;
}
/* flat rail link */
.cag-rail-link {
  display: flex; align-items: center; gap: 11px; width: 100%;
  padding: 9px 11px; border-radius: 11px;
  font-size: 13.5px; font-weight: 500; color: #574E44; text-decoration: none;
  transition: background .12s, color .12s;
}
.cag-rail-link:hover { background: rgba(0,0,0,.04); color: #1A1611; }
.cag-rail-ic { display:flex; align-items:center; justify-content:center; width:17px; height:17px; flex:0 0 17px; color:#8c8479; }
.cag-rail-active { background:#fff; color:#A8330F; font-weight:600; box-shadow:0 1px 2px rgba(0,0,0,.05); }
.cag-rail-active .cag-rail-ic { color:#C2541E; }
/* sectioned (studio) rail link — denser, matches studio nav */
.cag-sec-link {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 6px 12px; border-radius: 8px;
  font-size: 12px; color: #6b6b6b; text-decoration: none; text-align: left;
  transition: background .12s, color .12s;
}
.cag-sec-link:hover { background: #faf8f3; color: #1f2328; }
.cag-sec-ic { display:flex; align-items:center; justify-content:center; width:14px; height:14px; flex:0 0 14px; color:#8c8479; }
.cag-sec-active { background:#ECEAE1; color:#1f2328; font-weight:500; }
.cag-sec-active .cag-sec-ic { color:#C2541E; }
</style>
