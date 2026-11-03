// Tiny static server for the browser tests: serves the repo root on 127.0.0.1.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".webm": "video/webm", ".mp4": "video/mp4" };

/** `logs` collects the bodies the pages POST to any `.../api/client-log` (answered 200 with a body, as the app does). */
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
    if (req.method === "GET" && rel.endsWith("/api/labels")) { // the labels map the app reads on every result (web/labels.js):
      res.writeHead(200, { "content-type": "application/json" }).end("{}"); // a harness has no labelled entries (TICKET-241 AC-2)
      return;
    }
    const file = path.resolve(ROOT, "." + rel);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404).end("not found");
      return;
    }
    const type = TYPES[path.extname(file)] || "application/octet-stream";
    const size = fs.statSync(file).size;
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || "");  // video seeks need Range, as the app serves it
    if (m && (m[1] || m[2])) {
      const start = m[1] ? Number(m[1]) : Math.max(0, size - Number(m[2]));
      const end = m[1] && m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
      res.writeHead(206, { "content-type": type, "accept-ranges": "bytes", "content-range": `bytes ${start}-${end}/${size}`, "content-length": end - start + 1 });
      fs.createReadStream(file, { start, end }).pipe(res);
      return;
    }
    res.writeHead(200, { "content-type": type, "accept-ranges": "bytes", "content-length": size });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port, logs })));
}
