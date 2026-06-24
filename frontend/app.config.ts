// Nuxt UI v2 (installed: @nuxt/ui 2.22.3) global theme config.
//
// Without this file Nuxt UI falls back to its default `primary: 'green'` /
// generic blue accent, so bare <UButton>, <UTabs>, <UBadge>, <UToggle> etc.
// render in the wrong color. Here we point `primary` at the brand `clay`
// scale (registered in tailwind.config.ts under theme.extend.colors.clay).
//
// `gray: 'stone'` selects Tailwind's warm neutral so the surrounding grays
// harmonize with the warm terracotta brand instead of the cool default.
export default defineAppConfig({
  ui: {
    primary: 'clay',
    gray: 'stone',
  },
})
