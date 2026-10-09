/**
 * Theme control: three explicit states, not a two-state switch.
 *
 * A plain toggle cannot express "follow my machine", so someone whose laptop flips to dark
 * at sunset has to come back and flip the console too. The segmented control shows all
 * three choices and which one is in force, which is also the only way to tell "dark
 * because I chose it" from "dark because my OS is".
 */

import { useTheme, type ThemeChoice } from "@/lib/theme";
import { Icon, type IconName } from "./Icon";

const CHOICES: { value: ThemeChoice; icon: IconName; label: string }[] = [
  { value: "light", icon: "sun", label: "Light" },
  { value: "dark", icon: "moon", label: "Dark" },
  { value: "system", icon: "monitor", label: "Match system" },
];

export function ThemeToggle({ className }: { className?: string }) {
  const { choice, setChoice } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="Appearance"
      className={`flex items-center gap-0.5 rounded-pill border border-line-200 bg-bg-sunk p-0.5 ${className ?? ""}`}
    >
      {CHOICES.map((option) => {
        const active = choice === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={option.label}
            onClick={() => setChoice(option.value)}
            className={
              active
                ? "flex h-7 w-7 items-center justify-center rounded-pill bg-bg-panel text-ink-900 shadow-hairline"
                : "flex h-7 w-7 items-center justify-center rounded-pill text-ink-400 transition-colors hover:text-ink-700"
            }
          >
            {/* The label is the accessible name via `title`; the glyph itself is decoration. */}
            <Icon name={option.icon} size={15} />
            <span className="sr-only">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
