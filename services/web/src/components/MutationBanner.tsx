import clsx from "clsx";

type MutationBannerProps = {
  tone: "success" | "error";
  message: string;
  onDismiss?: () => void;
};

export function MutationBanner({ tone, message, onDismiss }: MutationBannerProps) {
  return (
    <div
      role="status"
      className={clsx(
        "mb-4 rounded-sm border px-4 py-3 text-sm",
        tone === "success" && "border-ok-fg/30 bg-ok-bg text-ok-fg",
        tone === "error" && "border-line-200 bg-risk-bg text-risk-fg",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p>{message}</p>
        {onDismiss ? (
          <button type="button" className="shrink-0 font-medium underline" onClick={onDismiss}>
            Dismiss
          </button>
        ) : null}
      </div>
    </div>
  );
}
