'use client'

import { Button, ErrorState, Panel } from '@/components/ui/primitives'

export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <Panel className="mt-8 p-4">
      <ErrorState
        error={{ code: 'client_error', message: error.message || 'Something went wrong rendering this page.' }}
      />
      <div className="mt-3">
        <Button variant="secondary" onClick={reset}>
          Try again
        </Button>
      </div>
    </Panel>
  )
}
