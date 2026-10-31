// Tiny static server for the browser tests: serves the repo root on 127.0.0.1.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

/** `logs` collects the bodies the pages POST to any `.../api/client-log` (answered 204, as the app does). */
export function serveRoot() {
  const logs = [];
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (req.method === "POST" && rel.endsWith("/api/client-log")) {
      const chunks = [];
      req.on("data", (c) => chunks.push(c));
      req.on("end", () => {
        try { logs.push(JSON.parse(Buffer.concat(chunks).toString("utf8"))); } catch { logs.push(null); }
        res.writeHead(204).end();
      });
      return;
    }
    const file = path.resolve(ROOT, "." + rel);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404).end("not found");
      return;
    }
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port, logs })));
}
