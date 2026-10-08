/**
 * Side-effect CSS imports.
 *
 * Next's `next-env.d.ts` covers most setups, but TypeScript 6 wants an explicit
 * declaration for a side-effect-only import. Declared here rather than
 * suppressed at the import site.
 */
declare module '*.css'
