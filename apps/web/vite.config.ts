import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [tailwindcss()],
  // The companion's verified iOS 15 phone cannot parse SDK class static blocks.
  build: { target: "safari15.4", outDir: "../../hirz/companion/ui", emptyOutDir: true },
  server: { host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:8000" } },
});
