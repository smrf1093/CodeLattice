// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://smrf1093.github.io",
  base: "/CodeLattice",
  output: "static",
  vite: {
    plugins: [tailwindcss()],
  },
});
