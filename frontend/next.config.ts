import path from 'node:path'
import type { NextConfig } from 'next'

const config: NextConfig = {
  // Standalone output keeps the production image small: Next copies only the
  // traced runtime dependencies instead of all of node_modules.
  output: 'standalone',
  // Pin the tracing root to this app. Without it, Next infers the workspace
  // root from the nearest lockfile, and a stray package-lock.json higher up
  // the tree silently nests server.js one directory deeper in the standalone
  // output than the Dockerfile and docs expect.
  outputFileTracingRoot: path.join(__dirname),
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: {
    // Lint is a separate, explicit `make lint` step so a lint warning cannot
    // silently become a failed production build.
    ignoreDuringBuilds: true,
  },
}

export default config
