<template>
  <div class="h-full overflow-y-auto bg-[#FBFAF6] px-5 py-5 text-sm">
    <!-- Header -->
    <div class="flex items-center gap-2 mb-1">
      <UIcon name="i-heroicons-book-open" class="w-4 h-4 text-[#C2683F]" />
      <h3 class="text-[15px] font-semibold text-[#1f2328]"
          style="font-family: ui-serif, Georgia, 'Times New Roman', serif">How to get each value</h3>
    </div>
    <p class="text-xs text-[#6b6b6b] leading-relaxed mb-4">{{ doc.overview }}</p>

    <!-- Prerequisites -->
    <div v-if="doc.prerequisites?.length"
         class="rounded-lg border border-dashed border-[#E8C9B5] bg-white px-3 py-2.5 mb-4">
      <div class="text-[11px] font-semibold text-[#1f2328] mb-1.5">One-time setup (do first)</div>
      <ul class="space-y-1">
        <li v-for="(p, i) in doc.prerequisites" :key="i"
            class="text-xs text-[#6b6b6b] leading-snug flex gap-1.5">
          <span class="text-[#C2683F] mt-0.5">•</span><span>{{ p }}</span>
        </li>
      </ul>
    </div>

    <!-- Field cards -->
    <div
      v-for="card in cards"
      :key="card.name"
      :data-field="card.name"
      class="rounded-xl border bg-white px-3 py-3 mb-2.5 transition-all"
      :class="highlightField === card.name
        ? 'border-[#E8C9B5] shadow-[0_8px_22px_-14px_rgba(194,104,63,.5)]'
        : 'border-[#E7E5DD]'"
      @mouseenter="$emit('hover-field', card.name)"
      @mouseleave="$emit('hover-field', null)"
    >
      <div class="flex items-center gap-2">
        <span class="text-[13px] font-semibold text-[#1f2328]">{{ card.title }}</span>
        <span v-if="card.fd.required !== false"
              class="text-[9px] font-bold text-[#b4453a] bg-[#fbeeec] border border-[#f0cdc9] rounded-full px-1.5 leading-[14px]">REQUIRED</span>
        <span v-else
              class="text-[9px] font-bold text-[#9a958c] bg-[#F4F1EA] border border-[#E7E5DD] rounded-full px-1.5 leading-[14px]">OPTIONAL</span>
      </div>

      <p v-if="card.fd.what" class="text-xs text-[#6b6b6b] leading-snug mt-1.5">{{ card.fd.what }}</p>

      <div v-if="card.fd.where"
           class="text-[11px] text-[#A8542F] bg-[#F3E7DF] border border-[#E8C9B5] rounded-md px-2 py-1.5 mt-2 leading-relaxed">
        {{ card.fd.where }}
      </div>

      <ol v-if="card.fd.steps?.length" class="list-decimal ps-4 mt-2 space-y-0.5">
        <li v-for="(s, i) in card.fd.steps" :key="i" class="text-xs text-[#6b6b6b] leading-snug">{{ s }}</li>
      </ol>

      <code v-if="card.fd.example"
            class="inline-block mt-2 text-[11px] text-[#1f2328] bg-[#F4F1EA] border border-[#E7E5DD] rounded px-2 py-0.5"
            style="font-family: ui-monospace, Menlo, monospace">{{ card.fd.example }}</code>

      <div v-if="card.fd.gotcha"
           class="text-[11px] text-[#8a5a12] bg-[#fbf3e3] border border-[#f0dcb6] rounded-md px-2 py-1.5 mt-2 leading-snug">
        {{ card.fd.gotcha }}
      </div>
    </div>

    <!-- Friendly note when truly nothing to document -->
    <div v-if="!cards.length"
         class="rounded-xl border border-[#E7E5DD] bg-white px-3 py-4 text-center text-xs text-[#9a958c]">
      Fill in the connection fields on the left. No extra guidance is available for this connector yet.
    </div>

    <!-- Troubleshooting -->
    <div v-if="doc.troubleshooting?.length"
         class="rounded-lg border border-[#f0dcb6] bg-[#fbf3e3] px-3 py-2.5 mt-3">
      <div class="text-[11px] font-semibold text-[#8a5a12] mb-1.5 flex items-center gap-1.5">
        <UIcon name="i-heroicons-lifebuoy" class="w-3.5 h-3.5" />Troubleshooting
      </div>
      <ul class="space-y-1">
        <li v-for="(t, i) in doc.troubleshooting" :key="i"
            class="text-[11px] text-[#8a5a12] leading-snug flex gap-1.5">
          <span class="mt-0.5">•</span><span>{{ t }}</span>
        </li>
      </ul>
    </div>

    <a v-if="doc.docsUrl" :href="doc.docsUrl" target="_blank" rel="noopener"
       class="inline-flex items-center gap-1 mt-3 text-xs font-medium text-[#C2683F] hover:text-[#A8542F]">
      <UIcon name="i-heroicons-arrow-top-right-on-square" class="w-3.5 h-3.5" />
      Official documentation
    </a>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { getConnectorDoc, buildGenericDoc } from '~/utils/connectorDocs'
import type { ConnectorDoc, FieldDoc } from '~/utils/connectorDocs/types'

const props = defineProps<{
  connectorType: string
  connectorLabel: string
  fields: any[]
  highlightField?: string | null
}>()

defineEmits<{ (e: 'hover-field', name: string | null): void }>()

const doc = computed<ConnectorDoc>(
  () => getConnectorDoc(props.connectorType) || buildGenericDoc(props.connectorLabel || props.connectorType, props.fields || [])
)

// Order cards by the form's field list first, then any extra documented fields.
const cards = computed<Array<{ name: string; title: string; fd: FieldDoc }>>(() => {
  const d = doc.value
  const out: Array<{ name: string; title: string; fd: FieldDoc }> = []
  const seen = new Set<string>()
  const titleFor = (n: string) => {
    const f = (props.fields || []).find((x: any) => String(x?.field_name ?? x?.name) === n)
    return (f && (f.title || f.field_name)) || n
  }
  for (const f of props.fields || []) {
    const n = String(f?.field_name ?? f?.name ?? '').trim()
    if (!n || seen.has(n)) continue
    if (d.fields[n]) { out.push({ name: n, title: f.title || n, fd: d.fields[n] }); seen.add(n) }
  }
  for (const [n, fd] of Object.entries(d.fields)) {
    if (seen.has(n)) continue
    out.push({ name: n, title: titleFor(n), fd }); seen.add(n)
  }
  return out
})
</script>
