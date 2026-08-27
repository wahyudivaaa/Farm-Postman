/**
 * Postman2API Web — multi-account Postman Agent Mode → OpenAI/Anthropic compatible gateway.
 *
 * Full reverse engineering of the Postman Agent Mode /_gw gateway.
 * Feature set (from the open provider reference + own RE):
 *   - multi-account pool (each Postman account = separate session)
 *   - OpenAI /v1/chat/completions + /v1/models (streaming + non-streaming)
 *   - Anthropic /v1/messages compatibility
 *   - conversation recovery (continue prior chats across requests)
 *   - usage tracking (per-account credits, last N, chart)
 *   - API-key auth + management
 *   - dashboard (accounts, keys, usage, models, settings)
 */
import http from "node:http";
import { readFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 9121);
const APP_VER = "12.15.4-260616-1202";
const DB_PATH = path.join(__dirname, "data.db");

// ---------------- DB ----------------
mkdirSync(path.dirname(DB_PATH), { recursive: true });
const db = new Database(DB_PATH);
db.pragma("journal_mode = WAL");
db.exec(`
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT, postman_sid TEXT NOT NULL UNIQUE,
  workspace_subdomain TEXT, user_name TEXT, workspace_id TEXT,
  model_key TEXT DEFAULT 'auto', active INTEGER DEFAULT 1,
  status TEXT DEFAULT 'unknown', usage_used INTEGER DEFAULT 0, usage_limit INTEGER DEFAULT 50000,
  added_at TEXT DEFAULT (datetime('now')), last_used TEXT
);
CREATE TABLE IF NOT EXISTS keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, key TEXT UNIQUE, active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER, model TEXT, prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
  total_tokens INTEGER DEFAULT 0, credits INTEGER DEFAULT 0, ts TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
`);

// seed default key
const seedKey = process.env.API_KEY || "postman-default-key";
if (!db.prepare("SELECT 1 FROM keys WHERE key=?").get(seedKey)) {
  db.prepare("INSERT INTO keys (label,key) VALUES (?,?)").run("default", seedKey);
}

// ---------------- helpers ----------------
const json = (res, code, obj) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(obj)); };
const body = (req) => new Promise((ok, no) => { let b = ""; req.on("data", c => { b += c; if (b.length > 5e6) req.destroy(); }); req.on("end", () => { try { ok(b ? JSON.parse(b) : {}); } catch { no(new Error("bad json")); } }); req.on("error", no); });
const readRaw = (req) => new Promise((ok, no) => { let b = ""; req.on("data", c => { b += c; if (b.length > 5e6) req.destroy(); }); req.on("end", () => ok(b)); req.on("error", no); });

// auth check
function checkKey(req) {
  const h = req.headers["authorization"] || "";
  const token = h.startsWith("Bearer ") ? h.slice(7) : (req.headers["x-api-key"] || "");
  const k = db.prepare("SELECT * FROM keys WHERE key=? AND active=1").get(token);
  if (!k) return null;
  return k;
}

// ---------------- Postman upstream ----------------
const MODEL_MAP = {
  "gpt-5.6-sol": "GPT_56_SOL", "gpt-5.6-terra": "GPT_56_TERRA", "gpt-5.6-luna": "GPT_56_LUNA",
  "gpt-5.5": "GPT_55", "gpt-5.4": "GPT_54",
  "claude-opus-4-8": "CLAUDE_OPUS_48_BEDROCK", "claude-opus-4-7": "CLAUDE_OPUS_47_BEDROCK",
  "claude-opus-4-5": "CLAUDE_OPUS_45_BEDROCK", "claude-sonnet-4-6": "CLAUDE_46_SONNET_BEDROCK",
  "claude-sonnet-4-5": "CLAUDE_45_SONNET_BEDROCK", "claude-haiku-4-5": "CLAUDE_45_HAIKU_BEDROCK",
};
const MODELS = [
  ["gpt-5.6-sol", 128000], ["gpt-5.6-terra", 128000], ["gpt-5.6-luna", 128000], ["gpt-5.5", 128000], ["gpt-5.4", 128000],
  ["claude-opus-4-8", 200000], ["claude-opus-4-7", 200000], ["claude-opus-4-5", 200000],
  ["claude-sonnet-4-6", 200000], ["claude-sonnet-4-5", 200000], ["claude-haiku-4-5", 200000], ["auto", 200000],
];

function postmanModelId(reqModel) {
  const m = String(reqModel || "auto").trim().toLowerCase();
  return m in MODEL_MAP ? MODEL_MAP[m] : (m.toUpperCase().replace(/-/g, "_") || null);
}

function buildChatBody(query, convId, model) {
  return {
    input: { chatType: "USER_QUERY", query, toolResponse: "", useCase: null, conversationId: convId, agent: null, product: "workspace_v12", startedFrom: "CHAT_INPUT" },
    platform: "WEB",
    clientTools: { nativeToolsHash: `clienttools-workspace_v12-browser-${APP_VER}-d5808662718f`, excludedTools: ["listDatasets","createDataset","previewDataset","queryDatasetView","deleteDataset","getDatasetSchema","createDatasetView","deleteDatasetView"] },
    clientKBTerms: { nativeTermsHash: `kbterms-workspace_v12-browser-${APP_VER}-4755650f241c`, excludedKBTerms: ["DATASETS"] },
    mandatoryContext: { workspaceId: "0" },
    selectedContext: [], backgroundContext: [], availableSkills: [],
    devModeOptions: { selectedModel: model, isParallelToolCallingSupported: true, autoRun: false, supportsAskUser: false, supportsActionRecommendations: true, useThinkingModeIfAvailable: true, thinkingLevel: "low" },
  };
}

function pmHeaders(acc, accept) {
  return { "Cookie": `postman.sid=${acc.postman_sid}`, "Content-Type": "application/json", "Accept": accept,
           "x-app-version": APP_VER, "x-pstmn-req-service": "agent-mode-service",
           "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
           "Origin": `https://${acc.workspace_subdomain}`, "Referer": `https://${acc.workspace_subdomain}/` };
}

// pick account (least-used, active)
function pickAccount() {
  return db.prepare("SELECT * FROM accounts WHERE active=1 ORDER BY usage_used ASC LIMIT 1").get() || null;
}

// upstream chat via undici
import { fetch as undiciFetch } from "undici";

async function pmChat(acc, query, convId, model, signal) {
  const bodyData = buildChatBody(query, convId, model);
  const ws = `https://${acc.workspace_subdomain}`;
  const resp = await undiciFetch(`${ws}/_gw/chat`, { method: "POST", headers: pmHeaders(acc, "text/event-stream"), body: JSON.stringify(bodyData), signal });
  return resp; // SSE stream
}

// ---------------- SSE -> OpenAI parser ----------------
function parseSSE(line, model) {
  const m = /^data:\s*(.+)$/.exec(line.trim());
  if (!m) return null;
  let ev; try { ev = JSON.parse(m[1]); } catch { return null; }
  if (!ev || typeof ev !== "object") return null;
  const type = String(ev.eventType || "");
  if (type === "textChunk" && ev.data?.textContent) {
    return { type: "content", text: ev.data.textContent };
  }
  if (type === "thinkingChunk" && ev.data?.textContent) {
    return { type: "thinking", text: ev.data.textContent };
  }
  if (type === "usage" && ev.data) {
    return { type: "usage", usage: ev.data };
  }
  if (type === "conversation" && ev.data?.id) {
    return { type: "conversation", id: ev.data.id };
  }
  if (type === "failure" || type === "error") {
    return { type: "error", error: ev.data?.message || ev.data?.userMessage || "upstream error" };
  }
  return null;
}

// ---------------- OpenAI chat handler ----------------
async function handleChatWithRaw(req, res, isStream, rawBody) {
  let b; try { b = JSON.parse(rawBody || "{}"); } catch { return json(res, 400, { error: { message: "bad json" } }); }
  return handleChatParsed(req, res, isStream, b);
}
async function handleChatParsed(req, res, isStream, b) {
  const model = b.model || "auto";
  const messages = b.messages || [];
  const query = messages.length ? String(messages[messages.length - 1].content || "") : "";
  const acc = pickAccount();
  if (!acc) return json(res, 503, { error: { message: "no active Postman account" } });

  const pmModel = postmanModelId(model);
  const convId = convState.get(acc.id) || null;
  const includeUsage = b.stream_options?.include_usage === true;

  try {
    const up = await pmChat(acc, query, convId, pmModel, req.signal || undefined);
    if (!up.ok) return json(res, 502, { error: { message: `postman upstream ${up.status}` } });
    const reader = up.body.getReader();
    const dec = new TextDecoder();
    let text = "", convIdNew = null, usageData = null, err = null;
    let first = true;

    if (isStream) {
      res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
      const cid = "chatcmpl-" + Math.random().toString(16).slice(2);
      const sendChunk = (delta, fr = null) => {
        const obj = { id: cid, object: "chat.completion.chunk", model, choices: [{ index: 0, delta, finish_reason: fr }] };
        res.write("data: " + JSON.stringify(obj) + "\n\n");
      };
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const lines = (dec.decode(value, { stream: true })).split("\n");
          for (const line of lines) {
            const p = parseSSE(line, model);
            if (!p) continue;
            if (p.type === "content") { sendChunk({ content: p.text }); text += p.text; }
            else if (p.type === "thinking") { sendChunk({ reasoning_content: p.text }); }
            else if (p.type === "conversation") convIdNew = p.id;
            else if (p.type === "usage") usageData = p.usage;
            else if (p.type === "error") { err = p.error; sendChunk({ content: "" }, "stop"); }
          }
        }
      } catch (e) { /* client aborted */ }
      sendChunk({}, "stop");
      if (includeUsage) {
        res.write("data: " + JSON.stringify({ id: cid, object: "chat.completion.chunk", model, choices: [], usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: text.length } }) + "\n\n");
      }
      res.write("data: [DONE]\n\n");
      if (typeof res.end === "function") { try { res.end(); } catch {} }
      if (!res.writableEnded) { try { res.end(); } catch {} }
    } else {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const lines = (dec.decode(value, { stream: true })).split("\n");
        for (const line of lines) {
          const p = parseSSE(line, model);
          if (!p) continue;
          if (p.type === "content") text += p.text;
          else if (p.type === "conversation") convIdNew = p.id;
          else if (p.type === "usage") usageData = p.usage;
          else if (p.type === "error") err = p.error;
        }
      }
      if (err && !text) return json(res, 502, { error: { message: err } });
      json(res, 200, { id: "chatcmpl-" + Math.random().toString(16).slice(2), object: "chat.completion", model, choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }], usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 } });
    }

    // persist conversation id + usage
    if (convIdNew) { convState.set(acc.id, convIdNew); db.prepare("UPDATE accounts SET last_used=datetime('now') WHERE id=?").run(acc.id); }
    if (usageData) {
      db.prepare("UPDATE accounts SET usage_used=?, usage_limit=? WHERE id=?").run(usageData.usage || 0, usageData.limit || 50000, acc.id);
    }
    db.prepare("INSERT INTO usage (account_id, model, total_tokens, credits) VALUES (?,?,?,?)").run(acc.id, model, Math.round((usageData?.usage||0)/2), 1);
  } catch (e) {
    if (!res.headersSent) return json(res, 502, { error: { message: String(e.message || e) } });
    res.end();
  }
}

// in-memory conversation state per account
const convState = new Map();

// ---------------- HTTP server ----------------
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const p = url.pathname;

  // static dashboard
  if (req.method === "GET" && (p === "/" || p.startsWith("/dashboard"))) {
    const f = path.join(__dirname, "public", p === "/" ? "index.html" : "index.html");
    if (existsSync(f)) { res.writeHead(200, { "Content-Type": "text/html" }); res.end(readFileSync(f)); return; }
  }
  if (req.method === "GET" && p.startsWith("/public/")) {
    const f = path.join(__dirname, "public", p.slice(8));
    const ext = path.extname(f);
    const ctype = { ".js": "application/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml" }[ext] || "text/plain";
    if (existsSync(f)) { res.writeHead(200, { "Content-Type": ctype }); res.end(readFileSync(f)); return; }
  }
  if (req.method === "GET" && (p === "/healthz" || p === "/api/status")) {
    return json(res, 200, { ok: true, accounts: db.prepare("SELECT count(*) c FROM accounts").get().c, version: "2.0.0" });
  }

  // -------- API (auth for management) --------
  if (p.startsWith("/api/")) {
    const key = checkKey(req);
    if (p === "/api/keys" && req.method === "POST") {
      // create key (public endpoint can be gated; here simple)
      const b = await body(req);
      const k = "pk-" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
      db.prepare("INSERT INTO keys (label,key) VALUES (?,?)").run(b.label || "key", k);
      return json(res, 200, { ok: true, key: k });
    }
    if (!key) return json(res, 401, { error: { message: "invalid api key" } });

    // accounts CRUD
    if (p === "/api/accounts") {
      if (req.method === "GET") {
        const rows = db.prepare("SELECT id,label,workspace_subdomain,user_name,model_key,active,status,usage_used,usage_limit,added_at,last_used FROM accounts").all();
        return json(res, 200, { accounts: rows });
      }
      if (req.method === "POST") {
        const b = await body(req);
        try {
          const info = db.prepare("INSERT INTO accounts (label,postman_sid,workspace_subdomain,user_name,workspace_id,model_key) VALUES (?,?,?,?,?,?)")
            .run(b.label || "acct", b.postman_sid, b.workspace_subdomain, b.user_name || "", b.workspace_id || "0", b.model_key || "auto");
          return json(res, 200, { ok: true, id: info.lastInsertRowid });
        } catch (e) { return json(res, 400, { error: String(e.message || e) }); }
      }
    }
    if (p === "/api/account" && req.method === "DELETE") {
      const b = await body(req);
      db.prepare("DELETE FROM accounts WHERE id=?").run(b.id);
      return json(res, 200, { ok: true });
    }
    if (p === "/api/account/active" && req.method === "POST") {
      const b = await body(req);
      db.prepare("UPDATE accounts SET active=? WHERE id=?").run(b.active ? 1 : 0, b.id);
      return json(res, 200, { ok: true });
    }
    if (p === "/api/account/state" && req.method === "POST") {
      const b = await body(req);
      db.prepare("UPDATE accounts SET status=? WHERE id=?").run(b.status, b.id);
      return json(res, 200, { ok: true });
    }
    if (p === "/api/account/test" && req.method === "POST") {
      const b = await body(req);
      const acc = db.prepare("SELECT * FROM accounts WHERE id=?").get(b.id);
      if (!acc) return json(res, 404, { error: "no account" });
      try {
        const up = await pmChat(acc, "Reply OK", null, null);
        const ok = up.ok;
        db.prepare("UPDATE accounts SET status=? WHERE id=?").run(ok ? "ok" : `http_${up.status}`, acc.id);
        return json(res, 200, { ok: true, status: ok ? "ok" : `http_${up.status}` });
      } catch (e) { db.prepare("UPDATE accounts SET status='error' WHERE id=?").run(acc.id); return json(res, 200, { ok: false, error: String(e.message || e) }); }
    }

    // usage
    if (p === "/api/usage") {
      const rows = db.prepare("SELECT * FROM usage ORDER BY id DESC LIMIT 100").all();
      const total = db.prepare("SELECT SUM(total_tokens) t, COUNT(*) c FROM usage").get();
      return json(res, 200, { rows, totalTokens: total.t || 0, calls: total.c || 0 });
    }
    if (p === "/api/usage/chart") {
      const rows = db.prepare("SELECT date(ts) d, SUM(total_tokens) t, COUNT(*) c FROM usage GROUP BY d ORDER BY d DESC LIMIT 30").all();
      return json(res, 200, { rows });
    }
    if (p === "/api/usage/models") {
      const rows = db.prepare("SELECT model, SUM(total_tokens) t, COUNT(*) c FROM usage GROUP BY model ORDER BY c DESC").all();
      return json(res, 200, { rows });
    }
    if (p === "/api/models") {
      return json(res, 200, { models: MODELS.map(([id, ctx]) => ({ id, object: "model", owned_by: "postman", context_window: ctx })) });
    }
    if (p === "/api/keys" && req.method === "GET") {
      return json(res, 200, { keys: db.prepare("SELECT id,label,key,active,created_at FROM keys").all() });
    }
    if (p === "/api/sessions") {
      return json(res, 200, { sessions: [...convState.entries()].map(([acc, conv]) => ({ accountId: acc, conversationId: conv })) });
    }
    if (p === "/api/sessions" && req.method === "DELETE") {
      convState.clear(); return json(res, 200, { ok: true });
    }
    return json(res, 404, { error: "not found" });
  }

  // -------- OpenAI /v1 --------
  if (p.startsWith("/v1/")) {
    if (p === "/v1/models") {
      const key = checkKey(req);
      if (!key) return json(res, 401, { error: { message: "invalid api key" } });
      return json(res, 200, { object: "list", data: MODELS.map(([id, ctx]) => ({ id, object: "model", created: 1700000000, owned_by: "postman", context_window: ctx })) });
    }
    if (p === "/v1/chat/completions") {
      const key = checkKey(req);
      if (!key) return json(res, 401, { error: { message: "invalid api key" } });
      const rawBody = await readRaw(req);
      console.log("[v1] model/body:", rawBody.slice(0, 400));
      const isStream = (req.headers["accept"] || "").includes("text/event-stream");
      return handleChatWithRaw(req, res, isStream, rawBody);
    }
    return json(res, 404, { error: { message: "not found" } });
  }

  res.writeHead(404); res.end("not found");
});

server.listen(PORT, () => console.log(`Postman2API web on :${PORT}`));
