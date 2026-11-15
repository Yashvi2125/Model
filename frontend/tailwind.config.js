/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sand: { 50: "#FBF8F2", 100: "#F6F1E7", 200: "#ECE4D3", 300: "#DDD1B9" },
        ink: { 950: "#0E1B30", 900: "#14233D", 700: "#33415C", 500: "#5B6880", 400: "#8791A5" },
        lagoon: { 50: "#E8F5F3", 100: "#CDE9E5", 200: "#9FD3CC", 500: "#14958F", 600: "#0F7C77", 700: "#0C625F", 800: "#0B4D4B" },
        sun: { 100: "#FCEFD2", 500: "#E9A23B", 700: "#9A6411" },
        coral: { 100: "#FBE3DC", 500: "#D9644A", 700: "#A23E27" },
      },
      fontFamily: {
        display: ['"Bricolage Grotesque Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ['"Figtree Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: { card: "0 1px 2px rgba(20,35,61,.05), 0 6px 18px -8px rgba(20,35,61,.12)" },
    },
  },
  plugins: [],
};
