/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Open WebUI 風深色調
        ink: {
          900: "#0f0f0f",
          850: "#171717",
          800: "#1f1f1f",
          750: "#262626",
          700: "#2e2e2e",
          600: "#3a3a3a",
        },
      },
    },
  },
  plugins: [],
};
