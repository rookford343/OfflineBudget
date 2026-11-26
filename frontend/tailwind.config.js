/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        income: "#22c55e",
        expense: "#ef4444",
        warning: "#f59e0b",
        projected: "#3b82f6",
        surface: "var(--c-surface)",
        card: "var(--c-card)",
        ink: "var(--c-ink)",
        muted: "var(--c-muted)",
        line: "var(--c-line)",
        bar: "var(--c-bar)",
        accent: "var(--c-accent)",
        "accent-strong": "var(--c-accent-strong)",
        warn: "var(--c-warn)",
        "warn-text": "var(--c-warn-text)",
        "warn-figure": "var(--c-warn-figure)",
        "warn-bg": "var(--c-warn-bg)",
        "warn-line": "var(--c-warn-line)",
        // TEMPORARY (2026-11-26 Dashboard redesign): indigo renders as teal until each page swaps indigo-* for the named colors. Follow-up: hard-coded indigo hexes in Spending.tsx, Forecast.tsx, NetWorth.tsx charts. Delete this alias when no indigo-* remains.
        indigo: {
          50: "#f0fdfa",
          100: "#ccfbf1",
          200: "#99f6e4",
          300: "#5eead4",
          400: "#2dd4bf",
          500: "#0d9488",
          600: "#0f766e",
          700: "#115e59",
          800: "#134e4a",
          900: "#0f3d3a",
          950: "#042f2e",
        },
      },
    },
  },
  plugins: [],
}

