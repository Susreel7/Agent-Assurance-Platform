/** @type {import('tailwindcss').Config} */

// Every colour points at a custom property in styles/tokens.css rather than holding a
// hex value here. Tailwind's own palette is deliberately not extended with one-off
// shades: a colour that only exists at the call site is a colour nobody can change.
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "var(--ink-900)",
          700: "var(--ink-700)",
          600: "var(--ink-600)",
          400: "var(--ink-400)",
          300: "var(--ink-300)",
        },
        bg: {
          base: "var(--bg-base)",
          panel: "var(--bg-panel)",
          sunk: "var(--bg-sunk)",
          hover: "var(--bg-hover)",
        },
        rail: {
          bg: "var(--rail-bg)",
          panel: "var(--rail-panel)",
          line: "var(--rail-line)",
          ink: "var(--rail-ink)",
          dim: "var(--rail-ink-dim)",
          active: "var(--rail-active-bg)",
        },
        line: {
          200: "var(--line-200)",
          300: "var(--line-300)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          hover: "var(--accent-hover)",
          soft: "var(--accent-soft)",
          ink: "var(--accent-ink)",
        },
        ok: { fg: "var(--ok-fg)", bg: "var(--ok-bg)", solid: "var(--ok-solid)" },
        warn: { fg: "var(--warn-fg)", bg: "var(--warn-bg)", solid: "var(--warn-solid)" },
        risk: { fg: "var(--risk-fg)", bg: "var(--risk-bg)", solid: "var(--risk-solid)" },
        info: { fg: "var(--info-fg)", bg: "var(--info-bg)", solid: "var(--info-solid)" },
        mute: { fg: "var(--mute-fg)", bg: "var(--mute-bg)", solid: "var(--mute-solid)" },
        series: {
          1: "var(--series-1)",
          2: "var(--series-2)",
          3: "var(--series-3)",
          4: "var(--series-4)",
          5: "var(--series-5)",
          6: "var(--series-6)",
        },
        grid: "var(--grid)",
      },
      maxWidth: {
        content: "1440px",
      },
      width: {
        rail: "260px",
      },
      spacing: {
        topbar: "64px",
      },
      fontSize: {
        micro: ["11px", { lineHeight: "1.4", letterSpacing: "0.02em" }],
        table: ["13px", { lineHeight: "1.45" }],
        body: ["14px", { lineHeight: "1.55" }],
        lede: ["15px", { lineHeight: "1.6" }],
        stat: ["28px", { lineHeight: "1.1", letterSpacing: "-0.02em" }],
        display: ["26px", { lineHeight: "1.2", letterSpacing: "-0.02em" }],
        headline: ["32px", { lineHeight: "1.15", letterSpacing: "-0.025em" }],
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        hairline: "0 0 0 1px var(--line-200)",
        card: "var(--shadow-card)",
        pop: "var(--shadow-pop)",
      },
      borderRadius: {
        card: "14px",
        pill: "9999px",
      },
      keyframes: {
        "fade-rise": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "none" },
        },
      },
      animation: {
        "fade-rise": "fade-rise 160ms ease-out",
      },
    },
  },
  plugins: [],
};
