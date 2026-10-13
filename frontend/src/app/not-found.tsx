import { FlowCanvas } from '@/components/flow/FlowCanvas'
import { ArrowRightIcon, FlowIcon, LinkButton, UsersIcon } from '@/components/ui/primitives'

export default function NotFound() {
  return (
    <section aria-labelledby="not-found-title" data-flow-origin className="hero-band mt-4 min-h-[460px]">
      <FlowCanvas className="absolute inset-0 opacity-60 md:opacity-100" labels={false} />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(52rem_24rem_at_0%_0%,rgb(30_34_66/0.82),rgb(30_34_66/0.5)_45%,transparent_72%)]"
      />

      <div className="relative z-1 max-w-2xl px-6 py-12 sm:px-10 sm:py-16">
        <p className="text-brand-hero font-mono text-[13px] font-semibold tracking-[0.2em]">ERROR 404</p>
        <h1
          id="not-found-title"
          className="mt-3 text-[34px] leading-[1.08] font-semibold tracking-[-0.03em] text-[#f2f3fa] sm:text-[40px]"
        >
          No evidence for this page.
        </h1>
        <p className="mt-4 max-w-[48ch] text-[14.5px] leading-relaxed text-[#c9cdea]">
          The address doesn&apos;t match any route in the application. It may have been mistyped, or it
          may point at a run or customer that no longer exists.
        </p>

        <div className="mt-7 flex flex-wrap gap-3">
          <LinkButton href="/" variant="brand" size="lg" icon={<ArrowRightIcon className="h-4 w-4" />}>
            Back to the dashboard
          </LinkButton>
          <LinkButton href="/runs" variant="onDark" size="lg" icon={<FlowIcon className="h-4 w-4" />}>
            Investigations
          </LinkButton>
          <LinkButton href="/customers" variant="onDark" size="lg" icon={<UsersIcon className="h-4 w-4" />}>
            Customers
          </LinkButton>
        </div>
      </div>
    </section>
  )
}
