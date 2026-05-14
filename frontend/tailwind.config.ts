import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ["'JetBrains Mono'", "Consolas", "Monaco", "monospace"],
      },
      colors: {
        terminal: {
          bg:      "#09090b",   // zinc-950
          surface: "#18181b",   // zinc-900
          border:  "#27272a",   // zinc-800
          muted:   "#71717a",   // zinc-500
          text:    "#f4f4f5",   // zinc-100
        },
      },
    },
  },
  plugins: [],
};

export default config;
