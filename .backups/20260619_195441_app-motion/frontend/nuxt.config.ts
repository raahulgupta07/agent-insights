import { defineNuxtConfig } from "nuxt/config"

// Dev-proxy backend target. Default 8000 (upstream). For local dev against the
// running ca-app container, set BOW_BACKEND=127.0.0.1:3007. Prod build unaffected.
const BOW_BACKEND = process.env.BOW_BACKEND || '127.0.0.1:8000'
const BACKEND_HTTP = `http://${BOW_BACKEND}`
const BACKEND_WS = `ws://${BOW_BACKEND}`

export default defineNuxtConfig({
  devtools: { enabled: true },
  ssr: false,

  // Global page route transition (Claude-style soft cross-fade). Classes
  // live in assets/css/transitions.css (.page-*); reduced-motion disables it.
  app: {
    pageTransition: { name: 'page', mode: 'out-in' },
  },

  modules: [
    "@nuxt/ui",
    "@sidebase/nuxt-auth",
    'nuxt-tiptap-editor',
    '@nuxtjs/mdc',
    '@nuxt-alt/proxy',
    'nuxt-echarts',
    'nuxt-monaco-editor'
  ],

  echarts: {
    charts: [
      'BarChart',
      'LineChart',
      'PieChart',
      'ScatterChart',
      'EffectScatterChart',
      'BoxplotChart',
      'CandlestickChart',
      'GaugeChart',
      'FunnelChart',
      'HeatmapChart',
      'LinesChart',
      'MapChart',
      'ParallelChart',
      'RadarChart',
      'SunburstChart',
      'TreeChart',
      'TreemapChart'
    ],
    components: [
      'AriaComponent',
      'AxisPointerComponent',
      'BrushComponent',
      'CalendarComponent',
      'DataZoomComponent',
      'DataZoomInsideComponent',
      'DataZoomSliderComponent',
      'DatasetComponent',
      'GridComponent',
      'LegendComponent',
      'MarkLineComponent',
      'MarkPointComponent',
      'ParallelComponent',
      'RadarComponent'
    ]
  },

  tiptap: {
    prefix: 'Tiptap'
  },

  plugins: [
    '~/plugins/vue-draggable-resizable.client.js',
    '~/plugins/vue-flow.client.js',
    '~/plugins/i18n.ts',
  ],

  css: [
    '~/assets/css/rtl.css',
    '~/assets/css/transitions.css',
  ],

  imports: {
    dirs: ['ee/composables'],
    presets: [
      { from: 'vue-i18n', imports: ['useI18n'] },
    ],
  },

  icon: {
    localApiEndpoint: '/_nuxt_icon',
    serverBundle: {
      collections: ['heroicons'],
    },
    clientBundle: {
      scan: true,
    },
    fallbackToApi: false,
  },

  colorMode: {
    preference: 'light'
  },

  proxy: {
    debug: true,
    experimental: {
        listener: true
    },
    proxies: {
        '/ws/api': {
            target: BACKEND_WS,
            ws: true,
            changeOrigin: true,
            secure: false,
            rewrite: (path) => path,
            headers: {
                'Upgrade': 'websocket',
                'Connection': 'Upgrade'
            }
        },
        '/.well-known': {
            target: BACKEND_HTTP,
            changeOrigin: true,
            secure: false,
            rewrite: (path) => path
        },
        '/mcp': {
            target: BACKEND_HTTP,
            changeOrigin: true,
            secure: false,
            rewrite: (path) => `/api${path}`
        },
        '/swagger': {
            target: BACKEND_HTTP,
            changeOrigin: true,
            secure: false,
            rewrite: (path) => path
        },
        '/openapi.json': {
            target: BACKEND_HTTP,
            changeOrigin: true,
            secure: false,
            rewrite: (path) => path
        },
        '/excel': {
            target: BACKEND_HTTP,
            changeOrigin: true,
            secure: false,
            rewrite: (path) => `/api${path}`
        },
        '/api': {
            target: BACKEND_HTTP,
            changeOrigin: true,
            secure: false,
            rewrite: (path) => path,
            headers: {
                'Connection': 'keep-alive'
            }
        }
    }
},

  auth: {
    baseURL: '/api/', // Proxy now handled by NGINX
    provider: {
      type: 'local',
      pages: {
        login: '/users/sign-in',
        signup: '/users/sign-up'
      },
      endpoints: {
        signIn: { path: '/auth/jwt/login', method: 'post' },
        signOut: { path: '/auth/jwt/logout', method: 'post' },
        signUp: { path: '/auth/jwt/register', method: 'post' },
        getSession: { path: '/users/whoami', method: 'get' }
      },
      token: {
        signInResponseTokenPointer: '/access_token',
        type: 'Bearer',
        maxAgeInSeconds: 60 * 60 * 24 * 7, // 7 days
        cookie: {
          name: 'auth_token',
          options: {
            path: '/',
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'lax'
          }
        }
      },
      sessionDataType: { id: 'integer', name: 'string', email: 'string', is_superuser: 'boolean',
        organizations: '{ name: string, description: string | null, id: string, role: string, roles?: string[], permissions?: string[], resource_permissions?: Record<string, string[]>, is_enterprise?: boolean, usage_quota?: any }[]'
      },
    },
    session: {
      enableRefreshOnWindowFocus: true,
      enableRefreshPeriodically: false
    },
    globalAppMiddleware: {
      isEnabled: true
    },
    rewriteRedirects: true,
    fullPathRedirect: true
  },

  runtimeConfig: {
    public: {
      baseURL: '/api',
      wsURL: '/ws/api',
      environment: process.env.NODE_ENV,
    }
  },

  nitro: {
    experimental: {
      websocket: false
    }
  },

  // Allow ngrok domains to access the dev server (for Slack webhooks via frontend proxy)
  vite: {
    server: {
      allowedHosts: [
        '.ngrok-free.app'
      ]
    }
  },

  routeRules: {
    '/data': { redirect: '/agents' },
    '/data/**': { redirect: '/agents/**' },
  },

  compatibilityDate: '2025-08-03',
})
