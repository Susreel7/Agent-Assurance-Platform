/**
 * One failure, rendered.
 *
 * This is the leaf. It knows how to lay out a refusal and nothing about where the
 * refusal came from — `ReasonState` in `DataBoundary.tsx` turns an `ApiError` into these
 * props, and that is the call site every screen should reach for.
 *
 * It previously took a `message` and defaulted its title to "Something went wrong", so
 * a 403 from a permission check, a 404 from a dead URL and a 500 from a real bug were
 * indistinguishable, and all three offered a Try again button that could not work. It
 * now takes `reason` and `next`, because those are the two facts that decide what a
 * person can do about it. Both are optional so the handful of pre-F0 call sites that
 * have only a sentence still compile — but a reason is what makes the box useful, and a
 * screen that has one should pass it.
 */

type ErrorStateProps = {
  title?: string;
  message: string;
  /** The API's reason code. Shown with the request id so a screenshot is reportable. */
  reason?: string;
  /** What the person can do, as a label. Absent means there is nothing to offer. */
  next?: { label: string; onAction: () => void } | null;
  requestId?: string;
  onRetry?: () => void;
};

export function ErrorState({
  title = "Something went wrong",
  message,
  reason,
  next,
  requestId,
  onRetry,
}: ErrorStateProps) {
  // `next` wins when both are given: the server naming an action knows more than this
  // component's assumption that anything failed can be retried.
  const action = next ?? (onRetry ? { label: "Try again", onAction: onRetry } : null);
  const footer = [requestId ? `Reference ${requestId}` : null, reason]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="rounded-sm border border-line-200 bg-risk-bg px-4 py-6 text-center" role="alert">
      <p className="text-sm font-medium text-risk-fg">{title}</p>
      <p className="mt-1 text-sm text-ink-600">{message}</p>
      {action ? (
        <button
          type="button"
          className="mt-4 text-sm font-medium text-info-fg underline"
          onClick={action.onAction}
        >
          {action.label}
        </button>
      ) : null}
      {footer ? <p className="mt-3 font-mono text-[10px] text-ink-500">{footer}</p> : null}
    </div>
  );
}
