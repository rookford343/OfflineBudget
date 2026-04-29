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
      },
    },
  },
  plugins: [],
}

