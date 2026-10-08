/** Build/runtime configuration, all from NEXT_PUBLIC_* environment variables. */

export const config = {
  apiBaseUrl: (process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, ''),
  productName: process.env.NEXT_PUBLIC_PRODUCT_NAME ?? 'Veriflow',
  apiKey: process.env.NEXT_PUBLIC_API_KEY ?? '',
  /** The WebGL liquid-glass accent is opt-in; see public/vendor/liquid-glass/README.md. */
  liquidGlass: (process.env.NEXT_PUBLIC_LIQUID_GLASS ?? 'off') === 'on',
} as const

export const DEFAULT_OBJECTIVE =
  'Analyze enterprise customers renewing within the next 90 days. Identify the five accounts ' +
  'at highest risk of churn, investigate the reasons behind each account, verify all important ' +
  'conclusions using evidence, and recommend retention actions.'
