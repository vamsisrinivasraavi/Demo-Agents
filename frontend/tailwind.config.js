/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"DM Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
      colors: {
        brand: {
          50: "#eef4ff",
          100: "#d9e5ff",
          200: "#bbd2ff",
          300: "#8db5ff",
          400: "#588dff",
          500: "#3366ff",
          600: "#1a44f5",
          700: "#1333e1",
          800: "#162cb6",
          900: "#182b8f",
        },
        surface: {
          0: "#ffffff",
          50: "#f8f9fb",
          100: "#f1f3f6",
          200: "#e4e7ed",
          300: "#cdd2db",
          400: "#9ba3b3",
          500: "#6b7485",
          600: "#4a5262",
          700: "#353c4a",
          800: "#232830",
          900: "#141619",
        },
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.4s ease-out",
        "pulse-dot": "pulseDot 1.4s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseDot: {
          "0%, 80%, 100%": { opacity: "0.3", transform: "scale(0.8)" },
          "40%": { opacity: "1", transform: "scale(1)" },
        },
      },
    },
  },
  plugins: [],
};