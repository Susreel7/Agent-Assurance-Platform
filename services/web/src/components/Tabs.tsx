import clsx from "clsx";

export type TabItem = {
  id: string;
  label: string;
};

type TabsProps = {
  tabs: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
  ariaLabel: string;
};

export function Tabs({ tabs, activeId, onChange, ariaLabel }: TabsProps) {
  return (
    <div role="tablist" aria-label={ariaLabel} className="flex gap-1 border-b border-line-200">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === activeId}
          className={clsx(
            "px-3 py-2 text-sm -mb-px border-b-2",
            tab.id === activeId
              ? "border-info-fg text-ink-900 font-medium"
              : "border-transparent text-ink-600 hover:text-ink-900",
          )}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
