<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nOS profile builder</title>
<style>
  :root{--fg:#1d1d1f;--bg:#fff;--mute:#6e6e73;--line:#e5e5ea;--acc:#0a66c2;--ok:#1a7f37}
  @media(prefers-color-scheme:dark){:root{--fg:#f2f2f2;--bg:#111;--mute:#9a9a9f;--line:#2a2a2e;--acc:#6cb4ff;--ok:#3fb950}}
  body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,Segoe UI,sans-serif}
  main{max-width:880px;margin:0 auto;padding:24px 16px 80px}
  h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:28px 0 8px}
  .sub{color:var(--mute);margin:0 0 18px}
  .steps{display:flex;gap:8px;margin:12px 0 20px;flex-wrap:wrap}
  .steps button{border:1px solid var(--line);background:none;color:var(--fg);padding:6px 12px;border-radius:999px;cursor:pointer}
  .steps button.on{border-color:var(--acc);color:var(--acc)}
  section{display:none} section.on{display:block}
  label.f{display:block;margin:10px 0} label.f span{display:block;font-weight:600}
  label.f small{color:var(--mute)} input[type=text],input[type=password],select{width:100%;max-width:520px;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
  .axis{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0}
  .axis b{display:block;margin-bottom:6px} .axis label{display:block;margin:3px 0}
  .axis small{color:var(--mute)}
  .sec{margin:14px 0 4px;font-weight:600;color:var(--mute);font-size:13px;text-transform:uppercase;letter-spacing:.04em}
  .flag{display:grid;grid-template-columns:22px 1fr;gap:8px;padding:4px 0;border-bottom:1px solid var(--line)}
  .flag small{color:var(--mute)} .flag .why{color:var(--acc);font-size:12px}
  .flag.auto{opacity:.6}
  pre{background:var(--line);padding:12px;border-radius:8px;overflow:auto;font-size:13px}
  .bar{display:flex;gap:8px;margin-top:16px;flex-wrap:wrap}
  .bar button{background:var(--acc);color:#fff;border:0;padding:9px 14px;border-radius:6px;cursor:pointer;font:inherit}
  .bar button.ghost{background:none;color:var(--acc);border:1px solid var(--acc)}
  .count{color:var(--ok);font-weight:600}
</style>
</head>
<body>
<main>
  <h1>nOS profile builder</h1>
  <p class="sub">Three steps to a <code>config.yml</code> tailored to you, written before the first <code>nos</code> run. Nothing leaves this page.</p>
  <div class="steps">
    <button data-go="1" class="on">1 · Parameters</button>
    <button data-go="2">2 · Profiles</button>
    <button data-go="3">3 · Services</button>
    <button data-go="4">4 · config.yml</button>
  </div>

  <section id="s1" class="on">
    <h2>Key parameters</h2>
    <div id="params"></div>
    <label class="f"><span>E-mail</span><select id="mail"></select></label>
    <div class="bar"><button data-go="2">Next: profiles</button></div>
  </section>

  <section id="s2">
    <h2>Profiles — one per axis, or none</h2>
    <p class="sub">Each axis answers one question. The service list in step 3 is prefilled from what you pick here, in this order.</p>
    <div id="axes"></div>
    <div class="bar"><button class="ghost" data-go="1">Back</button><button data-go="3">Next: services</button></div>
  </section>

  <section id="s3">
    <h2>Services — <span class="count" id="count"></span></h2>
    <p class="sub">Prefilled from the profiles; add or remove freely. Greyed flags are decided by nOS from your parameters.</p>
    <div id="flags"></div>
    <div class="bar"><button class="ghost" data-go="2">Back</button><button data-go="4">Next: config.yml</button></div>
  </section>

  <section id="s4">
    <h2>Your config.yml</h2>
    <p class="sub">Save it as <code>config.yml</code> next to <code>default.config.yml</code> in your nOS checkout, then run <code>nos</code>. Secrets go to <code>credentials.yml</code>, never here.</p>
    <pre id="out"></pre>
    <div class="bar"><button class="ghost" data-go="3">Back</button><button id="dl">Download config.yml</button><button class="ghost" id="cp">Copy</button></div>
  </section>
</main>

<script id="data" type="application/json">__DATA__</script>
<script id="logic">
// Pure functions — tests/anatomy runs this block under node with DATA injected.
function mergeFlags(data, picks, mailId) {
  // default → service-set → use-case → policy → environment → constraint → mail
  const on = {};
  for (const f of data.flags) if (!f.auto) on[f.key] = !!f.default;
  for (const axis of data.axes) {
    const p = data.profiles.find(x => x.axis === axis && x.id === picks[axis]);
    if (p) Object.assign(on, p.flags);
  }
  const mail = data.mail.options.find(o => o.id === mailId);
  if (mail) Object.assign(on, mail.flags);
  return on;
}
function renderConfig(data, params, picks, mailId, on) {
  const L = ["# config.yml — written by the nOS profile builder", "# Overrides default.config.yml; every line here is a choice you made.", ""];
  for (const p of data.params) {
    if (p.secret) continue;                                  // step 1 secret → credentials.yml
    const v = params[p.key]; if (v === undefined || v === "" || v === data.param_defaults[p.key]) continue;
    L.push(`${p.key}: ${JSON.stringify(String(v))}`);
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
if (typeof module !== "undefined") module.exports = { mergeFlags, renderConfig };
</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const state = { params: {...DATA.param_defaults}, picks: {}, mail: "none", on: null, touched: {} };
const $ = s => document.querySelector(s);
function go(n) {
  document.querySelectorAll("section").forEach(s => s.classList.toggle("on", s.id === "s" + n));
  document.querySelectorAll(".steps button").forEach(b => b.classList.toggle("on", b.dataset.go == n));
  if (n == 3) drawFlags(); if (n == 4) drawOut();
}
document.querySelectorAll("[data-go]").forEach(b => b.onclick = () => go(b.dataset.go));
// step 1
$("#params").innerHTML = DATA.params.map(p => `<label class="f"><span>${p.label}</span><input type="${p.secret ? "password" : "text"}" data-k="${p.key}" value="${p.secret ? "" : (DATA.param_defaults[p.key] ?? "")}"><small>${p.hint}${p.secret ? " — goes to credentials.yml, not config.yml" : ""}</small></label>`).join("");
$("#params").oninput = e => { state.params[e.target.dataset.k] = e.target.value; };
$("#mail").innerHTML = DATA.mail.options.map(o => `<option value="${o.id}">${o.label}</option>`).join("");
$("#mail").onchange = e => { state.mail = e.target.value; state.on = null; };
// step 2
$("#axes").innerHTML = DATA.axes.map(a => {
  const ps = DATA.profiles.filter(p => p.axis === a);
  return `<div class="axis"><b>${a}</b><label><input type="radio" name="${a}" value="" checked> none</label>` +
    ps.map(p => `<label><input type="radio" name="${a}" value="${p.id}"> <code>${p.id}</code> <small>${p.purpose}</small></label>`).join("") + `</div>`;
}).join("");
$("#axes").onchange = e => { state.picks[e.target.name] = e.target.value || undefined; state.on = null; };
// step 3
function drawFlags() {
  if (!state.on) { state.on = mergeFlags(DATA, state.picks, state.mail); state.touched = {}; }
  let sec = null, html = "";
  for (const f of DATA.flags) {
    if (f.section !== sec) { sec = f.section; html += `<div class="sec">${sec}</div>`; }
    const why = f.auto ? "decided by nOS" : (state.on[f.key] !== !!f.default ? "from profile" : "");
    html += `<div class="flag${f.auto ? " auto" : ""}"><input type="checkbox" data-k="${f.key}" ${f.auto ? "disabled" : (state.on[f.key] ? "checked" : "")}><div><code>${f.key.replace("install_", "")}</code> <small>${f.label}</small> <span class="why">${why}</span></div></div>`;
  }
  $("#flags").innerHTML = html;
  $("#count").textContent = Object.values(state.on).filter(Boolean).length + " on";
}
$("#flags").onchange = e => { state.on[e.target.dataset.k] = e.target.checked; $("#count").textContent = Object.values(state.on).filter(Boolean).length + " on"; };
// step 4
function drawOut() { if (!state.on) state.on = mergeFlags(DATA, state.picks, state.mail); $("#out").textContent = renderConfig(DATA, state.params, state.picks, state.mail, state.on); }
$("#dl").onclick = () => { const b = new Blob([$("#out").textContent], {type: "text/yaml"}); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "config.yml"; a.click(); };
$("#cp").onclick = () => navigator.clipboard.writeText($("#out").textContent);
</script>
</body>
</html>
