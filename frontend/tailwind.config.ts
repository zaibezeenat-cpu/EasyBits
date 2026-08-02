import type { Config } from "tailwindcss";
import tailwindAnimate from "tailwindcss-animate";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#FAFAFA",
        surface: "#FFFFFF",
        border: "#E5E5E5",
        textPrimary: "#171717",
        textSecondary: "#6B6B6B",
        accent: "#561491", // WoodMart Purple
        accentSoft: "#F7A800", // WoodMart Gold
        success: "#16A34A",
        warning: "#D97706",
        danger: "#DC2626",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [tailwindAnimate],
};
export default config;
