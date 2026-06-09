/**
 * Top-level error boundary.
 *
 * Catches any uncaught render error in the React tree below it
 * (including errors thrown inside a route, a data-fetching hook,
 * or a deep child component) and shows a recoverable fallback
 * instead of unmounting the entire app to a blank page.
 *
 * In production this is the last line of defense before the
 * browser's default crash UI. The boundary also reports to the
 * console (and the global `window.onerror` handler will pick it
 * up for any future telemetry hook).
 *
 * Usage (in `main.tsx`):
 *   <ErrorBoundary>
 *     <App />
 *   </ErrorBoundary>
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary] uncaught render error:", error, info.componentStack);
  }

  private handleReload = (): void => {
    // Reset state and remount the tree from scratch. Hard
    // `location.reload` is overkill — a state reset preserves
    // the user's in-memory navigation state and the QueryClient
    // cache.
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }
    return (
      <div
        role="alert"
        className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center"
      >
        <h1 className="text-2xl font-semibold">Something went wrong</h1>
        <p className="max-w-md text-sm text-muted-foreground">
          The page hit an unexpected error. You can try recovering without losing
          your session, or reload the whole app.
        </p>
        {this.state.error ? (
          <pre className="max-w-2xl overflow-auto rounded bg-muted p-3 text-left text-xs">
            {this.state.error.message}
          </pre>
        ) : null}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={this.handleReload}
            className="rounded border px-3 py-1 text-sm hover:bg-muted"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => window.location.assign("/")}
            className="rounded border px-3 py-1 text-sm hover:bg-muted"
          >
            Go home
          </button>
        </div>
      </div>
    );
  }
}
