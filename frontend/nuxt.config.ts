import { defineNuxtConfig } from "nuxt/config"

// Dev-proxy backend target. Default 8000 (upstream). For local dev against the
// running ca-app container, set DASH_BACKEND=127.0.0.1:3007. Prod build unaffected.
const DASH_BACKEND = process.env.DASH_BACKEND || '127.0.0.1:8000'
const BACKEND_HTTP = `http://${DASH_BACKEND}`
const BACKEND_WS = `ws://${DASH_BACKEND}`

export default defineNuxtConfig({
  devtools: { enabled: true },
  ssr: false,

  // Page route transition DISABLED. The global { name:'page', mode:'out-in' }
  // cross-fade stranded the entering page at opacity:0 on the FIRST SPA nav
  // (blank screen, worked on 2nd click) — same strand bug the report page had
  // to opt out of individually. Turning it off globally fixes every page at
  // once. (.ca-* entrance helpers in transitions.css still work.)
  app: {
    pageTransition: false,
    layoutTransition: false,
    head: {
      meta: [
        { name: 'theme-color', content: '#C2683F' },
        { name: 'apple-mobile-web-app-capable', content: 'yes' },
        { name: 'apple-mobile-web-app-status-bar-style', content: 'default' },
        { name: 'apple-mobile-web-app-title', content: 'CityAgent' },
      ],
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
        { rel: 'icon', type: 'image/png', sizes: '32x32', href: '/favicon-32.png' },
        { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' },
      ],
    },
  },

  modules: [
    "@nuxt/ui",
    "@sidebase/nuxt-auth",
    'nuxt-tiptap-editor',
    '@nuxtjs/mdc',
    '@nuxt-alt/proxy',
    'nuxt-echarts',
    'nuxt-monaco-editor',
    '@vite-pwa/nuxt'
  ],

  // Installable PWA (Add to Home Screen / desktop install). SPA shell precached;
  // API is NEVER cached (NetworkOnly) so data + auth stay live.
  pwa: {
    registerType: 'autoUpdate',
    manifest: {
      name: 'CityAgent Analytics',
      short_name: 'CityAgent',
      description: 'Agentic analytics — grounded studios, dashboards and insights over your data.',
      lang: 'en',
      display: 'standalone',
      start_url: '/',
      scope: '/',
      background_color: '#ffffff',
      theme_color: '#C2683F',
      icons: [
        { src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png' },
        { src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png' },
        { src: '/pwa-maskable-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
      ],
    },
    workbox: {
      navigateFallback: '/',
      globPatterns: ['**/*.{js,css,html,png,svg,ico,woff2}'],
      // Don't precache the giant editor/codegen blobs (Monaco TS worker ~9MB, babel ~3MB):
      // they're lazy-loaded only in the SQL/code editor and would bloat the install.
      globIgnores: [
        '**/nuxt-monaco-editor/**',
        '**/ts.worker-*.js',
        '**/libs/babel-standalone.min.js',
        '**/assets/cityagent-dash-logo.png',
      ],
      maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
      runtimeCaching: [
        // NEVER cache the API / auth / websocket — always hit network (no stale data, no token bugs).
        { urlPattern: ({ url }: any) => url.pathname.startsWith('/api') || url.pathname.startsWith('/ws'),
          handler: 'NetworkOnly' },
        // App-shell static assets: cache-first.
        { urlPattern: ({ url }: any) => url.pathname.startsWith('/_nuxt/'),
          handler: 'CacheFirst', options: { cacheName: 'nuxt-assets' } },
      ],
    },
    client: { installPrompt: true },
    devOptions: { enabled: false },
  },

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
