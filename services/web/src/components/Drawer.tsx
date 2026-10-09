import clsx from "clsx";

type DrawerProps = {
  title: string;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  width?: number;
};

export function Drawer({ title, open, onClose, children, width = 360 }: DrawerProps) {
  if (!open) return null;
  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-40 bg-ink-900/20"
        aria-label="Close panel"
        onClick={onClose}
      />
      <aside
        className={clsx("fixed top-0 right-0 z-50 h-full bg-bg-panel shadow-hairline flex flex-col")}
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
      >
        <header className="flex items-center justify-between border-b border-line-200 px-4 py-3">
          <h2 id="drawer-title" className="text-sm font-semibold">
            {title}
          </h2>
          <button type="button" className="text-sm text-ink-600" onClick={onClose} aria-label="Close">
            Close
          </button>
        </header>
        <div className="flex-1 overflow-auto p-4 scrollbar-thin">{children}</div>
      </aside>
    </>
  );
}
