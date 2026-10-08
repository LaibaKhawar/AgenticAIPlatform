import type { Metadata, Viewport } from 'next'
import { Inter } from 'next/font/google'
import { AppShell } from '@/components/shell/AppShell'
import { config } from '@/lib/config'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

export const metadata: Metadata = {
  title: {
    default: `${config.productName} — evidence-verified AI investigations`,
    template: `%s · ${config.productName}`,
  },
  description:
    'Enterprise AI investigation and agent-orchestration platform. Turns a business objective into a ' +
    'verified, evidence-backed report with human approval for sensitive actions.',
  robots: { index: false, follow: false },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: dark)', color: '#090c10' },
    { media: '(prefers-color-scheme: light)', color: '#f2f4f7' },
  ],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        {/* Apply the stored theme before first paint so there is no flash of
            the wrong palette. Kept inline and tiny on purpose. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('veriflow-theme');if(t&&t!=='system'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();`,
          }}
        />
      </head>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-4 focus:py-2 focus:text-[var(--accent-ink)]"
        >
          Skip to content
        </a>
        <AppShell>
          <div id="main">{children}</div>
        </AppShell>
      </body>
    </html>
  )
}
