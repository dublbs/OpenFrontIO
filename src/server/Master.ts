import cluster from "cluster";
import crypto from "crypto";
import express from "express";
import http from "http";
import path from "path";
import { fileURLToPath } from "url";
import { GameEnv } from "../core/configuration/Config";
import { logger } from "./Logger";
import { MapPlaylist } from "./MapPlaylist";
import { MasterLobbyService } from "./MasterLobbyService";
import { setNoStoreHeaders } from "./NoStoreHeaders";
import { renderAppShell } from "./RenderHtml";
import { ServerEnv } from "./ServerEnv";
import { applyStaticAssetCacheControl } from "./StaticAssetCache";

const playlist = new MapPlaylist();
let lobbyService: MasterLobbyService;

const app = express();
const server = http.createServer(app);

const log = logger.child({ comp: "m" });

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

app.use(express.json());

// Serve the shared app shell for the root document.
app.use(async (req, res, next) => {
  if (req.path === "/") {
    try {
      await renderAppShell(
        res,
        path.join(__dirname, "../../static/index.html"),
      );
    } catch (error) {
      log.error("Error rendering index.html:", error);
      res.status(500).send("Internal Server Error");
    }
  } else {
    next();
  }
});

app.use(
  express.static(path.join(__dirname, "../../static"), {
    maxAge: "1y", // Set max-age to 1 year for all static assets
    setHeaders: (res) => {
      applyStaticAssetCacheControl(
        res.setHeader.bind(res),
        res.req.originalUrl,
      );
    },
  }),
);

app.set("trust proxy", 3);

app.use("/api", (_req, res, next) => {
  setNoStoreHeaders(res);
  next();
});

// Mock auth endpoints for self-hosted deployment
function generateGuestJwt(reqOrigin: string): string {
  const header = btoa(JSON.stringify({ alg: "none", typ: "JWT" }));
  const audience = reqOrigin
    ? new URL(reqOrigin).hostname.split(".").slice(-2).join(".")
    : "localhost";
  const persistentId = crypto.randomUUID().replace(/-/g, "");
  const persistentIdB64 = Buffer.from(
    Uint8Array.from(persistentId.match(/.{2}/g)!.map((h) => parseInt(h, 16))),
  )
    .toString("base64url")
    .padEnd(22, "=");
  const now = Math.floor(Date.now() / 1000);
  const payload = btoa(
    JSON.stringify({
      jti: crypto.randomUUID(),
      sub: persistentIdB64,
      iat: now,
      iss: reqOrigin || "http://localhost:3000",
      aud: audience,
      exp: now + 86400,
    }),
  );
  return `${header}.${payload}.`;
}

app.post("/auth/refresh", (req, res) => {
  const origin = req.headers.origin || req.headers.referer?.replace(/\/$/, "");
  const jwt = generateGuestJwt(origin || "");
  res.json({ jwt, expiresIn: 86400 });
});

app.post("/auth/crazygames", (req, res) => {
  const origin = req.headers.origin || req.headers.referer?.replace(/\/$/, "");
  const jwt = generateGuestJwt(origin || "");
  res.json({ jwt, expiresIn: 86400 });
});

app.get("/users/@me", (_req, res) => {
  res.json({
    user: {},
    player: {
      publicId: "self-hosted",
      adfree: false,
      unlimitedRanked: false,
      canCreatePublicLobbies: false,
      flares: [],
      achievements: { singleplayerMap: [] },
      friends: [],
      subscription: null,
    },
  });
});

// Mock news and cosmetics endpoints
app.get("/news.json", (_req, res) => {
  res.json([]);
});

app.get("/cosmetics.json", (_req, res) => {
  res.json({
    hats: [],
    flags: [],
    trails: [],
    deathEffects: [],
    territories: [],
  });
});

function getWorkerPort(workerIndex: number): number {
  return 3001 + workerIndex;
}

function getRandomWorkerPort(): number {
  return getWorkerPort(Math.floor(Math.random() * ServerEnv.numWorkers()));
}

// Proxy HTTP requests to workers
function proxyToWorker(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  port: number,
  path: string,
) {
  const proxyReq = http.request(
    {
      hostname: "127.0.0.1",
      port,
      path,
      method: req.method,
      headers: {
        ...req.headers,
        host: `127.0.0.1:${port}`,
      },
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
      proxyRes.pipe(res);
    },
  );

  proxyReq.on("error", (err) => {
    log.error(`Proxy error to port ${port}: ${err.message}`);
    if (!res.headersSent) {
      res.writeHead(502);
      res.end("Worker unavailable");
    }
  });

  req.pipe(proxyReq);
}

// Proxy /api/create_game to a random worker
app.all("/api/create_game", (req, res) => {
  const port = getRandomWorkerPort();
  log.info(`Proxying /api/create_game to worker port ${port}`);
  proxyToWorker(req, res, port, req.url);
});

app.all("/api/adminbot/create_game", (req, res) => {
  const port = getRandomWorkerPort();
  proxyToWorker(req, res, port, req.url);
});

// Proxy /api/game/:id/listing to a random worker
app.all("/api/game/:id/listing", (req, res) => {
  const port = getRandomWorkerPort();
  proxyToWorker(req, res, port, req.url);
});

// Proxy any remaining /api/* to a random worker
app.all("/api/{*path}", (req, res) => {
  const port = getRandomWorkerPort();
  proxyToWorker(req, res, port, req.url);
});

// Proxy /wN/* HTTP requests to the correct worker
app.all("/w:workerIndex/{*path}", (req, res) => {
  const workerIndex = parseInt(req.params.workerIndex);
  const port = getWorkerPort(workerIndex);
  log.info(`Proxying HTTP ${req.url} -> port ${port}`);
  proxyToWorker(req, res, port, req.url);
});

// WebSocket upgrade handler — proxy /wN/ paths to the correct worker
server.on("upgrade", (req, socket, head) => {
  const url = req.url || "";
  const match = url.match(/^\/w(\d+)(\/.*)?$/);
  if (!match) {
    log.warn(`WebSocket upgrade for unknown path: ${url}`);
    socket.destroy();
    return;
  }

  const workerIndex = parseInt(match[1]);
  const workerPath = match[2] || "/";
  const port = getWorkerPort(workerIndex);

  log.info(`WebSocket upgrade: ${url} -> port ${port}`);

  const proxyReq = http.request({
    hostname: "127.0.0.1",
    port,
    path: workerPath,
    method: "GET",
    headers: {
      ...req.headers,
      host: `127.0.0.1:${port}`,
    },
  });

  proxyReq.on("upgrade", (proxyRes, proxySocket, proxyHead) => {
    // Build raw HTTP 101 response
    let headers = `HTTP/1.1 101 Switching Protocols\r\n`;
    for (let i = 0; i < proxyRes.rawHeaders.length; i += 2) {
      headers += `${proxyRes.rawHeaders[i]}: ${proxyRes.rawHeaders[i + 1]}\r\n`;
    }
    headers += "\r\n";

    socket.write(headers);

    if (proxyHead.length > 0) {
      socket.write(proxyHead);
    }

    proxySocket.pipe(socket);
    socket.pipe(proxySocket);

    proxySocket.on("error", () => socket.destroy());
    socket.on("error", () => proxySocket.destroy());
  });

  proxyReq.on("error", (err) => {
    log.error(`WebSocket proxy error to port ${port}: ${err.message}`);
    socket.destroy();
  });

  proxyReq.end();
});

// Start the master process
export async function startMaster() {
  if (!cluster.isPrimary) {
    throw new Error(
      "startMaster() should only be called in the primary process",
    );
  }

  log.info(`Primary ${process.pid} is running`);
  log.info(`Setting up ${ServerEnv.numWorkers()} workers...`);

  lobbyService = new MasterLobbyService(playlist, log);

  const INSTANCE_ID =
    ServerEnv.env() === GameEnv.Dev
      ? "DEV_ID"
      : crypto.randomBytes(4).toString("hex");
  process.env.INSTANCE_ID = INSTANCE_ID;

  log.info(`Instance ID: ${INSTANCE_ID}`);

  // Fork workers
  for (let i = 0; i < ServerEnv.numWorkers(); i++) {
    const worker = cluster.fork({
      WORKER_ID: i,
      INSTANCE_ID,
    });

    lobbyService.registerWorker(i, worker);
    log.info(`Started worker ${i} (PID: ${worker.process.pid})`);
  }

  // Handle worker crashes
  cluster.on("exit", (worker, code, signal) => {
    const workerId = (worker as any).process?.env?.WORKER_ID;
    if (workerId === undefined) {
      log.error(`worker crashed could not find id`);
      return;
    }

    const workerIdNum = parseInt(workerId);
    lobbyService.removeWorker(workerIdNum);

    log.warn(
      `Worker ${workerId} (PID: ${worker.process.pid}) died with code: ${code} and signal: ${signal}`,
    );
    log.info(`Restarting worker ${workerId}...`);

    // Restart the worker with the same ID
    const newWorker = cluster.fork({
      WORKER_ID: workerId,
      INSTANCE_ID,
    });

    lobbyService.registerWorker(workerIdNum, newWorker);
    log.info(
      `Restarted worker ${workerId} (New PID: ${newWorker.process.pid})`,
    );
  });

  const PORT = parseInt(process.env.PORT || "3000", 10);
  server.listen(PORT, () => {
    log.info(`Master HTTP server listening on port ${PORT}`);
  });
}

app.get("/api/health", (_req, res) => {
  const ready = lobbyService?.isHealthy() ?? false;
  if (ready) {
    res.json({ status: "ok" });
  } else {
    res.status(503).json({ status: "unavailable" });
  }
});

// SPA fallback route
app.get("/{*splat}", async function (_req, res) {
  try {
    const htmlPath = path.join(__dirname, "../../static/index.html");
    await renderAppShell(res, htmlPath);
  } catch (error) {
    log.error("Error rendering SPA fallback:", error);
    res.status(500).send("Internal Server Error");
  }
});
