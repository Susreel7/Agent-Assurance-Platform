import clsx from "clsx";
import { NavLink } from "react-router-dom";

export type SuiteSubNavItem = { to: string; label: string; end?: boolean };

const linkClass = ({ isActive }: { isActive: boolean }) =>
  clsx(
    "rounded-md px-3 py-1.5 text-sm transition-colors hover:no-underline",
    isActive ? "bg-rail-active font-medium text-rail-ink" : "text-rail-dim hover:text-rail-ink",
  );

export function SuiteSubNav({ items, ariaLabel }: { items: SuiteSubNavItem[]; ariaLabel: string }) {
  return (
    <nav aria-label={ariaLabel} className="mb-6 flex flex-wrap gap-1">
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
