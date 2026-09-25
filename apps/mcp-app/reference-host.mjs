// Build the pinned upstream renderer/bridge without changing their source files.
import { execFileSync } from "node:child_process";
import { readFile, mkdir, symlink } from "node:fs/promises";
import { createServer } from "node:http";
import { resolve } from "node:path";

const output = resolve("../../.tools/card-reference-host");
if (!process.argv.includes("--serve-only")) {
const { build } = await import("vite");
const { viteSingleFile } = await import("vite-plugin-singlefile");
const checkout = resolve(process.env.HIRZ_REFERENCE_HOST ?? "../../.tools/ext-apps-v2");
const commit = execFileSync("git", ["-C", checkout, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
if (commit !== "352f6ced4d80772e92b4e7a311854481a8d65b04") throw new Error("Reference host must be ext-apps v2.0.0");
if (execFileSync("git", ["-C", checkout, "diff", "--", "examples/basic-host/src"], { encoding: "utf8" }).trim()) throw new Error("Reference renderer must remain unchanged");
const root = resolve(checkout, "examples/basic-host");
try { await symlink(resolve("node_modules"), resolve(root, "node_modules"), "dir"); }
catch (error) { if (error.code !== "EEXIST") throw error; }
await mkdir(output, { recursive: true });
for (const input of ["index.html", "sandbox.html"]) await build({
  configFile: false, root, plugins: [viteSingleFile()],
  build: { outDir: output, emptyOutDir: false, rollupOptions: { input: resolve(root, input) } },
});
}
if (process.argv.includes("--serve") || process.argv.includes("--serve-only")) {
  for (const port of [8080, 8081]) createServer(async (request, response) => {
    const path = new URL(request.url, `http://localhost:${port}`).pathname;
    response.setHeader("Cache-Control", "no-store");
    if (port === 8080 && path === "/api/servers") {
      response.setHeader("Content-Type", "application/json");
      response.end(process.env.SERVERS ?? '["http://127.0.0.1:8082/mcp"]'); return;
    }
    if (path !== "/" && path !== "/index.html" && path !== "/sandbox.html") { response.writeHead(404).end(); return; }
    if (port === 8081) response.setHeader("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; frame-src 'self'; connect-src 'none'; base-uri 'none'; object-src 'none'");
    response.setHeader("Content-Type", "text/html");
    response.end(await readFile(resolve(output, port === 8081 ? "sandbox.html" : "index.html")));
  }).listen(port, "127.0.0.1");
}
