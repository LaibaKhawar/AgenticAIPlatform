/**
 * What Veriflow is built with.
 *
 * Every description states only what this codebase actually does with the
 * technology. Versions are never written here: they come from the installed
 * lockfile at build time, from the running services via
 * GET /api/v1/system/stack, or are honestly absent (dev tooling that is not
 * part of the running system).
 */

import type { ComponentType } from 'react'
import {
  SiCelery,
  SiDocker,
  SiEslint,
  SiFastapi,
  SiNextdotjs,
  SiOpentelemetry,
  SiPostgresql,
  SiPydantic,
  SiPytest,
  SiPython,
  SiReact,
  SiRedis,
  SiRuff,
  SiSqlalchemy,
  SiTailwindcss,
  SiTypescript,
} from 'react-icons/si'

export type StackLayer = 'frontend' | 'backend' | 'data' | 'ai' | 'tooling'

export const LAYERS: Array<{ id: StackLayer | 'all'; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'frontend', label: 'Frontend' },
  { id: 'backend', label: 'Backend' },
  { id: 'data', label: 'Data' },
  { id: 'ai', label: 'AI & tracing' },
  { id: 'tooling', label: 'Tooling' },
]

/** Where a version number comes from — shown on the card, never hidden. */
export type VersionSource =
  | { kind: 'build'; pkg: string } // resolved version in frontend/package-lock.json
  | { kind: 'library'; key: string; via?: string } // installed Python distribution, read live
  | { kind: 'service'; name: string } // asked of the running server
  | { kind: 'python' }
  | { kind: 'none'; note: string }

export interface StackEntry {
  id: string
  name: string
  layer: StackLayer
  /** Where it runs, shown in small caps (the snippet's "entities" line). */
  runsIn: string
  description: string
  tags: string[]
  version: VersionSource
  /** Simple Icons mark; absent when the project has no published logo. */
  Logo?: ComponentType<{ className?: string; size?: number; style?: React.CSSProperties }>
  /** Brand colour for the mark. Monogram tiles use it for their tint. */
  brand: string
  monogram?: string
}

export const STACK: StackEntry[] = [
  // ---------------------------------------------------------------- frontend
  {
    id: 'nextjs',
    name: 'Next.js',
    layer: 'frontend',
    runsIn: 'Frontend container',
    description:
      'App Router for every screen, with standalone output so the Docker image ships only the traced server and its runtime dependencies.',
    tags: ['Framework', 'Routing'],
    version: { kind: 'build', pkg: 'next' },
    Logo: SiNextdotjs,
    brand: '#000000',
  },
  {
    id: 'react',
    name: 'React',
    layer: 'frontend',
    runsIn: 'Browser',
    description:
      'Component model for the UI. Live pages poll the API through shared data hooks, and display preferences sync across components and tabs.',
    tags: ['UI', 'Hooks'],
    version: { kind: 'build', pkg: 'react' },
    Logo: SiReact,
    brand: '#61DAFB',
  },
  {
    id: 'typescript',
    name: 'TypeScript',
    layer: 'frontend',
    runsIn: 'Build time',
    description:
      'Strict mode throughout. Response types are hand-written to mirror the API schemas, with integration tests asserting the backend side of the contract.',
    tags: ['Types', 'Strict'],
    version: { kind: 'build', pkg: 'typescript' },
    Logo: SiTypescript,
    brand: '#3178C6',
  },
  {
    id: 'tailwind',
    name: 'Tailwind CSS',
    layer: 'frontend',
    runsIn: 'Build time',
    description:
      'Version 4 theme tokens carry the Pantone palette. Base and component rules live in CSS layers so utilities always win.',
    tags: ['Styling', 'Design tokens'],
    version: { kind: 'build', pkg: 'tailwindcss' },
    Logo: SiTailwindcss,
    brand: '#06B6D4',
  },
  {
    id: 'motion',
    name: 'Motion',
    layer: 'frontend',
    runsIn: 'Browser',
    description:
      'Shared-layout animation behind the sliding tab highlights, the morphing Display popover and this page’s marquee. The flow and page transitions are hand-written Canvas 2D, with no library.',
    tags: ['Animation', 'Layout'],
    version: { kind: 'build', pkg: 'motion' },
    brand: '#FFF312',
    monogram: 'M',
  },
  {
    id: 'recharts',
    name: 'Recharts',
    layer: 'frontend',
    runsIn: 'Browser · SVG',
    description:
      'Usage, ticket and evaluation charts. Every plotted chart has a table view, and the series colours are validated for contrast.',
    tags: ['Charts', 'Dataviz'],
    version: { kind: 'build', pkg: 'recharts' },
    brand: '#22B5BF',
    monogram: 'Rc',
  },

  // ----------------------------------------------------------------- backend
  {
    id: 'python',
    name: 'Python',
    layer: 'backend',
    runsIn: 'API · Workers',
    description:
      'The runtime for the API, the Celery workers and the orchestration engine. Every metric and risk score is computed here, deterministically.',
    tags: ['Runtime'],
    version: { kind: 'python' },
    Logo: SiPython,
    brand: '#3776AB',
  },
  {
    id: 'fastapi',
    name: 'FastAPI',
    layer: 'backend',
    runsIn: 'API container',
    description:
      'The REST API and its OpenAPI docs. Starting a run returns QUEUED immediately while workers do the actual work.',
    tags: ['API', 'OpenAPI'],
    version: { kind: 'library', key: 'fastapi' },
    Logo: SiFastapi,
    brand: '#009688',
  },
  {
    id: 'pydantic',
    name: 'Pydantic',
    layer: 'backend',
    runsIn: 'API · Workers',
    description:
      'Typed agent outputs and API schemas. Strict models reject malformed model output, which is retried with the validation error, never silently accepted.',
    tags: ['Validation', 'Structured output'],
    version: { kind: 'library', key: 'pydantic' },
    Logo: SiPydantic,
    brand: '#E92063',
  },
  {
    id: 'sqlalchemy',
    name: 'SQLAlchemy',
    layer: 'backend',
    runsIn: 'API · Workers',
    description:
      'Version 2 ORM behind the repositories. Task claiming uses conditional updates so two workers can never run the same task.',
    tags: ['ORM', 'Idempotency'],
    version: { kind: 'library', key: 'sqlalchemy' },
    Logo: SiSqlalchemy,
    brand: '#D71F00',
  },
  {
    id: 'alembic',
    name: 'Alembic',
    layer: 'backend',
    runsIn: 'Migrate job',
    description:
      'Schema migrations, run by a one-shot container before the API starts. Written by hand where autogenerate would drop the vector index.',
    tags: ['Migrations'],
    version: { kind: 'library', key: 'alembic' },
    brand: '#6BA81E',
    monogram: 'Al',
  },
  {
    id: 'celery',
    name: 'Celery',
    layer: 'backend',
    runsIn: 'Worker container',
    description:
      'Executes workflow tasks from the task graph. Retries are owned by the engine, not Celery, so every attempt is recorded.',
    tags: ['Queue', 'Workers'],
    version: { kind: 'library', key: 'celery' },
    Logo: SiCelery,
    brand: '#37814A',
  },

  // -------------------------------------------------------------------- data
  {
    id: 'postgresql',
    name: 'PostgreSQL',
    layer: 'data',
    runsIn: 'Database container',
    description:
      'The system of record: customers, runs, tasks, evidence, claims, approvals and the audit trail, all with real constraints.',
    tags: ['Database', 'Audit trail'],
    version: { kind: 'service', name: 'postgresql' },
    Logo: SiPostgresql,
    brand: '#4169E1',
  },
  {
    id: 'pgvector',
    name: 'pgvector',
    layer: 'data',
    runsIn: 'Database extension',
    description:
      'HNSW cosine search over document chunks. Customer-scoped queries use iterative scan, so a filter can never silently return nothing.',
    tags: ['Vector search', 'RAG'],
    version: { kind: 'service', name: 'pgvector' },
    brand: '#4169E1',
    monogram: 'pv',
  },
  {
    id: 'redis',
    name: 'Redis',
    layer: 'data',
    runsIn: 'Cache container',
    description: 'Message broker and result backend for the Celery workers.',
    tags: ['Broker'],
    version: { kind: 'service', name: 'redis' },
    Logo: SiRedis,
    brand: '#FF4438',
  },

  // ----------------------------------------------------------- AI & tracing
  {
    id: 'openai',
    name: 'OpenAI-compatible API',
    layer: 'ai',
    runsIn: 'API · Workers',
    description:
      'Chat completions with JSON-schema structured output, plus embeddings, called directly over HTTPS with httpx (no vendor SDK), so any OpenAI-compatible gateway works. It is used only when an API key is configured; otherwise the deterministic offline model runs.',
    tags: ['LLM', 'Embeddings', 'HTTP'],
    version: { kind: 'library', key: 'httpx', via: 'httpx' },
    brand: '#10A37F',
    monogram: 'AI',
  },
  {
    id: 'opentelemetry',
    name: 'OpenTelemetry',
    layer: 'ai',
    runsIn: 'API · Workers',
    description:
      'Spans around planning, tool calls, model calls, retrieval and verification, so a run can be traced end to end when tracing is enabled.',
    tags: ['Tracing', 'Observability'],
    version: { kind: 'library', key: 'opentelemetry' },
    Logo: SiOpentelemetry,
    brand: '#F5A800',
  },

  // ----------------------------------------------------------------- tooling
  {
    id: 'docker',
    name: 'Docker Compose',
    layer: 'tooling',
    runsIn: 'Host',
    description:
      'Six services: frontend, API, worker, PostgreSQL, Redis and a migrate job. Startup is ordered by health checks, not sleeps.',
    tags: ['Containers', 'Orchestration'],
    version: { kind: 'none', note: 'Runs the containers; not visible from inside them' },
    Logo: SiDocker,
    brand: '#2496ED',
  },
  {
    id: 'pytest',
    name: 'pytest',
    layer: 'tooling',
    runsIn: 'Development',
    description:
      'Unit, integration, agent and end-to-end suites. Integration tests run against real PostgreSQL and pgvector, never mocks of them.',
    tags: ['Testing'],
    version: { kind: 'none', note: 'Development tool; not installed in the running services' },
    Logo: SiPytest,
    brand: '#0A9EDC',
  },
  {
    id: 'ruff',
    name: 'Ruff',
    layer: 'tooling',
    runsIn: 'Development',
    description: 'Python linting, alongside mypy type checking of the whole backend.',
    tags: ['Lint'],
    version: { kind: 'none', note: 'Development tool; not installed in the running services' },
    Logo: SiRuff,
    brand: '#D7FF64',
  },
  {
    id: 'eslint',
    name: 'ESLint',
    layer: 'tooling',
    runsIn: 'Development',
    description: 'Frontend linting, run as an explicit step so a lint warning cannot silently fail a production build.',
    tags: ['Lint'],
    version: { kind: 'build', pkg: 'eslint' },
    Logo: SiEslint,
    brand: '#4B32C3',
  },
]

/** Frontend packages whose installed version the server page reads at build time. */
export const BUILD_PACKAGES = STACK.flatMap((entry) => (entry.version.kind === 'build' ? [entry.version.pkg] : []))
