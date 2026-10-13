import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import { AppShell } from '@/components/shell/AppShell'
import { config } from '@/lib/config'
import './globals.css'

const geistSans = Geist({
  subsets: ['latin'],
  variable: '--font-geist-sans',
  display: 'swap',
})

const geistMono = Geist_Mono({
  subsets: ['latin'],
  variable: '--font-geist-mono',
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
    { media: '(prefers-color-scheme: dark)', color: '#0b0d1c' },
    { media: '(prefers-color-scheme: light)', color: '#f4f5fb' },
  ],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <head>
        {/* Apply the stored theme and motion preference before first paint, so
            there is no flash of the wrong palette or of unwanted animation.
            Kept inline and tiny on purpose. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var r=document.documentElement,t=localStorage.getItem('veriflow-theme'),m=localStorage.getItem('veriflow-motion');if(t&&t!=='system'){r.setAttribute('data-theme',t);}if(m==='reduce'){r.setAttribute('data-motion','reduce');}}catch(e){}})();`,
          }}
        />
      </head>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-ink"
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
