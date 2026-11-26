/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Palette is unchanged from the original design.
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
      borderRadius: { "4xl": "2rem" },
      boxShadow: {
        card: "0 1px 2px rgba(20,35,61,.04), 0 8px 24px -12px rgba(20,35,61,.14)",
        lift: "0 2px 4px rgba(20,35,61,.04), 0 18px 40px -16px rgba(11,77,75,.28)",
        glow: "0 10px 30px -10px rgba(15,124,119,.55)",
        float: "0 24px 60px -20px rgba(14,27,48,.35)",
      },
      keyframes: {
        "fade-up": { "0%": { opacity: 0, transform: "translateY(14px)" }, "100%": { opacity: 1, transform: "translateY(0)" } },
        "fade-in": { "0%": { opacity: 0 }, "100%": { opacity: 1 } },
        float: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-10px)" } },
        "float-slow": { "0%,100%": { transform: "translateY(0) rotate(-2deg)" }, "50%": { transform: "translateY(-14px) rotate(1deg)" } },
        drift: { "0%": { transform: "translateX(0)" }, "100%": { transform: "translateX(-50%)" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
        "pulse-ring": { "0%": { transform: "scale(.9)", opacity: 0.7 }, "100%": { transform: "scale(2.2)", opacity: 0 } },
        "dash": { to: { strokeDashoffset: "-200" } },
      },
      animation: {
        "fade-up": "fade-up .6s cubic-bezier(.2,.7,.2,1) both",
        "fade-in": "fade-in .4s ease-out both",
        float: "float 6s ease-in-out infinite",
        "float-slow": "float-slow 9s ease-in-out infinite",
        drift: "drift 40s linear infinite",
        shimmer: "shimmer 2.4s linear infinite",
        "pulse-ring": "pulse-ring 2s ease-out infinite",
        dash: "dash 9s linear infinite",
      },
    },
  },
  plugins: [],
};
