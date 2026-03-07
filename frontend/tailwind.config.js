/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          600: "#1565c0",
          700: "#0d47a1",
          800: "#0a2e6e",
        },
      },
    },
  },
  plugins: [],
};
