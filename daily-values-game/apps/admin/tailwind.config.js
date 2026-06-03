/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // axis palette — keep in sync with apps/web/tailwind.config.js
      colors: {
        care: "#ef4444",
        equality: "#f59e0b",
        proportionality: "#eab308",
        loyalty: "#22c55e",
        authority: "#3b82f6",
        purity: "#a855f7"
      }
    }
  },
  plugins: []
};
