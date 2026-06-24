# City Agent DASH — Design System

Single source of truth for UI/UX. Every page, component, and new feature follows this.
Goal: one coherent, professional, "world-best" analytics product — not 13 pages that each
look slightly different.

Reference mockup: [`cityagent-dash-mockup.html`](./cityagent-dash-mockup.html) — open in a
browser. It is the living spec: if code and mockup disagree, the mockup wins.

---

## 1. Brand decision

Keep the established **warm-editorial** identity: cream canvas + coral accent + serif page
titles. It is distinctive (most analytics tools are cold blue/grey), already shipped, and
reads as premium. We did **not** switch to a generic blue/amber dashboard palette.

Personality: *calm, editorial, confident.* Think a financial-times reading surface with a
warm studio accent — not a neon SaaS dashboard.

---

## 2. Design tokens

These are the ONLY values allowed. No ad-hoc hex. (Tailwind arbitrary values today; migrate
to named theme tokens later — names below are the target.)

### Color

| Token | Hex | Tailwind today | Use |
|-------|-----|----------------|-----|
| `canvas` | `#FBFAF6` | `bg-[#FBFAF6]` | page background (cream) |
| `surface` | `#FFFFFF` | `bg-white` | cards, panels, inputs |
| `surface-sunken` | `#F4F1EA` | `bg-[#F4F1EA]` | icon chips, wells, hover fills |
| `border` | `#E7E5DD` | `border-[#E7E5DD]` | all hairlines, card borders, dividers |
| `text` | `#1f2328` | `text-[#1f2328]` | primary text, headings |
| `text-muted` | `#6b6b6b` | `text-[#6b6b6b]` | body / subtitles |
| `text-faint` | `#9a958c` | `text-[#9a958c]` | captions, placeholder, meta |
| `accent` | `#C2683F` | `bg-[#C2683F]` | primary buttons, active state, links |
| `accent-hover` | `#A8542F` | `hover:bg-[#A8542F]` | accent hover |
| `accent-wash` | `#F3E7DF` | `bg-[#F3E7DF]` | accent badges, selected rows |
| `avatar` | `#5B6470` | `bg-[#5B6470]` | user avatar, neutral chips |

Status (use sparingly, only for real state): success `#3F7D5B` / wash `#E8F0EA` · warning
`#B57A2F` / wash `#F6EEDF` · danger `#B5453F` / wash `#F6E5E4`. Never use raw `red-500` etc.

Accent is decorative + interactive only. **Never** color long body text coral. Contrast:
`#1f2328` on cream = 13:1, `#6b6b6b` on cream = 5.6:1, white on `#C2683F` = 4.7:1 — all pass
WCAG AA.

### Typography

- **Page titles (h1):** serif, `ui-serif, Georgia, 'Times New Roman', serif`, `text-2xl
  font-semibold tracking-tight text-[#1f2328]`. The serif title is the brand signature —
  every top-level page has exactly one.
- **Section headings:** sans, `text-[11px] font-semibold uppercase tracking-wider
  text-[#9a958c]` (the "eyebrow") OR `text-sm font-semibold text-[#1f2328]`.
- **Body:** sans (system / Inter), `text-sm`, `leading-relaxed` for prose, muted color.
- **Meta/caption:** `text-xs text-[#9a958c]`.
- Body min 14px in app chrome; never below 12px. Line length capped `max-w-2xl` for prose.

### Radius / shadow / spacing

- Radius scale: inputs & buttons `rounded-xl` (12px) · cards `rounded-2xl` (16px) · chips/pills
  `rounded-full` · icon tiles `rounded-xl`. No `rounded-lg` mixing — pick from this scale.
- Shadow: flat by default (borders do the work). Elevation only for overlays: dropdown
  `shadow-xl`, modal `shadow-2xl`. No drop-shadows on resting cards.
- Spacing rhythm: page top pad `py-2` then `mb-6` under header; section gap `mb-8`; card pad
  `p-4`/`p-5`; grid gap `gap-4` (lists) / `gap-6` (dashboards).
- z-index scale: dropdown `z-40`, sticky nav `z-40`, modal backdrop `z-50`, nested modal `z-[60]`.

---

## 3. The canonical page shell (FIX THE DRIFT)

Audit found 3 different wrappers across 4 pages. **One wrapper from now on.** Extract to a
component `<PageShell>` (props: `title`, `subtitle`, `#actions` slot, `#default` slot):

```html
<!-- OUTER: cream canvas, centered, scrolls independently -->
<div class="flex justify-center px-4 md:px-6 text-sm bg-[#FBFAF6] min-h-full">
  <!-- INNER: capped width, consistent top padding -->
  <div class="w-full max-w-7xl py-2 text-[#1f2328]">

    <!-- HEADER: serif title + subtitle on the left, ONE primary action on the right -->
    <header class="flex items-start justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight"
            style="font-family: ui-serif, Georgia, 'Times New Roman', serif">Title</h1>
        <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">Subtitle.</p>
      </div>
      <button class="btn-primary shrink-0"><!-- + Primary action --></button>
    </header>

    <!-- TABS (optional) directly under header, ABOVE search -->
    <!-- SEARCH/FILTER row -->
    <!-- CONTENT: grid / table / cards -->
  </div>
</div>
```

Migrate `studios` and `dashboards` to this exact wrapper (drop `ps-2 md:ps-4 ps-0`, drop
`h-full`, use `px-4 md:px-6` + `min-h-full` + inner `py-2`). `knowledge` and `connectors`
already match — they are the reference.

Canonical order on every list page: **header → tabs → search → content**. Tabs use the
underline style (active = `border-[#C2683F] text-[#1f2328] font-medium`).

---

## 4. Components (one definition each)

Build these as real Vue components in `components/ui/` so a page never re-codes them.

### Buttons
- **Primary** (`btn-primary`): `inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm
  font-medium text-white bg-[#C2683F] hover:bg-[#A8542F] disabled:opacity-50
  disabled:cursor-not-allowed transition-colors cursor-pointer`. Leading icon `w-4 h-4`.
  Exactly ONE per page header.
- **Secondary** (`btn-secondary`): same box, `bg-white border border-[#E7E5DD] text-[#1f2328]
  hover:bg-[#F4F1EA]`.
- **Ghost** (`btn-ghost`): `text-[#6b6b6b] hover:bg-[#F4F1EA] hover:text-[#1f2328]`.
- **Danger:** `bg-white border border-[#E7E5DD] text-[#B5453F] hover:bg-[#F6E5E4]`.
- Min hit target 44×44 (pad small icon buttons to `w-9 h-9` min `w-8 h-8`). Async → disable +
  spinner, never let user double-fire.
- Decide `UButton` vs raw `<button>`: **standardize on raw `<button>` with these classes** for
  primary/secondary actions (UButton's color overrides fight the brand). Keep UButton only for
  dropdown/menu list items.

### Input / search
One search field everywhere:
```html
<div class="relative flex-1 max-w-xl">
  <input class="w-full ps-10 pe-4 py-2.5 bg-white border border-[#E7E5DD] rounded-xl
    text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none focus:ring-2
    focus:ring-[#C2683F]/30 focus:border-[#C2683F]" />
  <Icon name="magnifying-glass" class="absolute start-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9a958c]" />
</div>
```
Focus ring opacity is **`/30`** everywhere (kill the `/40` variant). Text inputs share the box
minus the leading icon.

### Card
`bg-white border border-[#E7E5DD] rounded-2xl p-5`. Hover (if clickable):
`hover:border-[#C2683F]/40 hover:shadow-sm transition-all cursor-pointer`. Title `text-sm
font-medium text-[#1f2328]`, meta `text-xs text-[#9a958c]`. Icon tile top-left: `w-11 h-11
rounded-xl bg-[#F4F1EA] border border-[#E7E5DD] text-[#C2683F] flex items-center justify-center`.

### Badge / pill
`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium`. Accent badge
`bg-[#F3E7DF] text-[#C2683F]`; neutral `bg-[#F4F1EA] text-[#6b6b6b]`; status uses status-wash.

### Empty state
Centered in a single card: icon tile → `text-sm font-medium text-[#1f2328]` line →
`text-xs text-[#9a958c] max-w-md` hint → one primary button. (Studios already nails this — copy it.)

### Loading
Inline: centered `Spinner` + muted label. Lists/grids: skeleton cards (reserve height to stop
layout jump), not a bare spinner. Respect `prefers-reduced-motion`.

### Tabs
Underline tabs under the header. Count badge after label: muted `text-xs`, or accent pill
(`bg-[#F3E7DF] text-[#C2683F]`) when it's an actionable count (e.g. review queue).

### Settings pages
Each settings tab is its OWN full page using the canonical shell (no left rail). Layout owns
the per-tab title+subtitle. Form rows: label `text-sm font-medium text-[#1f2328]` → control →
`text-xs text-[#9a958c]` help. Group width `md:w-2/3`. Section dividers `border-t
border-[#E7E5DD]`. Save = one primary button, bottom-left, with `:loading`.

---

## 5. UX rules (non-negotiable)

**Accessibility (CRITICAL)**
- Every icon-only button has `aria-label`. Every input has an associated `<label>` (or
  `aria-label`). Focus visible on all interactive elements (the `/30` ring). Tab order = visual
  order. Color is never the only signal (pair with icon/text). Contrast ≥ 4.5:1 (tokens above
  guarantee it).

**Interaction (CRITICAL)**
- `cursor-pointer` on everything clickable (cards included). Hover gives visible feedback
  (border/fill/color), never a layout-shifting scale. Primary action = click/tap, never
  hover-only. Touch targets ≥ 44px.

**Performance / layout (HIGH)**
- Reserve space for async content (skeletons) — no content jumping. Images: lazy + sized. No
  horizontal scroll at 375 / 768 / 1024 / 1440. Content never hides behind the sticky nav
  (`min-h-full` shell handles it).

**Animation (MEDIUM)**
- 150–300ms, `transition-colors`/`transition-all`, ease. Transform/opacity only. Honor
  `prefers-reduced-motion: reduce` → disable non-essential motion.

**Consistency (MEDIUM)**
- Same shell, same components, every page. No emojis as icons — Heroicons only, fixed `w-4 h-4`
  / `w-5 h-5`. One container width (`max-w-7xl`). Serif for h1 only.

---

## 6. Per-page application

| Page type | Shell | Notes |
|-----------|-------|-------|
| List (studios, dashboards, knowledge, connectors, queries, skills, evals) | canonical | header → tabs → search → card grid `gap-4`/`gap-6` |
| Dashboard view | canonical | KPI row (4 stat cards) → chart grid; data-dense, minimal padding |
| Settings tabs | canonical, layout-owned title | form rows `md:w-2/3`, one Save |
| Report / chat | full-bleed (no max-w cap) | composer bottom, message column `max-w-3xl` centered, trace de-boxed |
| Sign-in / auth | centered card on cream | serif wordmark, provider rows, one primary |

---

## 7. Pre-merge checklist

- [ ] Uses canonical `<PageShell>` wrapper (no bespoke `ps-2`/`h-full` variants)
- [ ] One serif h1, one primary action in header
- [ ] All colors from §2 tokens — zero stray hex
- [ ] Buttons/inputs/cards from §4 — nothing re-coded inline
- [ ] Focus ring `/30`, cursor-pointer on clickables, aria-labels on icon buttons
- [ ] Skeleton (not spinner) for grid/table load; no layout jump
- [ ] Empty + error + loading states all present
- [ ] Responsive 375/768/1024/1440, no horizontal scroll
- [ ] No emojis as icons; Heroicons only
- [ ] `prefers-reduced-motion` respected
</content>
</invoke>
