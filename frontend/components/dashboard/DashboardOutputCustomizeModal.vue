<template>
	<!-- NotebookLM-style "Customize output" dialog. Tap an output tile (Dashboard /
	     Report / Slides / Excel) -> this modal -> Generate passes the chosen options
	     through to the generate endpoint. Excel has no LLM, so model/language/prose
	     fields are hidden for it. Self-contained: owns only its field state. -->
	<transition name="ocm-fade">
		<div v-if="open" class="ocm-overlay" @click.self="$emit('close')" @keydown.esc="$emit('close')">
			<div class="ocm-sheet" role="dialog" aria-label="Customize output">
				<div class="ocm-head">
					<span class="ocm-ico">{{ meta.icon }}</span>
					<div class="ocm-ttl">{{ meta.title }}</div>
					<button class="ocm-x" @click="$emit('close')" aria-label="Close">✕</button>
				</div>

				<div class="ocm-body">
					<!-- Format presets (variant-specific) -->
					<div v-if="meta.formats.length" class="ocm-field">
						<label class="ocm-lbl">Format</label>
						<div class="ocm-seg">
							<button v-for="f in meta.formats" :key="f.value"
								class="ocm-seg-btn" :class="{ on: format === f.value }"
								@click="format = f.value">{{ f.label }}</button>
						</div>
					</div>

					<!-- Length (dashboard/report/slides) -->
					<div v-if="variant !== 'excel'" class="ocm-field">
						<label class="ocm-lbl">Length</label>
						<div class="ocm-seg">
							<button class="ocm-seg-btn" :class="{ on: length === 'compact' }" @click="length = 'compact'">Compact</button>
							<button class="ocm-seg-btn" :class="{ on: length === '' }" @click="length = ''">Standard</button>
							<button class="ocm-seg-btn" :class="{ on: length === 'full' }" @click="length = 'full'">Full</button>
						</div>
					</div>

					<!-- Depth (dashboard/report/slides) -->
					<div v-if="variant !== 'excel'" class="ocm-field">
						<label class="ocm-lbl">Depth</label>
						<div class="ocm-seg">
							<button class="ocm-seg-btn" :class="{ on: depth === '' }" @click="depth = ''">Auto</button>
							<button class="ocm-seg-btn" :class="{ on: depth === 'exec' }" @click="depth = 'exec'">Executive</button>
							<button class="ocm-seg-btn" :class="{ on: depth === 'analyst' }" @click="depth = 'analyst'">Analyst</button>
						</div>
						<span class="ocm-hint">Executive = headline KPIs + one chart · Analyst = full breakdowns &amp; drill-downs.</span>
					</div>

					<!-- Focus (free text) -->
					<div class="ocm-field">
						<label class="ocm-lbl">Focus <span class="ocm-opt">optional</span></label>
						<textarea v-model="describe" class="ocm-ta" rows="2"
							:placeholder="meta.placeholder"></textarea>
						<div class="ocm-samples">
							<span class="ocm-samples-lbl">Try:</span>
							<button v-for="s in meta.samples" :key="s" class="ocm-chip" @click="describe = s">{{ s }}</button>
						</div>
					</div>

					<!-- Model + Language (LLM variants only) -->
					<div v-if="variant !== 'excel'" class="ocm-row">
						<div class="ocm-field ocm-half">
							<label class="ocm-lbl">Model</label>
							<select v-model="modelId" class="ocm-sel">
								<option v-if="autoModel" value="auto">Auto (pick best)</option>
								<option v-if="moa" value="moa">MoA (panel of models)</option>
								<option value="">Default</option>
								<option v-for="m in models" :key="m.id" :value="m.model_id">{{ m.model_id }}</option>
							</select>
							<span class="ocm-hint">Auto lets the agent choose the right model for the job.</span>
						</div>
						<div class="ocm-field ocm-half">
							<label class="ocm-lbl">Language</label>
							<select v-model="language" class="ocm-sel">
								<option v-for="l in LANGS" :key="l" :value="l">{{ l }}</option>
							</select>
						</div>
					</div>
				</div>

				<div class="ocm-foot">
					<button class="ocm-cancel" @click="$emit('close')">Cancel</button>
					<button class="ocm-gen" @click="onGenerate">Generate →</button>
				</div>
			</div>
		</div>
	</transition>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
	open: boolean
	variant: 'dashboard' | 'report' | 'slides' | 'excel'
	prefill?: string
}>(), { open: false, variant: 'dashboard', prefill: '' })

const emit = defineEmits<{
	(e: 'close'): void
	(e: 'generate', payload: { variant: string; describe: string; format: string; length: string; depth: string; model_id: string; language: string }): void
}>()

const LANGS = ['English', 'Spanish', 'French', 'German', 'Portuguese', 'Arabic', 'Chinese', 'Japanese', 'Burmese']

const describe = ref('')
const format = ref('')
const length = ref('')
const depth = ref('')
const modelId = ref('')
const language = ref('English')
const models = ref<any[]>([])
const autoModel = ref(false)   // HYBRID_AUTO_MODEL — offer the "Auto" model option
const moa = ref(false)         // HYBRID_MOA — offer the "MoA" panel option

const VARIANTS: Record<string, any> = {
	dashboard: {
		icon: '📊', title: 'Build a dashboard',
		placeholder: 'e.g. calls by channel + monthly trend',
		formats: [
			{ value: '', label: 'Auto' },
			{ value: 'KPI-led layout with headline metrics up top', label: 'KPI-led' },
			{ value: 'analytical layout with breakdowns and drill-downs', label: 'Analytical' },
			{ value: 'narrative layout mixing prose and charts', label: 'Narrative' },
		],
		samples: ['calls by channel + monthly trend', 'success rate by call outcome', 'leads vs new users per month'],
	},
	report: {
		icon: '📄', title: 'Write a report',
		placeholder: 'e.g. what changed vs last month',
		formats: [
			{ value: 'executive summary', label: 'Exec summary' },
			{ value: 'full detailed report', label: 'Full report' },
			{ value: 'concise bulleted brief', label: 'Brief' },
		],
		samples: ['what changed vs last month', 'top drivers of unsuccessful calls', 'brand switching summary'],
	},
	slides: {
		icon: '📽️', title: 'Make slides',
		placeholder: 'e.g. retention + brand switching for the board',
		formats: [
			{ value: 'clean executive deck with key talking points', label: 'Executive deck' },
			{ value: 'detailed walkthrough deck with full text', label: 'Detailed' },
		],
		samples: ['retention + brand switching for the board', 'monthly performance highlights', 'channel deep-dive'],
	},
	excel: {
		icon: '📗', title: 'Build a workbook',
		placeholder: 'e.g. channel, calls, success%, leads grouped by month',
		formats: [],
		samples: ['channel, calls, success%, leads grouped by month', 'outcome counts by month', 'brand switching matrix'],
	},
}
const meta = computed(() => VARIANTS[props.variant] || VARIANTS.dashboard)

async function loadModels() {
	try {
		const { data } = await useMyFetch<any>('/llm/models?is_enabled=true')
		const arr = (data.value as any) || []
		models.value = Array.isArray(arr) ? arr : (arr.models || [])
	} catch { models.value = [] }
	// Auto / MoA availability from org flags (same as the chat picker).
	try {
		const { data } = await useMyFetch<any[]>('/organization/hybrid-flags')
		const rows = (data.value as any[]) || []
		autoModel.value = !!rows.find(r => r?.env_name === 'HYBRID_AUTO_MODEL')?.effective
		moa.value = !!rows.find(r => r?.env_name === 'HYBRID_MOA')?.effective
	} catch { autoModel.value = false; moa.value = false }
}

// Reset fields + prefill focus each time the modal opens.
watch(() => props.open, async (o) => {
	if (!o) return
	describe.value = props.prefill || ''
	format.value = meta.value.formats.length ? meta.value.formats[0].value : ''
	length.value = ''
	depth.value = ''
	language.value = 'English'
	if (!models.value.length) await loadModels()
	// Default to Auto when the org has it; else org default.
	modelId.value = autoModel.value ? 'auto' : ''
})

function onGenerate() {
	emit('generate', {
		variant: props.variant,
		describe: describe.value.trim(),
		format: format.value,
		length: length.value,
		depth: depth.value,
		model_id: modelId.value,
		language: language.value,
	})
}
</script>

<style scoped>
.ocm-overlay { position: fixed; inset: 0; z-index: 90; background: rgba(30, 22, 12, .38); display: grid; place-items: center; padding: 20px; }
.ocm-sheet { width: 520px; max-width: 100%; background: #fff; border-radius: 16px; box-shadow: 0 30px 70px -24px rgba(40, 25, 10, .5); overflow: hidden; display: flex; flex-direction: column; }
.ocm-head { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid #EFE7DA; }
.ocm-ico { font-size: 20px; }
.ocm-ttl { flex: 1; font-family: 'Spectral', ui-serif, Georgia, serif; font-size: 17px; font-weight: 600; color: #211B14; }
.ocm-x { border: none; background: none; color: #b7ac9c; cursor: pointer; font-size: 15px; padding: 4px; border-radius: 8px; }
.ocm-x:hover { background: #F4EEE5; color: #C2541E; }
.ocm-body { padding: 16px; display: flex; flex-direction: column; gap: 14px; max-height: 62vh; overflow-y: auto; }
.ocm-field { display: flex; flex-direction: column; gap: 6px; }
.ocm-lbl { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .4px; color: #8A7F70; }
.ocm-opt { font-weight: 500; text-transform: none; letter-spacing: 0; color: #b3ab9d; }
.ocm-seg { display: flex; gap: 6px; flex-wrap: wrap; }
.ocm-seg-btn { flex: 1; min-width: 80px; padding: 7px 10px; border: 1px solid #E5DDCF; background: #FBFAF6; border-radius: 9px; font-size: 12.5px; color: #6a6153; cursor: pointer; transition: all .12s; }
.ocm-seg-btn:hover { border-color: #d9c4b6; }
.ocm-seg-btn.on { background: #C2541E; border-color: #C2541E; color: #fff; font-weight: 600; }
.ocm-ta { border: 1px solid #E5DDCF; border-radius: 10px; padding: 9px 11px; font-size: 13px; color: #2b2419; resize: vertical; font-family: inherit; }
.ocm-ta:focus { outline: 2px solid #C2541E44; border-color: #C2541E; }
.ocm-row { display: flex; gap: 12px; }
.ocm-half { flex: 1; }
.ocm-sel { border: 1px solid #E5DDCF; border-radius: 10px; padding: 8px 10px; font-size: 13px; color: #2b2419; background: #fff; cursor: pointer; }
.ocm-hint { font-size: 11px; color: #a29886; line-height: 1.4; }
.ocm-samples { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 6px; }
.ocm-samples-lbl { font-size: 11px; color: #a29886; }
.ocm-chip { border: 1px solid #E9E0D3; background: #FBFAF6; color: #6a6153; border-radius: 20px; padding: 3px 10px; font-size: 11.5px; cursor: pointer; transition: all .12s; }
.ocm-chip:hover { border-color: #C2541E; color: #C2541E; background: #FFF6F1; }
.ocm-foot { display: flex; justify-content: flex-end; gap: 10px; padding: 12px 16px; border-top: 1px solid #EFE7DA; }
.ocm-cancel { padding: 8px 16px; border: 1px solid #E5DDCF; background: #fff; border-radius: 10px; font-size: 13px; color: #6a6153; cursor: pointer; }
.ocm-cancel:hover { background: #F4EEE5; }
.ocm-gen { padding: 8px 18px; border: none; background: #C2541E; color: #fff; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; }
.ocm-gen:hover { background: #a8471a; }
.ocm-fade-enter-active, .ocm-fade-leave-active { transition: opacity .16s; }
.ocm-fade-enter-from, .ocm-fade-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .ocm-fade-enter-active, .ocm-fade-leave-active { transition: none; } }
</style>
