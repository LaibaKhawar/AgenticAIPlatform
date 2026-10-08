import type { NextConfig } from 'next'

const config: NextConfig = {
  // Standalone output keeps the production image small: Next copies only the
  // traced runtime dependencies instead of all of node_modules.
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: {
    // Lint is a separate, explicit `make lint` step so a lint warning cannot
    // silently become a failed production build.
    ignoreDuringBuilds: true,
  },
}

export default config
