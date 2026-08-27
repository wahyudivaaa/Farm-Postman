const API_KEY = localStorage.getItem("pm2api_key") || "postman-default-key";
const AUTH = { "Authorization": "Bearer " + API_KEY };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { ...AUTH, ...(opts.headers || {}) } });
  if (path.startsWith("/api/") && r.status === 401) { toast("Invalid API key", "err"); }
  return r.json();
}

function toast(msg, type = "ok") {
  let t = document.querySelector(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.style.borderColor = type === "err" ? "var(--danger)" : "var(--success)";
  t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2600);
}

const PAGES = { dashboard, accounts, keys, usage, models, settings };
const TITLES = { dashboard: "Dashboard", accounts: "Accounts", keys: "API Keys", usage: "Usage", models: "Models", settings: "Settings" };

document.querySelectorAll(".nav-item").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  go(b.dataset.page);
}));

async function refreshHealth() {
  try {
    const r = await fetch("/healthz");
    const ok = r.ok;
    document.getElementById("healthDot").className = "dot" + (ok ? " ok" : "");
    document.getElementById("healthText").textContent = ok ? "online" : "error";
  } catch { document.getElementById("healthDot").className = "dot"; document.getElementById("healthText").textContent = "offline"; }
}

// ---------- Dashboard ----------
function dashboard() {
  return `
  <div class="cards" id="dashCards"></div>
  <div class="panel"><h3>Recent calls</h3><div id="dashRecent">…</div></div>`;
}
async function loadDashboard() {
  const s = await api("/api/status");
  const accts = await api("/api/accounts");
  const u = await api("/api/usage");
  const ac = accts.accounts || [];
  const busy = ac.filter(x => x.status === "ok").length;
  document.getElementById("dashCards").innerHTML = `
    <div class="card"><div class="lbl">Accounts</div><div class="num">${ac.length}</div><div class="sub">${busy} ok</div></div>
    <div class="card"><div class="lbl">Total calls</div><div class="num">${u.calls || 0}</div><div class="sub">${(u.totalTokens||0).toLocaleString()} tokens</div></div>
    <div class="card"><div class="lbl">Credits</div><div class="num">${(u.totalTokens||0) > 0 ? ((u.totalTokens/1e3)|0) : 0}K</div><div class="sub">used</div></div>
    <div class="card"><div class="lbl">Service</div><div class="num" style="color:var(--success)">v2.0</div><div class="sub">${s.accounts} accounts loaded</div></div>`;
  const rows = (u.rows || []).slice(0, 8).map(r => `<tr><td>${r.ts}</td><td>${r.model}</td><td>${r.total_tokens}</td><td>${r.credits}</td></tr>`).join("");
  document.getElementById("dashRecent").innerHTML = `<table><tr><th>Time</th><th>Model</th><th>Tokens</th><th>Credits</th></tr>${rows || "<tr><td colspan=4>No calls yet</td></tr>"}</table>`;
}

// ---------- Accounts ----------
function accounts() {
  return `
  <div class="panel">
    <h3>Add Postman account</h3>
    <div class="form-row">
      <input id="a_label" placeholder="label" value="acct">
      <input id="a_sid" placeholder="postman.sid token (required)" style="min-width:280px">
      <input id="a_sub" placeholder="workspace subdomain (we2epjvvel-8763866)">
      <input id="a_model" placeholder="default model (auto)">
    </div>
    <button class="btn" onclick="addAccount()">＋ Add</button>
  </div>
  <div class="panel"><h3>Accounts</h3><div id="acctList"><table id="acctTable"><tr><th>Label</th><th>Subdomain</th><th>Model</th><th>Status</th><th>Usage</th><th>Active</th><th></th></tr></table></div></div>`;
}
async function addAccount() {
  const b = { label: a_label.value, postman_sid: a_sid.value.trim(), workspace_subdomain: a_sub.value.trim(), model_key: a_model.value || "auto" };
  if (!b.postman_sid) return toast("postman.sid required", "err");
  const r = await api("/api/accounts", { method: "POST", body: JSON.stringify(b), headers: { "Content-Type": "application/json" } });
  if (r.ok) { toast("Account added"); loadAccounts(); } else toast(r.error, "err");
}
async function loadAccounts() {
  const d = await api("/api/accounts");
  const rows = (d.accounts || []).map(a => `
    <tr>
      <td>${a.label}</td><td>${a.workspace_subdomain}</td><td>${a.model_key}</td>
      <td><span class="badge ${a.status === 'ok' ? 'ok' : 'err'}">${a.status}</span></td>
      <td>${a.usage_used}/${a.usage_limit}</td>
      <td><input type="checkbox" ${a.active ? "checked" : ""} onchange="toggleAcct(${a.id}, this.checked)"></td>
      <td>
        <button class="btn secondary" onclick="testAcct(${a.id})">Test</button>
        <button class="btn secondary" onclick="delAcct(${a.id})" style="color:var(--danger)">✕</button>
      </td>
    </tr>`).join("");
  const t = document.querySelector("#acctTable") || document.getElementById("acctTable");
  if (t) t.innerHTML = "<tr><th>Label</th><th>Subdomain</th><th>Model</th><th>Status</th><th>Usage</th><th>Active</th><th></th></tr>" + rows;
}
async function toggleAcct(id, active) { await api("/api/account/active", { method: "POST", body: JSON.stringify({ id, active }), headers: { "Content-Type": "application/json" } }); }
async function testAcct(id) { await api("/api/account/test", { method: "POST", body: JSON.stringify({ id }), headers: { "Content-Type": "application/json" } }); toast("Tested"); loadAccounts(); setTimeout(loadAccounts, 1500); }
async function delAcct(id) { await api("/api/account", { method: "DELETE", body: JSON.stringify({ id }), headers: { "Content-Type": "application/json" } }); toast("Deleted"); loadAccounts(); }

// ---------- Keys ----------
function keys() {
  return `
  <div class="panel"><h3>API keys</h3><div id="keyList"></div><div class="form-row" style="margin-top:14px"><input id="k_label" placeholder="label"><button class="btn" onclick="addKey()">＋ Create key</button></div></div>`;
}
async function loadKeys() {
  const d = await api("/api/keys");
  document.getElementById("keyList").innerHTML = (d.keys || []).map(k => `<code>${k.key}</code> <span class="badge ${k.active ? "ok" : "warn"}">${k.active ? "active" : "off"}</span>`).join("<br>") || "no keys";
}
async function addKey() {
  const d = await api("/api/keys", { method: "POST", body: JSON.stringify({ label: k_label.value || "key" }), headers: { "Content-Type": "application/json" } });
  if (d.key) { toast("Key: " + d.key); loadKeys(); }
}

// ---------- Usage ----------
function usage() {
  return `
  <div class="cards" id="usageCards"></div>
  <div class="panel"><h3>By model</h3><div id="usageModels"></div></div>
  <div class="panel"><h3>History</h3><div id="usageHist"></div></div>`;
}
async function loadUsage() {
  const u = await api("/api/usage");
  const byModel = await api("/api/usage/models");
  document.getElementById("usageCards").innerHTML = `
    <div class="card"><div class="lbl">Calls</div><div class="num">${u.calls||0}</div></div>
    <div class="card"><div class="lbl">Tokens</div><div class="num">${(u.totalTokens||0).toLocaleString()}</div></div>`;
  document.getElementById("usageModels").innerHTML = `<table><tr><th>Model</th><th>Tokens</th><th>Calls</th></tr>${(byModel.rows||[]).map(r=>`<tr><td>${r.model}</td><td>${r.t}</td><td>${r.c}</td></tr>`).join("")}</table>`;
  document.getElementById("usageHist").innerHTML = `<table><tr><th>Time</th><th>Model</th><th>Tokens</th></tr>${(u.rows||[]).slice(0,20).map(r=>`<tr><td>${r.ts}</td><td>${r.model}</td><td>${r.total_tokens}</td></tr>`).join("")}</table>`;
}

// ---------- Models ----------
function models() {
  return `
  <div class="panel"><h3>Available models (OpenAI-compatible)</h3>
    <pre class="code" id="modelList">…</pre>
  </div>
  <div class="panel"><h3>Quick test</h3>
    <div class="form-row"><select id="t_model"><option value="claude-opus-4-8">claude-opus-4-8</option><option value="gpt-5.6-sol">gpt-5.6-sol</option><option value="claude-sonnet-4-6">claude-sonnet-4-6</option><option value="auto">auto</option></select>
    <input id="t_prompt" placeholder="prompt" value="Reply with OK" style="flex:1"><button class="btn" onclick="testChat()">Send</button></div>
    <pre class="code" id="chatOut"></pre>
  </div>`;
}
async function loadModels() {
  const d = await api("/v1/models");
  document.getElementById("modelList").textContent = JSON.stringify(d, null, 2);
}
async function testChat() {
  const out = document.getElementById("chatOut");
  out.textContent = "…";
  const r = await fetch("/v1/chat/completions", { method: "POST", headers: { ...AUTH, "Content-Type": "application/json" }, body: JSON.stringify({ model: t_model.value, messages: [{ role: "user", content: t_prompt.value }] }) });
  const d = await r.json();
  out.textContent = JSON.stringify(d, null, 2);
}

// ---------- Settings ----------
function settings() {
  return `<div class="panel"><h3>Settings</h3>
    <div class="form-row"><label>API key</label><input id="s_key" value="${API_KEY}" style="flex:1"><button class="btn" onclick="setKey()">Save</button></div>
    <div class="form-row" style="margin-top:16px"><button class="btn secondary" onclick="clearConvs()">Clear conversation state</button></div>
  </div>`;
}
function setKey() { localStorage.setItem("pm2api_key", s_key.value.trim()); location.reload(); }
async function clearConvs() { await api("/api/sessions", { method: "DELETE" }); toast("Cleared"); }

// routing — render template then load data
async function go(page) {
  document.getElementById("pageTitle").textContent = TITLES[page];
  document.getElementById("page").innerHTML = PAGES[page]();
  await load(page);
}
async function load(page) {
  refreshHealth();
  if (page === "dashboard") await loadDashboard();
  if (page === "accounts") await loadAccounts();
  if (page === "keys") await loadKeys();
  if (page === "usage") await loadUsage();
  if (page === "models") await loadModels();
}
window.go = go;
go("dashboard");
setInterval(refreshHealth, 15000);
setInterval(() => { const a = document.querySelector(".nav-item.active"); if (a && a.dataset.page === "dashboard") loadDashboard(); }, 20000);