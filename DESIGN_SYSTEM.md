# CityAgent Analytics — Design System (Source of Truth)

Standardized UI/UX spec for the Nuxt frontend. Brand = **clay / terracotta**. Goal: one
look across every page (list pages, settings, studio, report panel). When in doubt, copy
the tokens here verbatim — do **not** invent new hex, radii, or button shapes.

Live mockup: `mockup-design-system.html` (open in browser — nav-switchable, real tokens).

---

## 1. Color tokens

Brand scale `clay-*` is in `tailwind.config.ts` (50→950). Use the **named class** where Nuxt
UI honors it (`text-clay-600`, `bg-clay-500`), otherwise the explicit hex below. Never use
`gray-*` (legacy) — migrate to the neutrals here.

| Role | Token / hex | Use |
|------|-------------|-----|
| Primary | `#C2683F` (clay-500) | primary buttons, active nav, key accents |
| Primary hover | `#A8542F` (clay-600) | hover/pressed primary |
| Clay tint bg | `#F3E7DF` | selected pill, soft highlight |
| Feature bg | `#F6EFEA` | feature/hero card background |
| Feature border | `#E8C9B5` (clay-200) | warm border on highlighted cards |
| Page bg | `#FBFAF6` | app canvas behind cards |
| Card bg | `#FFFFFF` | standard cards/panels |
| Soft inner bg | `#F4F1EA` | nested panel, icon chip background |
| Border / divider | `#E7E5DD` | **the** standard border everywhere |
| Text strong | `#1f2328` | headings, primary text |
| Text body | `#6b6b6b` | body, subtitles |
| Text muted | `#9a958c` | hints, meta, captions |
| Success | `#3f9e6a` / bg `#eef6f0` / border `#d7ebde` | trained/enabled/approved status |
| Danger | `red-600` text / `red-50` bg | errors, destructive |

Rule: **clay = brand/action**, **green = status only**, **red = error only**. No raw blue
except chart series.

---

## 2. Typography

- Headings family = **serif**: `font-family: ui-serif, Georgia, 'Times New Roman', serif`.
  (Tier-2: hoist to `tailwind.config.ts` `fontFamily.serif` so `font-serif` replaces inline style.)
- Body family = default sans (Nuxt UI).

| Element | Class | Family |
|---------|-------|--------|
| Page title (H1) | `text-2xl font-semibold tracking-tight text-[#1f2328]` | serif |
| Section title (H2) | `text-[15px] font-semibold text-[#1f2328]` | serif |
| Sub-section / card title | `text-sm font-medium text-[#1f2328]` | sans |
| Body | `text-sm text-[#6b6b6b]` | sans |
| Muted / meta | `text-xs text-[#9a958c]` | sans |
| Badge / pill label | `text-[11px] font-medium` | sans |

Body base = **14px (`text-sm`)** — this app runs `text-sm` at the page root. Never go below
`text-xs` (12px) for readable text.

---

## 3. Buttons — exactly 3 variants

Kill the other 4. Every button is one of these.

```html
<!-- PRIMARY -->
<button class="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl
               bg-[#C2683F] text-white hover:bg-[#A8542F] transition-colors cursor-pointer">

<!-- SECONDARY (outline) -->
<button class="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg
               border border-[#E7E5DD] text-[#1f2328] bg-white hover:bg-[#F4F1EA]
               transition-colors cursor-pointer">

<!-- GHOST / ADD (dashed) -->
<button class="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg
               border border-dashed border-[#E7E5DD] text-[#C2683F]
               hover:border-[#C2683F] hover:bg-[#F3E7DF] transition-colors cursor-pointer">
```

- Radius: **primary = `rounded-xl`**, secondary/ghost = `rounded-lg`. No `rounded`/`rounded-md`/`rounded-full` for buttons (pills excepted).
- Disabled: `opacity-65 cursor-default`, no hover.
- Always `cursor-pointer` + `transition-colors` (150–300ms).
- `UButton` usage: if used, `color="primary"` (resolves clay) — don't mix `color="orange"`.

---

## 4. Cards / panels — 3 types

```html
<!-- INTERACTIVE card -->
<div class="rounded-2xl border border-[#E7E5DD] bg-white p-4 hover:shadow-md
            hover:-translate-y-0.5 transition-all cursor-pointer">

<!-- FEATURE / hero card -->
<div class="rounded-2xl border border-[#E8C9B5] bg-[#F6EFEA] p-4">

<!-- INFO box (status/alert) -->
<div class="rounded-lg border border-[#d7ebde] bg-[#eef6f0] px-3 py-1.5 text-sm">
```

- Card radius = `rounded-2xl`. Info/alert = `rounded-lg`. Inputs = `rounded-lg`.
- Static cards: no shadow. Interactive: `hover:shadow-md hover:-translate-y-0.5` only.
- Icon chip inside card: `w-11 h-11 rounded-xl bg-[#F4F1EA] border border-[#E7E5DD] flex items-center justify-center`.

---

## 5. Page shell & spacing

```html
<div class="flex justify-center px-4 md:px-6 text-sm bg-[#FBFAF6] min-h-full">
  <div class="w-full max-w-7xl py-2">
    <!-- HEADER (mandatory on every list/settings page) -->
    <div class="flex items-start justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight text-[#1f2328]"
            style="font-family: ui-serif, Georgia, 'Times New Roman', serif">Title</h1>
        <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">Subtitle.</p>
      </div>
      <button class="…PRIMARY…">+ Action</button>
    </div>
    <!-- content -->
  </div>
</div>
```

- Container: `max-w-7xl`, padding `px-4 md:px-6`, content `py-2`.
- **Settings pages use the SAME header** (serif H1) — no more `text-sm` settings titles.
- Card grid: `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6`.
- Section gap `gap-4`, intra-section `gap-3`, tight `gap-2`.

---

## 6. Empty / loading states

```html
<!-- EMPTY -->
<div class="text-center py-14 px-6 bg-white border border-[#E7E5DD] rounded-2xl">
  <div class="w-11 h-11 rounded-xl bg-[#F4F1EA] border border-[#E7E5DD] mx-auto
              flex items-center justify-center mb-3"><!-- icon --></div>
  <p class="text-sm font-medium text-[#1f2328]"
     style="font-family: ui-serif, Georgia, serif">Nothing here yet</p>
  <p class="text-xs text-[#9a958c] mt-1">Hint on what to do.</p>
</div>

<!-- LOADING: prefer skeleton over spinner for content areas -->
<div class="animate-pulse rounded-2xl border border-[#E7E5DD] bg-white p-4">
  <div class="h-3 w-1/3 bg-[#F4F1EA] rounded mb-3"></div>
  <div class="h-24 bg-[#F4F1EA] rounded"></div>
</div>
```

Spinner only for inline/button: `w-4 h-4 text-[#9a958c]`.

---

## 7. Icons

- **Always** `<UIcon name="i-heroicons-*" class="w-4 h-4" />`. Drop the legacy `<Icon name="heroicons:*">` colon form.
- Standard size `w-4 h-4`; hero/empty-state `w-6 h-6`. No emoji as icons.
- Icon-only buttons need `aria-label`.

---

## 8. Status pills

```html
<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium
             bg-[#eef6f0] text-[#3f9e6a] border border-[#d7ebde]">trained</span>   <!-- success -->
<span class="… bg-[#F3E7DF] text-[#A8542F] border border-[#E8C9B5]">AUTO</span>       <!-- clay/info -->
<span class="… bg-[#F4F1EA] text-[#9a958c] border border-[#E7E5DD]">draft</span>      <!-- neutral -->
```

---

## 9. Accessibility / polish checklist (pre-merge)

- [ ] `cursor-pointer` on every clickable element.
- [ ] Visible focus ring (`focus-visible:ring-2 focus-visible:ring-[#C2683F]`).
- [ ] Contrast ≥ 4.5:1 (body `#6b6b6b` on white = pass; never lighter for body text).
- [ ] Icon-only buttons have `aria-label`.
- [ ] `transition-colors`/`transition-all` 150–300ms; honor `prefers-reduced-motion`.
- [ ] No `gray-*`, no raw hex outside this table, no emoji icons.
- [ ] Responsive at 375 / 768 / 1024 / 1440.

---

## 10. Migration priority (from audit, 2026-06-23)

App is ~65% on-spec. To reach 100%:

**Tier 1 (cohesion):**
1. Settings pages → adopt serif H1 page header (currently `text-sm`). Files: `settings/general.vue`, `settings/identity-provider.vue`, `settings/ai_settings.vue`, `settings/features.vue`.
2. Collapse buttons to the 3 variants above. Worst offenders: `settings/identity-provider.vue`, `studios/index.vue`, `connectors.vue`, `skills.vue`.
3. Replace all `gray-*` with neutral hex. Files: `index.vue` (landing), `settings/identity-provider.vue`, `evals/index.vue`.

**Tier 2 (debt):** hoist serif to `tailwind.config.ts`; define `.ca-card` / `.ca-card-hover` / `.ca-btn-primary` component classes in a global css so pages stop repeating long class strings; enforce `px-4 md:px-6` on all roots.

**Tier 3 (polish):** normalize icon sizes to `w-4 h-4`; prefer skeletons over spinners.
