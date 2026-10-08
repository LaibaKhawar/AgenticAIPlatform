/** Liveness endpoint for the container health check. Touches nothing. */
export const dynamic = 'force-static'

export function GET() {
  return Response.json({ status: 'ok' })
}
