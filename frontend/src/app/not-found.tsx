import { EmptyState, LinkButton, Panel, SearchIcon } from '@/components/ui/primitives'

export default function NotFound() {
  return (
    <Panel className="mt-8">
      <EmptyState
        icon={<SearchIcon />}
        title="Page not found"
        description="That route does not exist in this application."
        action={
          <LinkButton href="/" variant="primary" size="sm">
            Back to the dashboard
          </LinkButton>
        }
      />
    </Panel>
  )
}
