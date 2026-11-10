import { lazy, Suspense } from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { QueuePage } from './QueuePage'
import { ReviewPage } from './ReviewPage'

// AG Grid is large; load it only when the guardian opens the Activity tab, so the sender's
// screens stay small and fast.
const ActivityPage = lazy(() => import('./ActivityPage').then((m) => ({ default: m.ActivityPage })))
// Same for AG Charts on the Insights tab.
const InsightsPage = lazy(() => import('./InsightsPage').then((m) => ({ default: m.InsightsPage })))

/** Guardian routes: #/guardian (queue), #/guardian/p/{id}, #/guardian/activity, #/guardian/insights. */
export function GuardianArea({ parts }: { parts: string[] }) {
  const [view = 'queue', id] = parts
  const queue = usePoll(() => api.listPayments({ queue: 'guardian' }), 3000, 'guardian-queue')
  const waiting = queue.data?.filter((p) => p.status === 'HELD').length ?? 0
  const tab = view === 'p' ? 'queue' : view

  return (
    <div className="stack">
      <nav className="tabs" aria-label="Guardian">
        <a href="#/guardian" aria-current={tab === 'queue' ? 'page' : undefined}>
          Waiting for you{waiting > 0 && <span className="count">{waiting}</span>}
        </a>
        <a href="#/guardian/activity" aria-current={tab === 'activity' ? 'page' : undefined}>
          Activity
        </a>
        <a href="#/guardian/insights" aria-current={tab === 'insights' ? 'page' : undefined}>
          Insights
        </a>
      </nav>
      {view === 'p' && id ? (
        <ReviewPage key={id} id={id} />
      ) : view === 'activity' ? (
        <Suspense fallback={<section className="card">Loading the activity table…</section>}>
          <ActivityPage />
        </Suspense>
      ) : view === 'insights' ? (
        <Suspense fallback={<section className="card">Loading insights…</section>}>
          <InsightsPage />
        </Suspense>
      ) : (
        <QueuePage payments={queue.data} error={queue.error} />
      )}
    </div>
  )
}
