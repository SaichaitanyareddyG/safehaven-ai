import { Component, type ReactNode } from 'react'

import { reportError } from '@/lib/report-error'

/** A page that crashes shows this instead of a blank screen, and the admins
 *  are told (lib/report-error.ts). */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    reportError(error)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="flex min-h-dvh items-center justify-center bg-[#F3F7F8] p-6">
        <div className="max-w-sm rounded-2xl bg-white p-6 text-center shadow-[0_12px_40px_rgba(22,37,44,0.10)]" role="alert">
          <h1 className="text-xl font-semibold text-[#16252C]">Something went wrong</h1>
          <p className="mt-2 text-base text-[#53656E]">
            This page hit a problem. Our team has been told. Reloading usually fixes it.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 h-12 w-full rounded-xl bg-[#0F6383] text-base font-semibold text-white hover:bg-[#0B5068]"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}
