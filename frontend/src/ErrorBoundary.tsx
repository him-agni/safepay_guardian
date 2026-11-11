import { Component, type ErrorInfo, type ReactNode } from 'react'

/** Catches a crash while drawing a page, so the person sees a plain message instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('SafePay page error', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="app-main">
        <section className="card" role="alert">
          <h1>Something went wrong on this page</h1>
          <p className="lead">
            The page could not be shown. Reloading usually fixes it. This did not send, cancel or change any payment.
          </p>
          <div className="actions">
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload the page
            </button>
            <a className="btn btn-secondary" href="#/" onClick={() => this.setState({ failed: false })}>
              Go to the home page
            </a>
          </div>
        </section>
      </main>
    )
  }
}
