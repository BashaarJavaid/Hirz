import { build } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import { mkdir, rename, rm } from "node:fs/promises";

const destination = new URL("../../hirz/mcp/ui/", import.meta.url);
await rm(destination, { recursive: true, force: true });
await mkdir(destination, { recursive: true });
for (const card of ["plan-card", "approval-card", "verification-card", "doorbell-card", "scorecard"]) {
  await build({
    root: import.meta.dirname,
    plugins: [viteSingleFile()],
    define: { __CARD__: JSON.stringify(card) },
    build: { outDir: destination.pathname, emptyOutDir: false },
  });
  await rename(new URL("index.html", destination), new URL(`${card}.html`, destination));
}
