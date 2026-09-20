import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /**
   * Change this to clear a caught error — the caller passes the current
   * route, so navigating away puts the app back in a working state instead
   * of leaving the message up while the URL changes underneath it.
   *
   * Deliberately a prop rather than a `key` on the boundary itself: a `key`
   * would throw away and rebuild the entire subtree on *every* navigation,
   * error or not, when all that's wanted is to drop one piece of state.
   */
  resetKey?: unknown;
}

interface State {
  error: Error | null;
  /** The `resetKey` the current error was caught under, so a later change to
      it can be recognised. */
  resetKey: unknown;
}

/**
 * Catches a render error and shows it, instead of letting React unmount the
 * whole app and leave a blank white page.
 *
 * A single bad value used to be enough: one malformed currency code stored on
 * one account made Intl throw while drawing a table, and the entire interface
 * -- sidebar, navigation, everything -- vanished, with no visible way back
 * and nothing on screen explaining why. Whatever the next such value turns
 * out to be, the rest of the app now stays usable and the error is readable.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  /**
   * Clears a caught error when `resetKey` changes. Derived during render
   * rather than in componentDidUpdate, which would have to setState and so
   * render the failed state once more before replacing it.
   */
  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.resetKey === state.resetKey) return null;
    return { error: null, resetKey: props.resetKey };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled render error:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="card p-6 border-loss/40 space-y-3">
        <p className="text-loss font-medium">Something went wrong while displaying this page.</p>
        <p className="text-muted text-sm">
          The rest of the app still works — use the menu to go somewhere else, or reload to try again.
        </p>
        <p className="font-mono text-xs text-muted break-words">{error.message}</p>
        <div className="flex gap-3">
          <button className="btn-primary text-sm" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
          <button className="btn-ghost text-sm" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    );
  }
}
