import type { Metadata } from 'next'
import { SettingsView } from '@/components/settings/SettingsView'

export const metadata: Metadata = {
  title: 'Settings',
  description: 'Display preferences for this browser and the live state of the deployment.',
}

export default function SettingsPage() {
  return <SettingsView />
}
