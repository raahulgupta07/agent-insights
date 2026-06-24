import type { Config } from 'tailwindcss'

// Brand palette for CityAgent Analytics.
//
// Nuxt UI v2 resolves the `primary`/`gray` colors named in app.config.ts by
// looking them up in the *Tailwind* theme (`#tailwind-config/theme/colors`,
// see @nuxt/ui/dist/runtime/plugins/colors.js -> get(colors, appConfig.ui.primary)).
// A custom color therefore MUST be registered here under theme.extend.colors
// with the full 50-950 shade scale, otherwise Nuxt UI falls back to its
// default (green/blue) and logs "Primary color 'clay' not found".
//
// CLAY (terracotta) brand scale. 500 = #C2683F (main), 600 = #A8542F (hover/dark).
export default <Partial<Config>>{
  theme: {
    extend: {
      colors: {
        clay: {
          50: '#FBF6F2',
          100: '#F4E5DA',
          200: '#E8C9B5',
          300: '#DBAC8F',
          400: '#CF8A65',
          500: '#C2683F',
          600: '#A8542F',
          700: '#8B4427',
          800: '#6E3620',
          900: '#5A2D1B',
          950: '#331810',
        },
      },
    },
  },
}
