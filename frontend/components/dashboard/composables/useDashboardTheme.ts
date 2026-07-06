import { computed, unref } from 'vue';
import { DEFAULT_THEME_NAME, themes, resolveDefaultThemeName } from '../themes/index';
import type { ThemeTokens } from '../themes/types';

// HYBRID_BRAND_PALETTE (Phase 4, default OFF): reactive module-level flag, fetched
// once. Until it resolves (and whenever the flag is off) it stays false, so the
// default-theme fallback is byte-identical to before.
const brandPaletteEnabled = useState<boolean>('hybrid_brand_palette', () => false);
let _brandFlagFetched = false;
function ensureBrandFlag() {
  if (_brandFlagFetched) return;
  _brandFlagFetched = true;
  try {
    useMyFetch<any[]>('/organization/hybrid-flags')
      .then(({ data }: any) => {
        try {
          const rows = (unref(data) as any[]) || [];
          const row = rows.find(
            (f: any) => f?.env_name === 'HYBRID_BRAND_PALETTE' || f?.key === 'BRAND_PALETTE'
          );
          brandPaletteEnabled.value = !!row?.effective;
        } catch (_e) { /* fail-soft: stay default */ }
      })
      .catch(() => { /* fail-soft */ });
  } catch (_e) { /* fail-soft */ }
}

export function useDashboardTheme(
  reportThemeName?: string | null | any,
  reportOverrides?: Record<string, any> | null | any,
  stepViewStyle?: Record<string, any> | null | any
) {
  ensureBrandFlag();
  const themeName = computed(() => {
    const name = String(unref(reportThemeName) || '').trim();
    if (name && themes[name]) return name;
    // No explicit report theme -> honor the brand-palette flag for the default.
    return resolveDefaultThemeName(brandPaletteEnabled.value);
  });

  const tokens = computed<ThemeTokens>(() => {
    const base = themes[themeName.value]?.tokens || themes[DEFAULT_THEME_NAME].tokens;
    // Shallow merge for now; deep-merge can be added when wiring
    const merged: any = { ...base };
    const ro = unref(reportOverrides) || {};
    if (ro && Object.keys(ro).length) {
      Object.assign(merged, ro);
    }
    const sv = unref(stepViewStyle) || {};
    if (sv && Object.keys(sv).length) {
      Object.assign(merged, sv);
    }
    return merged as ThemeTokens;
  });

  return { themeName, tokens };
}


