/**
 * Legible brand marks in both themes.
 *
 * A single brand/ink mix cannot work for every logo: pure-black marks
 * (Next.js) disappear on the dark theme and pale ones (React's cyan,
 * Ruff's lime) on the light theme. So for each brand and theme we start at a
 * 62% brand mix and step toward the ink colour only as far as needed to reach
 * the target contrast against the brand-tinted tile: 3:1 for a logo (a
 * graphical object) and 4.5:1 for a lettered monogram (text).
 *
 * The surface values mirror the validated tokens in globals.css
 * (--ink and --surface-sunken for each theme).
 */

const THEMES = {
  dark: { ink: '#f2f3fa', sunken: '#121530' },
  light: { ink: '#151833', sunken: '#eef0f8' },
} as const

type Rgb = [number, number, number]

function parse(hex: string): Rgb {
  const value = hex.replace('#', '')
  return [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16)) as Rgb
}

function toHex(rgb: Rgb): string {
  return `#${rgb.map((channel) => Math.round(channel).toString(16).padStart(2, '0')).join('')}`
}

/** CSS `color-mix(in srgb, a weight, b)`: linear in encoded sRGB. */
function mix(a: string, b: string, weight: number): string {
  const ca = parse(a)
  const cb = parse(b)
  return toHex(ca.map((channel, index) => channel * weight + cb[index]! * (1 - weight)) as Rgb)
}

function luminance(hex: string): number {
  const [r, g, b] = parse(hex).map((channel) => {
    const c = channel / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }) as Rgb
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

export interface BrandPalette {
  markDark: string
  markLight: string
  tileDark: string
  tileLight: string
}

export function brandPalette(brand: string, isText: boolean): BrandPalette {
  const target = isText ? 4.5 : 3
  const solve = (theme: keyof typeof THEMES) => {
    const { ink, sunken } = THEMES[theme]
    const tile = mix(brand, sunken, 0.14)
    let weight = 0.62
    let mark = mix(brand, ink, weight)
    while (contrast(mark, tile) < target && weight > 0) {
      weight = Math.max(0, weight - 0.02)
      mark = mix(brand, ink, weight)
    }
    return { mark, tile }
  }
  const dark = solve('dark')
  const light = solve('light')
  return { markDark: dark.mark, markLight: light.mark, tileDark: dark.tile, tileLight: light.tile }
}
