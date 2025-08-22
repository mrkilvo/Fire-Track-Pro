/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./firtrackpro/www/**/*.html",
    "./firtrackpro/www/**/*.js",
    "./firtrackpro/www/templates/**/*.html",
    "./firtrackpro/www/templates/**/*.js",
    "./firtrackpro/**/*.py",
    "./node_modules/flowbite/**/*.js",
  ],
  theme: {
    extend: {
      borderRadius: { xl: "0.85rem", "2xl": "1.25rem" },

      // >>> TOKENS: use in classes like bg-brand, text-ink, shadow-ft1, etc.
      colors: {
        brand: { DEFAULT: "#E11D48", 600: "#BE123C", 700: "#9F1239", weak: "#FDE7EE" },
        ink: "#0F172A",
        muted: "#475569",
        line: "#E2E8F0",
        panel: "#FFFFFF",
        panelweak: "#F8FAFC",
        ok: "#10B981", okweak: "#ECFDF5",
        warn: "#F59E0B", warnweak: "#FFFBEB",
        err: "#EF4444", errweak: "#FEF2F2",
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        ft1: "0 1px 2px rgba(2,6,23,.06)",
        ft2: "0 6px 16px rgba(2,6,23,.12)",
      },
    },
  },
  safelist: [
    { pattern: /(bg|text|border)-(slate|gray|green|rose|amber|purple|blue|indigo)-(50|100|200|300|500|700)/ },
    { pattern: /rounded-(lg|xl|2xl|full)/ },
    { pattern: /(bg|text)-(white|black)\/(40|50|60|70|80|90)/ },
    { pattern: /(backdrop-blur|shadow|ring|ring-offset)-(sm|md|lg|xl|2|4)/ },
    "prose", "prose-slate",
  ],
  corePlugins: {
    preflight: false,
  },
  plugins: [
    require("@tailwindcss/typography"),
    require("@tailwindcss/forms"),
    require("@tailwindcss/line-clamp"),
    require("flowbite/plugin"),
  ],
};
