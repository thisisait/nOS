<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nOS profile builder</title>
<style>
  :root{--fg:#1d1d1f;--bg:#fff;--mute:#6e6e73;--line:#e5e5ea;--acc:#0a66c2;--ok:#1a7f37;--warn:#9a6700;--panel:#f5f5f7}
  @media(prefers-color-scheme:dark){:root{--fg:#f2f2f2;--bg:#111;--mute:#9a9a9f;--line:#2a2a2e;--acc:#6cb4ff;--ok:#3fb950;--warn:#d4a72c;--panel:#1a1a1e}}
  body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,Segoe UI,sans-serif}
  main{max-width:880px;margin:0 auto;padding:24px 16px 80px}
  h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:28px 0 8px}
  .sub{color:var(--mute);margin:0 0 18px}
  .steps{display:flex;gap:8px;margin:12px 0 20px;flex-wrap:wrap}
  .steps button{border:1px solid var(--line);background:none;color:var(--fg);padding:6px 12px;border-radius:999px;cursor:pointer}
  .steps button.on{border-color:var(--acc);color:var(--acc)}
  section{display:none} section.on{display:block}
  label.f{display:block;margin:14px 0} label.f span{display:block;font-weight:600}
  label.f small{display:block;color:var(--mute)} label.f.b span{display:inline;margin-left:6px}
  input[type=text],input[type=password],select{width:100%;max-width:520px;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
  .note{background:var(--panel);border-radius:8px;padding:10px 12px;margin:10px 0;font-size:14px}
  .axis{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0}
  .axis b{display:block;margin-bottom:6px} .axis label{display:block;margin:3px 0}
  .axis small{color:var(--mute)}
  .sec{margin:14px 0 4px;font-weight:600;color:var(--mute);font-size:13px;text-transform:uppercase;letter-spacing:.04em}
  .flag{display:grid;grid-template-columns:22px 1fr auto;gap:8px;padding:4px 0;border-bottom:1px solid var(--line);align-items:start}
  .flag small{color:var(--mute)} .flag .why{color:var(--acc);font-size:12px} .flag .blocked{color:var(--warn);font-size:12px}
  .flag.auto,.flag.off{opacity:.6} .flag .est{font-size:12px;color:var(--mute);white-space:nowrap}
  .est-box{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
  .est-box b{display:block;font-size:20px} .est-box small{color:var(--mute)}
  .measured{color:var(--ok)} .assumed{color:var(--warn)}
  pre{background:var(--line);padding:12px;border-radius:8px;overflow:auto;font-size:13px}
  .bar{display:flex;gap:8px;margin-top:16px;flex-wrap:wrap}
  .bar button{background:var(--acc);color:#fff;border:0;padding:9px 14px;border-radius:6px;cursor:pointer;font:inherit}
  .bar button.ghost{background:none;color:var(--acc);border:1px solid var(--acc)}
  .count{color:var(--ok);font-weight:600}
  details summary{cursor:pointer;color:var(--mute);font-size:13px}
  table{border-collapse:collapse;font-size:13px;width:100%} td,th{text-align:left;padding:3px 6px;border-bottom:1px solid var(--line)} td.n{text-align:right}
</style>
</head>
<body>
<main>
  <h1>nOS profile builder</h1>
  <p class="sub">Six short steps to a <code>config.yml</code> made for your machine, written before the first <code>nos</code> run. Nothing leaves this page.</p>
  <div class="steps" id="stepnav"></div>
  <div id="sections"></div>
</main>

<script id="data" type="application/json">__DATA__</script>
<script id="logic">
// Pure functions — tests/anatomy runs this block under node with DATA injected.
function isLocalDomain(data, d) {
  d = (d || "").trim();
  return d === "localhost" || data.local_suffixes.some(s => d.endsWith(s));
}
function stepFields(data) { return data.steps.flatMap(s => s.fields); }
function knobs(data, picks, fields) {
  // non-install values: default → profile knobs (axis order) → your answers
  const k = {...data.knob_defaults};
  for (const axis of data.axes) {
    const p = data.profiles.find(x => x.axis === axis && x.id === picks[axis]);
    if (p) Object.assign(k, p.knobs);
  }
  for (const f of stepFields(data)) {
    if (f.secret || f.key.startsWith("install_")) continue;
    const v = (fields || {})[f.key];
    if (v !== undefined && v !== "") k[f.key] = v;
  }
  return k;
}
function blocked(data, key) {
  const s = data.services[key];
  return data.offline && s && !s.offline_ok ? "not in this offline build (" + s.missing.join(", ") + ")" : "";
}
function mergeFlags(data, picks, mailId, manual) {
  // default → service-set → use-case → policy → environment → constraint → mail → your toggles
  const on = {};
  for (const f of data.flags) if (!f.auto) on[f.key] = !!f.default;
  for (const axis of data.axes) {
    const p = data.profiles.find(x => x.axis === axis && x.id === picks[axis]);
    if (p) Object.assign(on, p.flags);
  }
  const mail = data.mail.options.find(o => o.id === mailId);
  if (mail) Object.assign(on, mail.flags);
  for (const [k, v] of Object.entries(manual || {})) if (k in on) on[k] = !!v;
  for (const k of Object.keys(on)) if (blocked(data, k)) on[k] = false;   // an offline build cannot run it
  return on;
}
function estimate(data, on, kn) {
  const r = {mem_bytes: 0, image_bytes: data.offline ? 0 : null, data_gb: 0, host: [], rows: []};
  for (const [flag, s] of Object.entries(data.services)) {
    const enabled = flag in on ? on[flag] : !!(kn || {})[flag];
    if (!enabled) continue;
    r.mem_bytes += s.mem_bytes; r.data_gb += s.data_gb;
    if (s.host) r.host.push(flag);
    if (data.offline) r.image_bytes += s.image_bytes || 0;
    r.rows.push({flag, ids: s.ids, mem_bytes: s.mem_bytes, data_gb: s.data_gb, host: s.host,
                 image_bytes: data.offline ? s.image_bytes : null});
  }
  return r;
}
function renderConfig(data, fields, picks, mailId, on) {
  const L = ["# config.yml — written by the nOS profile builder", "# Overrides default.config.yml; every line here is a choice you made.", ""];
  for (const f of stepFields(data)) {
    if (f.secret || f.key.startsWith("install_")) continue;         // secret → credentials.yml; install_* → services
    const v = (fields || {})[f.key];
    if (v === undefined || v === "" || v === data.defaults[f.key]) continue;
    L.push(`${f.key}: ${JSON.stringify(v)}`);
  }
  const chosen = data.axes.map(a => picks[a]).filter(Boolean);
  if (chosen.length) L.push("", `# profiles: ${chosen.join(" + ")}`);
  for (const a of data.axes) {
    const p = data.profiles.find(x => x.axis === a && x.id === picks[a]); if (!p) continue;
    for (const [k, v] of Object.entries(p.knobs)) L.push(`${k}: ${JSON.stringify(v)}`);
  }
  L.push("", "# services");
  for (const f of data.flags) {
    if (f.auto) continue;
    if (on[f.key] !== !!f.default) L.push(`${f.key}: ${on[f.key]}`);
  }
  return L.join("\n") + "\n";
}
if (typeof module !== "undefined") module.exports = { isLocalDomain, knobs, blocked, mergeFlags, estimate, renderConfig };
</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const state = { fields: {}, picks: {}, mail: "mailpit", manual: {} };
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const gb = b => (b / 2 ** 30).toFixed(1) + " GB";
const on = () => mergeFlags(DATA, state.picks, state.mail, state.manual);
const kn = () => knobs(DATA, state.picks, state.fields);
const fieldVal = k => state.fields[k] !== undefined ? state.fields[k] : DATA.defaults[k];

// nav + one section per step
$("#stepnav").innerHTML = DATA.steps.map((s, i) => `<button data-go="${i}">${i + 1} · ${s.title}</button>`).join("");
$("#sections").innerHTML = DATA.steps.map((s, i) => `<section id="s${i}"><h2>${s.title}</h2>${s.blurb ? `<p class="sub">${s.blurb}</p>` : ""}<div id="b${i}"></div>
  <div class="bar">${i ? `<button class="ghost" data-go="${i - 1}">Back</button>` : ""}${i < DATA.steps.length - 1 ? `<button data-go="${i + 1}">Next: ${DATA.steps[i + 1].title}</button>` : ""}</div></section>`).join("");
function go(n) {
  n = +n;
  document.querySelectorAll("section").forEach(s => s.classList.toggle("on", s.id === "s" + n));
  document.querySelectorAll(".steps button").forEach(b => b.classList.toggle("on", +b.dataset.go === n));
  draw(n);
  window.scrollTo(0, 0);
}
document.querySelectorAll("[data-go]").forEach(b => b.onclick = () => go(b.dataset.go));

function fieldHtml(f) {
  const v = f.secret ? "" : (fieldVal(f.key) ?? "");
  if (f.type === "bool") {
    const cur = f.key.startsWith("install_") ? !!on()[f.key] : !!v;
    return `<label class="f b"><input type="checkbox" data-k="${f.key}" ${cur ? "checked" : ""}><span>${f.label}</span><small>${f.hint}</small></label>`;
  }
  return `<label class="f"><span>${f.label}</span><input type="${f.type === "password" ? "password" : "text"}" data-k="${f.key}" value="${esc(v)}" placeholder="${esc(f.placeholder || "")}"><small>${f.hint}</small></label>`;
}
function drawFields(i) {
  const s = DATA.steps[i];
  let html = s.fields.map(fieldHtml).join("");
  if (s.id === "domain") html += `<div class="note" id="domnote"></div>`;
  if (s.id === "backup") html += `<label class="f"><span>${DATA.mail.label}</span><select id="mail">${DATA.mail.options.map(o => `<option value="${o.id}" ${o.id === state.mail ? "selected" : ""}>${o.label}</option>`).join("")}</select></label>`;
  $("#b" + i).innerHTML = html;
  const box = $("#b" + i);
  box.oninput = box.onchange = e => {
    const k = e.target.dataset.k; if (!k) return;
    if (e.target.type === "checkbox") { if (k.startsWith("install_")) state.manual[k] = e.target.checked; else state.fields[k] = e.target.checked; }
    else state.fields[k] = e.target.value;
    if (s.id === "domain") domNote();
  };
  if (s.id === "domain") domNote();
  if (s.id === "backup") $("#mail").onchange = e => { state.mail = e.target.value; };
}
function domNote() {
  const d = fieldVal("tenant_domain") || "";
  $("#domnote").innerHTML = isLocalDomain(DATA, d)
    ? `<b>${esc(d)}</b> stays on this machine: nOS makes its own certificate (mkcert) and answers the names itself (dnsmasq). No internet or DNS records needed.`
    : `<b>${esc(d)}</b> is a public domain: nOS asks Let's Encrypt for a certificate through Cloudflare DNS. Put a Cloudflare API token with <i>Zone:DNS:Edit</i> into <code>credentials.yml</code> as <code>acme_cloudflare_api_token</code>, and point the domain's DNS at this machine when you are ready to open it up.`;
}
function estHtml(e) {
  const img = e.image_bytes === null ? `<b>?</b><small>app images — <span class="assumed">unknown</span>, this page was built without an image cache</small>`
    : `<b>${gb(e.image_bytes)}</b><small>app images — <span class="measured">measured</span> from the image cache</small>`;
  return `<div class="est-box">
    <div><b>${gb(e.mem_bytes)}</b><small>RAM — <span class="measured">measured</span>: the sum of every container's declared memory limit${e.host.length ? `; ${e.host.length} host programs (${e.host.map(h => h.replace("install_", "")).join(", ")}) and AI models are not counted` : ""}</small></div>
    <div>${img}</div>
    <div><b>≈ ${e.data_gb} GB</b><small>data after a year — <span class="assumed">assumed</span> per service type (${Object.entries(DATA.assumptions).filter(([k]) => k !== "_default").map(([k, v]) => `${k} ${v}`).join(", ")}, else ${DATA.assumptions._default}); not a measurement</small></div>
  </div>`;
}
function drawServices(i) {
  const cur = on(), e = estimate(DATA, cur, kn());
  let html = `<p class="sub">Pick one profile per question, or none. The list below is filled from your picks and stays editable.</p>` +
    DATA.axes.map(a => {
      const ps = DATA.profiles.filter(p => p.axis === a);
      return `<div class="axis"><b>${a}</b><label><input type="radio" name="${a}" value="" ${state.picks[a] ? "" : "checked"}> none</label>` +
        ps.map(p => `<label><input type="radio" name="${a}" value="${p.id}" ${state.picks[a] === p.id ? "checked" : ""}> <code>${p.id}</code> <small>${p.purpose}</small></label>`).join("") + `</div>`;
    }).join("") +
    `<h2>Services — <span class="count" id="count">${Object.values(cur).filter(Boolean).length} on</span></h2>` +
    (DATA.offline ? `<div class="note">This page was built from an offline image cache: a service whose images are not in it is switched off and cannot be turned on.</div>` : "") +
    `<div id="estimate">${estHtml(e)}</div><div id="flags"></div>`;
  $("#b" + i).innerHTML = html;
  drawFlags();
  $("#b" + i).onchange = ev => {
    const t = ev.target;
    if (t.type === "radio") { state.picks[t.name] = t.value || undefined; drawServices(i); return; }
    if (t.dataset.k) { state.manual[t.dataset.k] = t.checked; drawFlags(); }
  };
}
function drawFlags() {
  const cur = on(), e = estimate(DATA, cur, kn());
  let sec = null, html = "";
  for (const f of DATA.flags) {
    if (f.section !== sec) { sec = f.section; html += `<div class="sec">${esc(sec)}</div>`; }
    const b = blocked(DATA, f.key), s = DATA.services[f.key];
    const why = f.auto ? "decided by nOS from your answers" : (b ? "" : (cur[f.key] !== !!f.default ? "from profile" : ""));
    const est = s ? (s.host ? "host" : `${(s.mem_bytes / 2 ** 20) | 0} MB RAM`) : "";
    html += `<div class="flag${f.auto ? " auto" : ""}${b ? " off" : ""}"><input type="checkbox" data-k="${f.key}" ${f.auto || b ? "disabled" : ""} ${cur[f.key] ? "checked" : ""}><div><code>${f.key.replace("install_", "")}</code> <small>${esc(f.label)}</small> <span class="why">${why}</span>${b ? `<span class="blocked">${esc(b)}</span>` : ""}</div><span class="est">${est}</span></div>`;
  }
  $("#flags").innerHTML = html;
  $("#count").textContent = Object.values(cur).filter(Boolean).length + " on";
  $("#estimate").innerHTML = estHtml(e);
}
function drawReview(i) {
  const cur = on(), e = estimate(DATA, cur, kn());
  const yaml = renderConfig(DATA, state.fields, state.picks, state.mail, cur);
  $("#b" + i).innerHTML = estHtml(e) +
    `<details><summary>per service</summary><table><tr><th>service</th><th>RAM</th><th>images</th><th>data (assumed)</th></tr>` +
    e.rows.map(r => `<tr><td>${r.ids.join(", ")}</td><td class="n">${r.host ? "host" : gb(r.mem_bytes)}</td><td class="n">${r.image_bytes === null ? "?" : gb(r.image_bytes)}</td><td class="n">${r.data_gb} GB</td></tr>`).join("") + `</table></details>` +
    `<p class="sub">Save it as <code>config.yml</code> next to <code>default.config.yml</code> in your nOS checkout, then run <code>nos</code>. Secrets (password prefix, Cloudflare token, S3 keys) go to <code>credentials.yml</code>, never here.</p>
    <pre id="out">${esc(yaml)}</pre><div class="bar"><button id="dl">Download config.yml</button><button class="ghost" id="cp">Copy</button></div>`;
  $("#dl").onclick = () => { const b = new Blob([yaml], {type: "text/yaml"}); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "config.yml"; a.click(); };
  $("#cp").onclick = () => navigator.clipboard.writeText(yaml);
}
function draw(i) {
  const s = DATA.steps[i];
  if (s.id === "services") drawServices(i); else if (s.id === "review") drawReview(i); else drawFields(i);
}
go(0);
</script>
</body>
</html>
