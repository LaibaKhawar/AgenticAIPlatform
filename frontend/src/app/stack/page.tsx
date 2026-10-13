import { readFileSync } from 'node:fs'
import path from 'node:path'
import type { Metadata } from 'next'
import { BUILD_PACKAGES } from '@/components/stack/catalogue'
import { StackView } from '@/components/stack/StackView'

export const metadata: Metadata = {
  title: 'Stack',
  description: 'What Veriflow is built with, with versions read from the lockfile and the running services.',
}

/**
 * The exact frontend versions installed, read from the lockfile when the page
 * is built (it is static). `package.json` only holds ranges like `^15.5.0`;
 * the lockfile records what `npm ci` actually installed. If the lockfile is
 * unreadable the versions are reported as unknown, never invented.
 */
function installedVersions(): Record<string, string | null> {
  try {
    const lock = JSON.parse(readFileSync(path.join(process.cwd(), 'package-lock.json'), 'utf8')) as {
      packages?: Record<string, { version?: string }>
    }
    return Object.fromEntries(
      BUILD_PACKAGES.map((pkg) => [pkg, lock.packages?.[`node_modules/${pkg}`]?.version ?? null]),
    )
  } catch {
    return Object.fromEntries(BUILD_PACKAGES.map((pkg) => [pkg, null]))
  }
}

export default function StackPage() {
  return <StackView build={installedVersions()} />
}
