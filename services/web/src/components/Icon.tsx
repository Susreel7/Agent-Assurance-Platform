/**
 * The console's icons, as path data.
 *
 * An icon library would be a megabyte of dependency for the twenty glyphs this product
 * uses, all of which are the same two-pixel stroke on a 24-unit grid. Keeping them here
 * also keeps them honest: every icon in this file is used by a screen, because adding
 * one means editing this file, and an unused one is visible in the diff.
 *
 * Purely decorative by default — the label next to an icon is what a screen reader
 * announces. Pass `title` only when the icon is the *only* thing identifying a control.
 */

import type { SVGProps } from "react";

const PATHS = {
  home: "M3 10.5 12 3l9 7.5M5.5 9.5V20a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V9.5",
  agents: "M12 3 4 7v6c0 4.4 3.4 7.4 8 8 4.6-.6 8-3.6 8-8V7l-8-4ZM9.5 11.5h5M9.5 15h3",
  activity: "M3 12h4l2.5-7 4 14L16 12h5",
  cost: "M12 3v18M8 7.5h6a2.5 2.5 0 0 1 0 5H10a2.5 2.5 0 0 0 0 5h6",
  tools: "M14.5 4.5a4 4 0 0 0 5 5L21 8v3.5L12 20.5a2.5 2.5 0 0 1-3.5-3.5L17 8.5",
  mcp: "M8 3v4M16 3v4M5 7h14v5a7 7 0 0 1-14 0V7ZM12 19v2",
  changes: "M6 4v9m0 0a3 3 0 1 0 0 6 3 3 0 0 0 0-6Zm12 7V8a3 3 0 0 0-3-3h-3m0 0 3-3m-3 3 3 3m3 8a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  approvals: "M5 12.5 10 17.5 19 6.5M4 20h16",
  issues: "M12 8.5v4.5M12 16.5h.01M10.3 4.2 3 17a2 2 0 0 0 1.7 3h14.6a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z",
  clients: "M8.5 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3 20v-1.5A4.5 4.5 0 0 1 7.5 14h2A4.5 4.5 0 0 1 14 18.5V20M16 4.3a3 3 0 0 1 0 5.4M18 14.2a4.5 4.5 0 0 1 3 4.3V20",
  evidence: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5ZM14 3v5h5M9 13h6M9 17h4",
  graph: "M6 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM18 21a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM6 21a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM6 8v8M7.8 17 16.4 7.6M18 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  rules: "M4 5h16M4 12h10M4 19h7M18 15v6M15 18h6",
  sla: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3.5 2",
  contracts: "M7 3h7l5 5v13H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM14 3v5h5M9.5 14h6M9.5 17.5h3",

  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM20 20l-4.2-4.2",
  close: "M6 6l12 12M18 6 6 18",
  chevronRight: "m9 5 7 7-7 7",
  chevronDown: "m5 9 7 7 7-7",
  arrowUp: "M12 19V5m0 0-6 6m6-6 6 6",
  arrowDown: "M12 5v14m0 0 6-6m-6 6-6-6",
  arrowRight: "M5 12h14m0 0-6-6m6 6-6 6",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",

  check: "m5 12.5 4.5 4.5L19 7.5",
  alert: "M12 8v5M12 16.5h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7.5V12l3 1.8",
  spark: "M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2Z",
  refresh: "M20 11A8 8 0 0 0 6.3 6.3L4 8.5M4 5v3.5h3.5M4 13a8 8 0 0 0 13.7 4.7L20 15.5M20 19v-3.5h-3.5",
  filter: "M4 5h16l-6.2 7.3V19l-3.6 2v-8.7L4 5Z",
  download: "M12 4v10m0 0 4-4m-4 4-4-4M5 18.5h14",
  layers: "m12 3 9 4.5-9 4.5-9-4.5L12 3ZM3 12.5 12 17l9-4.5M3 17 12 21.5 21 17",
  pulse: "M4 12h3.5L10 6.5l3.5 11L16 12h4",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4.5 20.5a7.5 7.5 0 0 1 15 0",
  building: "M4 21V6a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v15M14 10h5a1 1 0 0 1 1 1v10M4 21h17M7.5 9h3M7.5 13h3M7.5 17h3",
  bell: "M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2a2 2 0 0 1-.6 1.4L4 17h5M9.5 17a2.5 2.5 0 0 0 5 0",
  settings: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3 1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1Z",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM9.5 9.5a2.5 2.5 0 0 1 4.5 1.5c0 2-2.5 2-2.5 4M12 17h.01",
  calendar: "M8 3v3M16 3v3M4 9h16M6 5h12a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z",
  more: "M6 12h.01M12 12h.01M18 12h.01",

  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z",
  monitor: "M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1ZM9 20h6M12 16v4",
  key: "M15.5 3a5.5 5.5 0 0 0-5.2 7.3L3 17.6V21h3.4l7.3-7.3A5.5 5.5 0 1 0 15.5 3ZM16 8h.01",
  shield: "M12 3 4.5 6v5.5c0 4.4 3.1 7.9 7.5 9.5 4.4-1.6 7.5-5.1 7.5-9.5V6L12 3Z",
  plug: "M9 3v5M15 3v5M7.5 8h9v3a4.5 4.5 0 0 1-9 0V8ZM12 15.5V21",
  ban: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM5.6 5.6l12.8 12.8",
  team: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM2.5 20v-1a4.5 4.5 0 0 1 4.5-4.5h4A4.5 4.5 0 0 1 15.5 19v1M16.5 4.4a3.5 3.5 0 0 1 0 6.2M18 14.6A4.5 4.5 0 0 1 21.5 19v1",
  fingerprint:
    "M12 4a8 8 0 0 0-8 8M20 12a8 8 0 0 0-8-8M12 8a4 4 0 0 0-4 4v2M16 12a4 4 0 0 0-4-4M12 12v8M8 17.5V20M16 15v5",
} as const;

export type IconName = keyof typeof PATHS;

type IconProps = Omit<SVGProps<SVGSVGElement>, "name"> & {
  name: IconName;
  size?: number;
  title?: string;
};

export function Icon({ name, size = 18, title, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      <path d={PATHS[name]} />
    </svg>
  );
}
