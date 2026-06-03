// Local dev server — runs the Vercel-style handlers without the Vercel CLI.
// Dependency-light (node:http only); run with: npm run dev
//   tsx --env-file=.env dev-server.ts
//
// It adapts node's (req,res) to the small slice of the @vercel/node surface the
// handlers use, injects a dev auth subject, and streams back a Response when a
// handler returns one (the @vercel/og share card).
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

const PORT = Number(process.env.PORT ?? 3000);
const IS_PROD = process.env.NODE_ENV === "production";

// pathname -> lazy handler import. Keys are "METHOD /path".
const routes: Record<string, () => Promise<{ default: Function }>> = {
  "GET /api/today": () => import("./api/today"),
  "GET /api/me": () => import("./api/me"),
  "POST /api/choice": () => import("./api/choice"),
  "GET /api/split": () => import("./api/split"),
  "GET /api/profile": () => import("./api/profile"),
  "GET /api/share-card": () => import("./api/share-card"),
  "POST /api/consent": () => import("./api/consent"),
  "POST /api/account/delete": () => import("./api/account/delete"),
  "GET /api/account/export": () => import("./api/account/export"),
  "POST /api/account/privacy": () => import("./api/account/privacy"),
  "POST /api/admin/import-story": () => import("./api/admin/import-story"),
  "GET /api/admin/coverage": () => import("./api/admin/coverage"),
  "GET /api/admin/stories": () => import("./api/admin/stories"),
  "GET /api/admin/story": () => import("./api/admin/story"),
  "PATCH /api/admin/story": () => import("./api/admin/story"),
};

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  if (chunks.length === 0) return undefined;
  const raw = Buffer.concat(chunks).toString("utf8");
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

// Minimal VercelResponse shim over the node ServerResponse.
function makeRes(nodeRes: ServerResponse) {
  const res = {
    status(code: number) {
      nodeRes.statusCode = code;
      return res;
    },
    setHeader(k: string, v: string) {
      nodeRes.setHeader(k, v);
      return res;
    },
    json(obj: unknown) {
      nodeRes.setHeader("content-type", "application/json");
      nodeRes.end(JSON.stringify(obj));
    },
    send(body: unknown) {
      nodeRes.end(body as any);
    },
    end() {
      nodeRes.end();
    },
  };
  return res;
}

const server = createServer(async (nodeReq, nodeRes) => {
  try {
    const url = new URL(nodeReq.url ?? "/", `http://localhost:${PORT}`);
    const key = `${nodeReq.method} ${url.pathname}`;
    const route = routes[key];

    if (!route) {
      nodeRes.statusCode = 404;
      nodeRes.end(JSON.stringify({ error: `no route for ${key}` }));
      return;
    }

    // query as a flat object (last value wins for repeats)
    const query: Record<string, string> = {};
    url.searchParams.forEach((v, k) => (query[k] = v));

    // dev auth: stand in for the auth middleware so the loop runs without JWTs
    const headers = { ...nodeReq.headers } as Record<string, any>;
    if (!IS_PROD && !headers["x-auth-subject"]) headers["x-auth-subject"] = "dev-user";

    const hasBody = nodeReq.method === "POST" || nodeReq.method === "PATCH";
    const body = hasBody ? await readBody(nodeReq) : undefined;
    const req = { method: nodeReq.method, url: nodeReq.url, headers, query, body };

    const mod = await route();
    const ret = await mod.default(req as any, makeRes(nodeRes) as any);

    // handlers that RETURN a Response (share-card via @vercel/og) — stream it
    if (ret instanceof Response) {
      nodeRes.statusCode = ret.status;
      ret.headers.forEach((v, k) => nodeRes.setHeader(k, v));
      const buf = Buffer.from(await ret.arrayBuffer());
      nodeRes.end(buf);
    }
  } catch (e: any) {
    if (!nodeRes.headersSent) nodeRes.statusCode = 500;
    nodeRes.end(JSON.stringify({ error: String(e?.message ?? e) }));
    console.error(e);
  }
});

server.listen(PORT, () => {
  console.log(`dev API on http://localhost:${PORT}  (dev auth: dev-user)`);
});
