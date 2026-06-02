/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // The axis palette — also used by the server-rendered share card so the
      // colours match across the app and the shared PNG (§10: the legend matters).
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
