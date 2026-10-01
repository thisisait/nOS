<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nOS setup</title>
<style>
  :root{--fg:#1d1d1f;--bg:#fff;--mute:#5f5f64;--line:#d9d9de;--acc:#0a5cb0;--ok:#1a7f37;--warn:#8a5a00;--err:#b42318;--panel:#f5f5f7}
  @media(prefers-color-scheme:dark){:root{--fg:#f2f2f2;--bg:#111;--mute:#a8a8ad;--line:#36363b;--acc:#7cbcff;--ok:#3fb950;--warn:#e0b341;--err:#ff7b72;--panel:#1c1c20}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,system-ui,Segoe UI,sans-serif}
  main{max-width:860px;margin:0 auto;padding:24px 16px 80px}
  h1{font-size:24px;margin:0 0 4px} h2{font-size:20px;margin:24px 0 6px} h2:focus{outline:none}
  h3{font-size:16px;margin:22px 0 6px}
  .sub{color:var(--mute);margin:0 0 16px}
  .steps{list-style:none;display:flex;gap:6px;margin:14px 0 18px;padding:0;flex-wrap:wrap}
  .steps button{border:1px solid var(--line);background:none;color:var(--fg);padding:6px 12px;border-radius:999px;cursor:pointer;font:inherit;font-size:14px}
  .steps button[aria-current]{border-color:var(--acc);color:var(--acc);font-weight:600}
  .steps button.bad::after{content:" !";color:var(--err);font-weight:700}
  section{display:none} section.on{display:block}
  .f{margin:16px 0} .f>label{display:block;font-weight:600}
  .f small,.hint{display:block;color:var(--mute);font-size:14px}
  .f.b>label{display:flex;gap:8px;align-items:flex-start;font-weight:600} .f.b input{margin-top:5px}
  input[type=text],input[type=email],input[type=password],select{width:100%;max-width:520px;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
  input[aria-invalid=true]{border-color:var(--err)}
  input:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
  .err{color:var(--err);font-size:14px;margin:4px 0 0} .err:empty{display:none}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;max-width:520px} .row input{flex:1 1 200px}
  .note{background:var(--panel);border-radius:8px;padding:10px 12px;margin:12px 0;font-size:15px}
  .note.warn{border-left:4px solid var(--warn)} .note.bad{border-left:4px solid var(--err)}
  fieldset{border:1px solid var(--line);border-radius:8px;padding:8px 12px 10px;margin:10px 0;min-width:0}
  legend{font-weight:600;padding:0 4px}
  .opt{display:flex;gap:8px;align-items:flex-start;margin:6px 0} .opt input{margin-top:5px}
  .opt small{display:block;color:var(--mute);font-size:14px}
  .flag{display:grid;grid-template-columns:20px 1fr auto;gap:8px;padding:6px 0;border-top:1px solid var(--line);align-items:start}
  .flag:first-of-type{border-top:0} .flag input{margin-top:5px}
  .flag small{color:var(--mute);font-size:14px} .flag code{color:var(--mute);font-size:12px}
  .flag .why{color:var(--acc);font-size:13px} .flag .blocked{color:var(--warn);font-size:13px;display:block}
  .flag.auto b,.flag.off b{color:var(--mute)} .flag .est{font-size:13px;color:var(--mute);white-space:nowrap}
  .est-box{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
  .est-box b{display:block;font-size:20px} .est-box small{color:var(--mute);font-size:13px}
  .measured{color:var(--ok)} .assumed{color:var(--warn)}
  .person{display:grid;grid-template-columns:1fr 1.4fr 1fr auto;gap:8px;align-items:end;padding:8px 0;border-top:1px solid var(--line)}
  .person label{font-size:13px;color:var(--mute);display:block} .person input,.person select{max-width:none}
  @media(max-width:620px){.person{grid-template-columns:1fr}.flag{grid-template-columns:20px 1fr}.flag .est{grid-column:2}}
  pre{background:var(--panel);padding:12px;border-radius:8px;overflow:auto;font-size:13px;max-width:100%}
  .bar{display:flex;gap:8px;margin-top:16px;flex-wrap:wrap}
  button.go,button.ghost{border-radius:6px;cursor:pointer;font:inherit;padding:9px 14px}
  button.go{background:var(--acc);color:var(--bg);border:0} button.ghost{background:none;color:var(--acc);border:1px solid var(--acc)}
  button.small{padding:4px 10px;font-size:14px}
  button:disabled{opacity:.5;cursor:not-allowed}
  .count{color:var(--ok);font-weight:600}
  details summary{cursor:pointer;color:var(--mute)}
  .scroll{overflow-x:auto}
  table{border-collapse:collapse;font-size:14px;width:100%} td,th{text-align:left;padding:3px 6px;border-bottom:1px solid var(--line)} td.n{text-align:right}
  code{font-size:.92em}
</style>
</head>
<body>
<main>
  <h1>Set up nOS</h1>
  <p class="sub">A few short questions, then you download a <code>config.yml</code> made for your machine and run <code>nos</code>. Everything stays on this page — nothing is sent anywhere.</p>
  <nav aria-label="Steps"><ol class="steps" id="stepnav"></ol></nav>
  <div id="sections"></div>
</main>

<script id="data" type="application/json">__DATA__</script>
<script id="logic">
// Pure functions — tests/anatomy runs this block under node with DATA injected.
// s = {fields, picks, mail, manual, people}: the person's answers, nothing else.
function isLocalDomain(data, d) {
  d = (d || "").trim();
  return d === "localhost" || data.local_suffixes.some(x => d.endsWith(x));
}
function stepFields(data) { return data.steps.flatMap(x => x.fields); }
function given(v) { return v !== undefined && v !== null && v !== ""; }
function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
function profileFor(data, picks, axis) { return data.profiles.find(p => p.axis === axis && p.id === (picks || {})[axis]); }
function fieldValue(data, picks, fields, key) {
  // your answer → the last picked profile that sets it → the default
  if (given((fields || {})[key])) return fields[key];
  let v = data.defaults[key];
  for (const axis of data.axes) { const p = profileFor(data, picks, axis); if (p && key in p.knobs) v = p.knobs[key]; }
  return v;
}
function knobs(data, picks, fields) {
  const k = {...data.knob_defaults};
  for (const axis of data.axes) { const p = profileFor(data, picks, axis); if (p) Object.assign(k, p.knobs); }
  for (const f of stepFields(data)) {
    if (f.secret || f.key.startsWith("install_")) continue;
    if (given((fields || {})[f.key])) k[f.key] = fields[f.key];
  }
  return k;
}
function blocked(data, key) {
  const x = data.services[key];
  return data.offline && x && !x.offline_ok ? "not in this offline build (" + x.missing.join(", ") + ")" : "";
}
function layers(data, picks, mailId, manual) {
  // default → service-set → use-case → policy → environment → constraint → mail → your toggles.
  // An untouched mail choice (null) overrides nothing, so a profile's mail flags survive.
  const on = {};
  for (const f of data.flags) if (!f.auto) on[f.key] = !!f.default;
  for (const axis of data.axes) { const p = profileFor(data, picks, axis); if (p) Object.assign(on, p.flags); }
  const mail = data.mail.options.find(o => o.id === mailId);
  if (mail) Object.assign(on, mail.flags);
  for (const [k, v] of Object.entries(manual || {})) if (k in on) on[k] = !!v;
  for (const k of Object.keys(on)) if (blocked(data, k)) on[k] = false;   // an offline build cannot run it
  return on;
}
function title(data, key) { return (data.flags.find(f => f.key === key) || {}).title || key.replace(/^install_/, "").replace(/_/g, " "); }
function consumerOn(data, c, on, kn, s) {
  if (c.flag) return !!on[c.flag];
  if (c.people) return (s.people || []).some(p => given((p.name || "").trim()));
  if (c.field) return !!fieldValue(data, s.picks, s.fields, c.field);
  return Object.values(s.picks || {}).includes(c.profile) && !!kn[c.knob];
}
function consumerName(data, c) {
  return c.flag ? title(data, c.flag) : c.people ? "the people you added" : c.field ? "the test accounts" : `the ${c.profile} profile (${c.knob})`;
}
function settle(data, s) {
  // The rules the estate declares (tools/profile-builder/rules.py), applied after every layer:
  // auto — nOS turns the provider on itself; silent — turned on here unless YOU turned it off,
  // then it blocks. Returns the flags, what was turned on and why, and what is left unmet.
  const on = layers(data, s.picks, s.mail, s.manual), kn = knobs(data, s.picks, s.fields), notes = [];
  const has = u => u in on ? !!on[u] : !!kn[u];
  const needs = data.rules.filter(r => r.cls !== "refused");
  for (let changed = true, n = 0; changed && n < 20; n++) {
    changed = false;
    for (const r of needs) {
      if (!consumerOn(data, r.consumer, on, kn, s) || r.upstream.some(has)) continue;
      const u = r.upstream.find(u => !blocked(data, u) && (r.cls === "auto" || (s.manual || {})[u] !== false));
      if (u === undefined) continue;
      on[u] = true; changed = true;
      notes.push({key: u, cls: r.cls, source: r.source});
    }
  }
  const live = needs.filter(r => consumerOn(data, r.consumer, on, kn, s));
  for (const n of notes) n.by = [...new Set(live.filter(r => r.upstream.includes(n.key)).map(r => consumerName(data, r.consumer)))].join(", ");
  return {on, kn, notes, unmet: live.filter(r => !r.upstream.some(has))};
}
function mergeFlags(data, picks, mailId, manual, s) {
  return settle(data, {fields: {}, people: [], ...(s || {}), picks, mail: mailId, manual}).on;
}
function mailOf(data, on) {
  const o = data.mail.options.find(o => Object.entries(o.flags).every(([k, v]) => !!on[k] === v));
  return o ? o.id : "";
}
function estimate(data, on, kn) {
  const r = {mem_bytes: 0, image_bytes: data.offline ? 0 : null, data_gb: 0, host: [], rows: []};
  const seen = new Set();                      // one image shared by two services is stored once
  for (const [flag, x] of Object.entries(data.services)) {
    const enabled = flag in on ? on[flag] : !!(kn || {})[flag];
    if (!enabled) continue;
    r.mem_bytes += x.mem_bytes; r.data_gb += x.data_gb;
    if (x.host) r.host.push(flag);
    if (data.offline) for (const [img, b] of Object.entries(x.image_sizes || {})) if (!seen.has(img)) { seen.add(img); r.image_bytes += b; }
    r.rows.push({flag, ids: x.ids, mem_bytes: x.mem_bytes, data_gb: x.data_gb, host: x.host,
                 image_bytes: data.offline ? x.image_bytes : null});
  }
  return r;
}
function nearest(data, s) {
  // Per axis, the profile that agrees with the most of what you chose yourself and contradicts none of it.
  const flagDefault = Object.fromEntries(data.flags.map(f => [f.key, !!f.default]));
  const said = {};
  for (const f of stepFields(data)) {
    const v = (s.fields || {})[f.key];
    if (!f.secret && !f.key.startsWith("install_") && given(v) && !same(v, data.defaults[f.key])) said[f.key] = v;
  }
  for (const [k, v] of Object.entries(s.manual || {})) if (!!v !== flagDefault[k]) said[k] = !!v;
  const mail = data.mail.options.find(o => o.id === s.mail);
  if (mail && s.mail !== data.mail.default) for (const [k, v] of Object.entries(mail.flags)) if (v !== flagDefault[k]) said[k] = v;
  const out = [];
  for (const axis of data.axes) {
    let best = null;
    for (const p of data.profiles.filter(x => x.axis === axis && !x.step)) {
      const sets = {...p.flags, ...p.knobs};
      const agree = Object.keys(said).filter(k => k in sets && same(sets[k], said[k]));
      const clash = Object.keys(said).filter(k => k in sets && !same(sets[k], said[k]));
      if (agree.length && !clash.length && (!best || agree.length > best.agree.length)) best = {axis, id: p.id, agree};
    }
    if (best && (s.picks || {})[axis] !== best.id) out.push(best);
  }
  return out;
}
const NAME_RE = /^[a-z]([a-z0-9._-]{0,61}[a-z0-9])?$/,   // = main.yml "Every extra person is well-formed"
      EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CHECKS = {
  timezone: v => /^(UTC|[A-Z][A-Za-z_]+(\/[A-Za-z0-9_+-]+)+)$/.test(v) ? "" : "Use a zone name like Europe/London or America/New_York.",
  abs_path: v => v.startsWith("/") ? "" : "Write the full path, starting with / (a ~ is not understood everywhere).",
  repo: v => /^(\/|[a-z0-9]+:)/.test(v) ? "" : "A full folder path starting with /, or a bucket address like s3:https://…",
  domain: v => v === "localhost" || /^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9]$/.test(v) ? "" : "Lowercase letters, digits, dashes and dots, e.g. dev.local or example.com — no https://.",
  slug: v => /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(v) ? "" : "Lowercase letters, digits and dashes only.",
  email: v => EMAIL_RE.test(v) ? "" : "That does not look like an e-mail address.",
  username: v => NAME_RE.test(v) ? "" : "Start with a lowercase letter; then lowercase letters, digits, dot, dash or underscore; end with a letter or digit.",
  acme_token: v => /^\S+$/.test(v) ? "" : "A token has no spaces.",
};
function fieldActive(data, s, on, f) {
  return !f.when || (f.when.startsWith("install_") ? !!on[f.when] : !!fieldValue(data, s.picks, s.fields, f.when));
}
function stepOf(data, key) {
  const st = data.steps.find(x => x.fields.some(f => f.key === key));
  if (st) return st.id;
  if (key === "tenant_domain_is_local" || key in data.derived) return "domain";
  return data.mail.options.some(o => key in o.flags) ? "backup" : "services";
}
function refusedProblems(data, s, st) {
  // main.yml and the roles refuse these combinations outright; the words come from the rule's literals.
  const domain = fieldValue(data, s.picks, s.fields, "tenant_domain") || "";
  const field = v => stepFields(data).find(f => f.key === v);
  const val = v => v in st.on ? !!st.on[v] : v in data.derived ? (data.derived[v] === "local") === isLocalDomain(data, domain)
    : v in st.kn ? !!st.kn[v] : given((s.fields || {})[v]);
  const words = ([v, want]) => v in data.derived ? ((data.derived[v] === "local") === want ? "your domain stays on this machine" : "your domain is public")
    : field(v) && field(v).type !== "bool" ? (want ? `${field(v).label.replace(/\s*\(.*\)$/, "")} is given` : `no ${field(v).label.replace(/\s*\(.*\)$/, "")} is given`)
    : `${title(data, v)} is ${want ? "on" : "off"}`;
  const P = [];
  for (const r of data.rules.filter(r => r.cls === "refused")) {
    if (!r.all.every(([v, want]) => val(v) === want)) continue;
    const via = r.any.filter(val);
    if (r.any.length && !via.length) continue;
    const said = [...new Set(r.all.map(words))].join(", ");
    const key = (r.all.find(([v]) => field(v)) || r.all.find(([v]) => stepOf(data, v) !== "services") || r.all[0] || [via[0]])[0];
    const gated = via.map(v => r.labels[v] || title(data, v)).join(", ");
    P.push({step: stepOf(data, key), key, msg: `nOS would refuse to start: ${said}${via.length ? ` — and ${gated} sign in through it` : ""} (“${r.why}”). Change one of these.`});
  }
  return P;
}
function unmetProblems(data, st) {
  const by = {};
  for (const r of st.unmet) for (const u of r.upstream.slice(0, 1)) (by[u] = by[u] || new Set()).add(consumerName(data, r.consumer));
  return Object.entries(by).map(([u, cs]) => {
    const names = [...cs].join(", "), up = title(data, u), why = blocked(data, u), many = cs.size > 1;
    const need = many ? "need" : "needs", them = many ? "those" : names;
    return {step: "services", key: u, msg: why ? `${names} ${need} ${up}, which is ${why}. Turn ${them} off.`
      : `${names} ${need} ${up}, which you turned off. Turn ${up} back on, or turn ${them} off.`};
  });
}
function prefixProblem(data, v) {
  if (!given(v)) return "Choose a master password, or press Generate. nOS refuses to start without one.";
  if (data.prefix_rule.refused.includes(v) || v.length < data.prefix_rule.min) return `At least ${data.prefix_rule.min} characters, and not "changeme".`;
  return /^[A-Za-z0-9]+$/.test(v) ? "" : "Letters and digits only — it is built into other passwords and files.";
}
function emails(data, s) {
  // The e-mail each account will really have, as the playbook derives it.
  const domain = fieldValue(data, s.picks, s.fields, "tenant_domain") || "dev.local";
  const me = fieldValue(data, s.picks, s.fields, "nos_primary_admin");
  return {
    system: String(fieldValue(data, s.picks, s.fields, "default_admin_email") || `admin@${domain}`).trim().toLowerCase(),
    operator: String(fieldValue(data, s.picks, s.fields, "nos_operator_email") || `${me || "<your login>"}@${domain}`).trim().toLowerCase(),
    tester: `tester@${domain}`,
    test: (data.accounts.test_users || []).map(u => `${u.name}@${domain}`),
  };
}
function problems(data, s) {
  // Everything that would make `nos` refuse this config, as {step, key, msg}. Defaults are trusted;
  // what you typed is checked. The playbook asserts the same rules again (main.yml, Identities).
  const P = [], st = settle(data, s), on = st.on;
  for (const x of data.steps) for (const f of x.fields) {
    if (!f.check || !fieldActive(data, s, on, f)) continue;
    const v = (s.fields || {})[f.key];
    let msg = "";
    if (f.check === "prefix") msg = prefixProblem(data, v);
    else if (f.check === "repo" && !given(v)) msg = "Say where the second copy goes, or turn it off.";
    else if (given(v)) msg = CHECKS[f.check](String(v).trim());
    if (msg) P.push({step: x.id, key: f.key, msg});
  }
  P.push(...refusedProblems(data, s, st), ...unmetProblems(data, st));
  const em = emails(data, s);
  if (em.operator === em.system) P.push({step: "accounts", key: "nos_operator_email", msg: "Your e-mail must differ from the system e-mail."});
  const me = fieldValue(data, s.picks, s.fields, "nos_primary_admin");
  const reserved = new Set([...data.accounts.reserved, ...(given(me) ? [me] : [])]);
  const slug = n => n.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const usedSlugs = new Set([...reserved].map(slug));
  const usedMail = new Set([em.system, em.operator, em.tester, ...(fieldValue(data, s.picks, s.fields, "nos_test_users_enabled") ? em.test : [])]);
  (s.people || []).forEach((p, i) => {
    const at = k => `people.${i}.${k}`, name = (p.name || "").trim(), mail = (p.email || "").trim().toLowerCase();
    if (!name && !mail) { P.push({step: "accounts", key: at("name"), msg: "Type a username, or remove this row."}); return; }
    if (!NAME_RE.test(name)) P.push({step: "accounts", key: at("name"), msg: CHECKS.username(name)});
    else if (usedSlugs.has(slug(name))) P.push({step: "accounts", key: at("name"), msg: `"${name}" is taken (or too close to a name that is).`});
    else usedSlugs.add(slug(name));
    if (!EMAIL_RE.test(mail)) P.push({step: "accounts", key: at("email"), msg: CHECKS.email(mail)});
    else if (usedMail.has(mail)) P.push({step: "accounts", key: at("email"), msg: "Another account already has this e-mail; apps would mix the two people up."});
    else usedMail.add(mail);
    if (![1, 2, 3, 4].includes(+p.tier)) P.push({step: "accounts", key: at("tier"), msg: "Choose an access level."});
  });
  return P;
}
function renderConfig(data, s, on) {
  const J = v => JSON.stringify(typeof v === "string" ? v.trim() : v);
  const L = ["# config.yml — written by the nOS profile builder", "# Overrides default.config.yml; every line here is a choice you made or a profile you picked.", ""];
  const vals = {}, from = {};
  for (const axis of data.axes) {
    const p = profileFor(data, s.picks, axis); if (!p) continue;
    for (const [k, v] of Object.entries(p.knobs)) { vals[k] = v; from[k] = p.id; }
  }
  for (const f of stepFields(data)) {                   // your answer outranks a profile's knob, written once
    if (f.secret || f.key.startsWith("install_")) continue;   // secret → credentials.yml; install_* → services
    if (!fieldActive(data, s, on, f)) continue;               // a hidden answer (backup off) is not a choice
    const v = (s.fields || {})[f.key];
    if (given(v)) { vals[f.key] = typeof v === "string" ? v.trim() : v; delete from[f.key]; }
  }
  const keep = Object.keys(vals).filter(k => !same(vals[k], data.defaults[k]));
  for (const f of stepFields(data)) if (keep.includes(f.key) && !from[f.key]) L.push(`${f.key}: ${J(vals[f.key])}`);
  const chosen = data.axes.map(a => (s.picks || {})[a]).filter(Boolean);
  if (chosen.length) L.push("", `# profiles: ${chosen.join(" + ")}`);
  for (const k of keep.filter(k => from[k])) L.push(`${k}: ${J(vals[k])}`);
  const people = (s.people || []).filter(p => given(p.name));
  if (people.length) {
    L.push("", "# people — each password is generated; after the first run read one with",
           "#   tools/nos-secret.py --user <name> nos-identity password", "nos_extra_identities:");
    for (const p of people) L.push(`  - {name: ${J(p.name)}, email: ${J((p.email || "").toLowerCase())}, tier: ${+p.tier}}`);
  }
  L.push("", "# services");
  for (const f of data.flags) if (!f.auto && on[f.key] !== !!f.default) L.push(`${f.key}: ${on[f.key]}`);
  return L.join("\n") + "\n";
}
function renderCredentials(data, prefix, fields) {
  if (prefixProblem(data, prefix)) return "";
  const L = ["# credentials.yml — written by the nOS profile builder. Keep it private (chmod 600).",
             `global_password_prefix: ${JSON.stringify(prefix)}`];
  for (const f of stepFields(data)) {
    const v = (fields || {})[f.key];
    if (f.secret && f.check !== "prefix" && given(v)) L.push(`${f.key}: ${JSON.stringify(String(v).trim())}`);
  }
  return L.concat("").join("\n");
}
if (typeof module !== "undefined") module.exports = { isLocalDomain, fieldValue, knobs, blocked, mergeFlags, settle, mailOf, estimate, nearest, problems, renderConfig, renderCredentials };
</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const state = { fields: {}, picks: {}, mail: null, manual: {}, people: [] };
let current = 0;
const $ = q => document.querySelector(q);
const esc = v => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const gb = b => (b / 2 ** 30).toFixed(1) + " GB";
const settled = () => settle(DATA, state);
const on = () => settled().on;
const kn = () => knobs(DATA, state.picks, state.fields);
const val = k => fieldValue(DATA, state.picks, state.fields, k);
const tierLabel = t => (DATA.accounts.tiers.find(x => x.tier === +t) || {}).label || "?";
const BROWSER_TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { return ""; } })();
const TZ_LIST = (() => { try { return Intl.supportedValuesOf("timeZone"); } catch (e) { return []; } })();

$("#stepnav").innerHTML = DATA.steps.map((st, i) => `<li><button type="button" data-go="${i}">${i + 1}. ${st.title}</button></li>`).join("");
$("#sections").innerHTML = DATA.steps.map((st, i) => `<section id="s${i}" aria-labelledby="t${i}"><h2 id="t${i}" tabindex="-1">${i + 1}. ${st.title}</h2>${st.blurb ? `<p class="sub">${st.blurb}</p>` : ""}<div id="b${i}"></div>
  <div class="bar">${i ? `<button type="button" class="ghost" data-go="${i - 1}">Back</button>` : ""}${i < DATA.steps.length - 1 ? `<button type="button" class="go" data-go="${i + 1}">Next: ${DATA.steps[i + 1].title}</button>` : ""}</div></section>`).join("");
document.addEventListener("click", e => { const b = e.target.closest("[data-go]"); if (b) go(b.dataset.go); });

function go(n, quiet) {
  current = +n;
  document.querySelectorAll("section").forEach(x => x.classList.toggle("on", x.id === "s" + current));
  document.querySelectorAll(".steps button").forEach(b => +b.dataset.go === current ? b.setAttribute("aria-current", "step") : b.removeAttribute("aria-current"));
  draw(current);
  markSteps();
  window.scrollTo(0, 0);
  if (!quiet) $("#t" + current).focus();
}
function markSteps() {
  const bad = new Set(problems(DATA, state).map(p => p.step));
  document.querySelectorAll(".steps button").forEach(b => b.classList.toggle("bad", bad.has(DATA.steps[+b.dataset.go].id) && +b.dataset.go < current));
}
function placeholderFor(f) {
  const domain = val("tenant_domain") || "dev.local";
  if (f.key === "default_admin_email") return `admin@${domain}`;
  if (f.key === "nos_operator_email") return `${val("nos_primary_admin") || "<your login>"}@${domain}`;
  return f.placeholder || "";
}
function fieldHtml(f) {
  const id = "f-" + f.key, hint = `<small id="h-${f.key}">${f.hint}</small>`, err = `<p class="err" id="e-${f.key}" role="status"></p>`;
  const wrap = inner => `<div class="f${f.type === "bool" ? " b" : ""}" id="w-${f.key}">${inner}${err}</div>`;
  if (f.type === "bool") {
    const cur = f.key.startsWith("install_") ? !!on()[f.key] : !!val(f.key);
    return wrap(`<label><input type="checkbox" id="${id}" data-k="${f.key}" aria-describedby="h-${f.key}" ${cur ? "checked" : ""}><span>${f.label}</span></label>${hint}`);
  }
  const v = f.secret ? (state.fields[f.key] || "") : (state.fields[f.key] ?? (val(f.key) ?? ""));
  const type = f.type === "password" ? "password" : "text";
  const extra = f.type === "timezone" ? ` list="tzlist" autocomplete="off"` : f.check === "email" ? ` inputmode="email" autocomplete="email"` : ` autocomplete="off"`;
  let after = "";
  if (f.type === "password") after = `${f.check === "prefix" ? `<button type="button" class="ghost small" data-gen="${f.key}">Generate</button>` : ""}<button type="button" class="ghost small" data-show="${f.key}" aria-pressed="false">Show</button>`;
  if (f.type === "timezone" && BROWSER_TZ && BROWSER_TZ !== v) after = `<button type="button" class="ghost small" data-tz>Use this computer's: ${esc(BROWSER_TZ)}</button>`;
  const dl = f.type === "timezone" && TZ_LIST.length ? `<datalist id="tzlist">${TZ_LIST.map(z => `<option value="${z}">`).join("")}</datalist>` : "";
  return wrap(`<label for="${id}">${f.label}</label><div class="row"><input type="${type}" id="${id}" data-k="${f.key}" value="${esc(v)}" placeholder="${esc(placeholderFor(f))}" aria-describedby="h-${f.key} e-${f.key}"${extra} spellcheck="false">${after}</div>${dl}${hint}`);
}
function showProblems() {
  const P = problems(DATA, state);
  document.querySelectorAll(".err").forEach(e => { e.textContent = ""; });
  document.querySelectorAll("[aria-invalid]").forEach(e => e.removeAttribute("aria-invalid"));
  for (const p of P) {
    const e = document.getElementById("e-" + p.key); if (e) e.textContent = p.msg;
    const i = document.getElementById("f-" + p.key); if (i) i.setAttribute("aria-invalid", "true");
  }
  const mn = document.getElementById("mailnotes");
  if (mn) mn.innerHTML = notesHtml(n => DATA.mail.options.some(o => n.key in o.flags)) +
    P.filter(p => p.step === "backup" && !document.getElementById("e-" + p.key)).map(p => `<p class="err">${esc(p.msg)}</p>`).join("");
  for (const f of DATA.steps.flatMap(x => x.fields)) if (f.when) {
    const w = document.getElementById("w-" + f.key);
    if (w) w.hidden = !(f.when.startsWith("install_") ? on()[f.when] : val(f.when));
  }
  return P;
}
function drawFields(i) {
  const st = DATA.steps[i], box = $("#b" + i);
  let html = st.fields.map(fieldHtml).join("");
  if (st.id === "domain") html += `<div class="note" id="domnote" aria-live="polite"></div>`;
  if (st.id === "backup") {
    const cur = state.mail || mailOf(DATA, on());
    html += `<div class="f"><label for="mail">${DATA.mail.label}</label><select id="mail">${cur ? "" : `<option value="" selected>As your service choices set it</option>`}${DATA.mail.options.map(o => `<option value="${o.id}" ${o.id === cur ? "selected" : ""}>${o.label}</option>`).join("")}</select><div id="mailnotes"></div></div>`;
  }
  if (st.id === "accounts") html += accountsHtml();
  box.innerHTML = html;
  box.oninput = box.onchange = e => {
    const t = e.target, k = t.dataset.k;
    if (t.id === "mail") { state.mail = t.value || null; showProblems(); return; }
    if (t.dataset.p !== undefined) { state.people[+t.dataset.p][t.dataset.pk] = t.value; showProblems(); return; }
    if (!k) return;
    if (t.type === "checkbox") { if (k.startsWith("install_")) state.manual[k] = t.checked; else state.fields[k] = t.checked; }
    else state.fields[k] = t.value;
    if (k === "nos_test_users_enabled" && st.id === "accounts") { drawFields(i); return; }
    if (st.id === "domain") domNote();
    showProblems();
  };
  box.onclick = e => {
    const t = e.target;
    if (t.dataset.gen) { const inp = $("#f-" + t.dataset.gen); inp.value = state.fields[t.dataset.gen] = strongPrefix(); inp.type = "text"; showProblems(); }
    if (t.dataset.show) { const inp = $("#f-" + t.dataset.show), shown = inp.type === "password"; inp.type = shown ? "text" : "password"; t.setAttribute("aria-pressed", String(shown)); t.textContent = shown ? "Hide" : "Show"; }
    if (t.dataset.tz !== undefined) { const inp = $("#f-nos_timezone"); inp.value = state.fields.nos_timezone = BROWSER_TZ; showProblems(); }
    if (t.dataset.add !== undefined) { state.people.push({name: "", email: "", tier: 3}); drawFields(i); document.getElementById(`f-people.${state.people.length - 1}.name`).focus(); }
    if (t.dataset.del !== undefined) { state.people.splice(+t.dataset.del, 1); drawFields(i); }
  };
  if (st.id === "domain") domNote();
  showProblems();
}
function strongPrefix() {
  const abc = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789", r = new Uint32Array(24);
  crypto.getRandomValues(r);
  return Array.from(r, x => abc[x % abc.length]).join("");
}
function accountsHtml() {
  const tu = DATA.accounts.test_users, testOn = !!val("nos_test_users_enabled");
  const tierOpts = t => DATA.accounts.tiers.map(x => `<option value="${x.tier}" ${x.tier === +t ? "selected" : ""}>${x.label}</option>`).join("");
  return `<p class="hint">${testOn ? "Test accounts: " : "The test accounts would be: "}${tu.map(u => `${u.name} (${tierLabel(u.tier)})`).join(", ")}.</p>
  <div class="note">Always created as well: <b>akadmin</b>, the system administrator (uses the system e-mail), and <b>nos-tester</b>, which nOS uses to check itself.</div>
  <h3>Other people</h3>
  <p class="hint">Each person gets an account and their own account in every app they may open. Access levels: ${DATA.accounts.tiers.map(x => `<b>${x.label}</b> — ${esc(x.description.toLowerCase())}`).join("; ")}. A higher level includes everything below it.</p>
  <div id="people">${state.people.map((p, i) => `<div class="person" role="group" aria-label="Person ${i + 1}">
    <div><label for="f-people.${i}.name">Username</label><input type="text" id="f-people.${i}.name" data-p="${i}" data-pk="name" value="${esc(p.name)}" autocomplete="off" spellcheck="false" aria-describedby="e-people.${i}.name"><p class="err" id="e-people.${i}.name" role="status"></p></div>
    <div><label for="f-people.${i}.email">E-mail</label><input type="email" id="f-people.${i}.email" data-p="${i}" data-pk="email" value="${esc(p.email)}" autocomplete="off" aria-describedby="e-people.${i}.email"><p class="err" id="e-people.${i}.email" role="status"></p></div>
    <div><label for="f-people.${i}.tier">Access</label><select id="f-people.${i}.tier" data-p="${i}" data-pk="tier">${tierOpts(p.tier)}</select><p class="err" id="e-people.${i}.tier" role="status"></p></div>
    <div><button type="button" class="ghost small" data-del="${i}" aria-label="Remove person ${i + 1}">Remove</button></div></div>`).join("")}</div>
  <div class="bar"><button type="button" class="ghost" data-add>Add a person</button></div>
  <div class="note">Passwords: nOS makes a separate password for each person. After the first run, read one with <code>tools/nos-secret.py --user &lt;username&gt; nos-identity password</code> and give it to that person. nOS keeps it: a password changed on the sign-in page is put back by the next run.</div>`;
}
function domNote() {
  const d = val("tenant_domain") || "";
  $("#domnote").innerHTML = isLocalDomain(DATA, d)
    ? `<b>${esc(d)}</b> stays on this machine: nOS makes its own certificate and answers the names itself. No internet or DNS settings needed. Your browser will ask once to trust the certificate.`
    : `<b>${esc(d)}</b> is a public domain: nOS asks Let's Encrypt for a certificate through Cloudflare. Put a Cloudflare API token with <i>Zone:DNS:Edit</i> into <code>credentials.yml</code> as <code>acme_cloudflare_api_token</code>, and point the domain at this machine when you are ready to open it up.`;
}
function notesHtml(filter) {
  // What the rules turned on for you, and why — never silently.
  const ns = settled().notes.filter(filter || (() => true));
  return ns.length ? `<div class="note" aria-live="polite"><b>Turned on for you:</b><ul>${ns.map(n => `<li><b>${esc(title(DATA, n.key))}</b> — ${esc(n.by)} ${n.by.includes(",") ? "need" : "needs"} it${n.cls === "auto" ? " (nOS turns it on itself)" : ""}.</li>`).join("")}</ul></div>` : "";
}
function unmetHtml() {
  const P = problems(DATA, state).filter(p => p.step === "services");
  return P.length ? `<div class="note bad" role="alert"><ul>${P.map(p => `<li>${esc(p.msg)}</li>`).join("")}</ul></div>` : "";
}
function estHtml(e) {
  const img = e.image_bytes === null ? `<b>?</b><small>downloads — <span class="assumed">unknown</span>: this page was built without an image cache</small>`
    : `<b>${gb(e.image_bytes)}</b><small>downloads — <span class="measured">measured</span> from the image cache</small>`;
  return `<div class="est-box" aria-live="polite">
    <div><b>${gb(e.mem_bytes)}</b><small>memory — <span class="measured">measured</span>: the services' declared limits${e.host.length ? `; ${e.host.length} programs running directly on the computer and AI models are not counted` : ""}</small></div>
    <div>${img}</div>
    <div><b>≈ ${e.data_gb} GB</b><small>data after a year — <span class="assumed">a guess</span> per kind of service (${Object.entries(DATA.assumptions).filter(([k]) => k !== "_default").map(([k, v]) => `${k} ${v}`).join(", ")}, else ${DATA.assumptions._default})</small></div>
  </div>`;
}
function drawServices(i) {
  const cur = on(), sug = nearest(DATA, state);
  const plainOf = id => (DATA.profiles.find(p => p.id === id) || {}).plain || id;
  let html = (sug.length ? `<div class="note">Based on your answers so far, this may fit: ${sug.map(x => `<b>${esc(plainOf(x.id))}</b> <small>(${x.id}; it also sets ${x.agree.map(esc).join(", ")})</small> <button type="button" class="ghost small" data-pick="${x.axis}" data-id="${x.id}">Use it</button>`).join("<br>")}</div>` : "") +
    `<p class="sub">Answer any of these to fill the list below, or skip them. The list stays editable.</p>` +
    DATA.axes.map(a => {
      const ps = DATA.profiles.filter(p => p.axis === a && !p.step);
      if (!ps.length) return "";
      return `<fieldset><legend>${DATA.axis_questions[a] || a}</legend><label class="opt"><input type="radio" name="${a}" value="" ${state.picks[a] ? "" : "checked"}><span>No / not sure</span></label>` +
        ps.map(p => `<label class="opt"><input type="radio" name="${a}" value="${p.id}" ${state.picks[a] === p.id ? "checked" : ""}><span>${esc(p.plain || p.id)} <small>${p.id}</small></span></label>`).join("") + `</fieldset>`;
    }).join("") +
    `<h3>Services — <span class="count" id="count" aria-live="polite">${Object.values(cur).filter(Boolean).length} on</span></h3>` +
    (DATA.offline ? `<div class="note warn">This page was built from an offline image cache: a service whose download is not in it is switched off and cannot be turned on.</div>` : "") +
    `<div id="estimate">${estHtml(estimate(DATA, cur, kn()))}</div><div id="svcnotes"></div><div id="flags"></div>`;
  const box = $("#b" + i);
  box.innerHTML = html;
  drawFlags();
  box.oninput = null;
  box.onchange = ev => {
    const t = ev.target;
    if (t.type === "radio") { state.picks[t.name] = t.value || undefined; drawServices(i); $(`input[name="${t.name}"]:checked`).focus(); return; }
    if (t.dataset.k) { state.manual[t.dataset.k] = t.checked; drawFlags(); }
  };
  box.onclick = ev => { const b = ev.target.closest("[data-pick]"); if (b) { state.picks[b.dataset.pick] = b.dataset.id; drawServices(i); } };
}
function drawFlags() {
  const st = settled(), cur = st.on;
  let html = "";
  for (const g of DATA.groups) {
    const fs = DATA.flags.filter(f => f.group === g);
    if (!fs.length) continue;
    html += `<fieldset><legend>${esc(g)}</legend>` + fs.map(f => {
      const b = blocked(DATA, f.key), x = DATA.services[f.key];
      const n = st.notes.find(x => x.key === f.key), forced = n && n.cls === "auto";
      const why = f.auto ? "nOS decides this from your answers" : b ? "" : n ? `turned on: ${n.by} ${n.by.includes(",") ? "need" : "needs"} it` : (cur[f.key] !== !!f.default ? "changed from the default" : "");
      const est = x ? (x.host ? "on the computer" : `${(x.mem_bytes / 2 ** 20) | 0} MB`) : "";
      return `<label class="flag${f.auto ? " auto" : ""}${b ? " off" : ""}"><input type="checkbox" data-k="${f.key}" ${f.auto || b || forced ? "disabled" : ""} ${cur[f.key] ? "checked" : ""}><span><b>${esc(f.title)}</b>${f.plain ? ` <small>— ${esc(f.plain)}</small>` : ""} <code>${f.key}</code> <span class="why">${why}</span>${b ? `<span class="blocked">${esc(b)}</span>` : ""}</span><span class="est">${est}</span></label>`;
    }).join("") + `</fieldset>`;
  }
  $("#flags").innerHTML = html;
  $("#svcnotes").innerHTML = unmetHtml() + notesHtml();
  $("#count").textContent = Object.values(cur).filter(Boolean).length + " on";
  $("#estimate").innerHTML = estHtml(estimate(DATA, cur, kn()));
}
function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type: "text/yaml"}));
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function drawReview(i) {
  const cur = on(), e = estimate(DATA, cur, kn()), P = problems(DATA, state);
  const yaml = renderConfig(DATA, state, cur), creds = renderCredentials(DATA, state.fields.global_password_prefix || "", state.fields);
  const stepNo = id => DATA.steps.findIndex(x => x.id === id);
  $("#b" + i).innerHTML = (P.length ? `<div class="note bad" role="alert"><b>Fix these first:</b><ul>${P.map(p => `<li>${esc(p.msg)} <button type="button" class="ghost small" data-go="${stepNo(p.step)}">Go to step ${stepNo(p.step) + 1}</button></li>`).join("")}</ul></div>` : "") +
    notesHtml() + estHtml(e) +
    `<details><summary>Per service</summary><div class="scroll"><table><tr><th scope="col">service</th><th scope="col">memory</th><th scope="col">download</th><th scope="col">data (guess)</th></tr>` +
    e.rows.map(r => `<tr><td>${r.ids.join(", ")}</td><td class="n">${r.host ? "on the computer" : gb(r.mem_bytes)}</td><td class="n">${r.image_bytes === null ? "?" : gb(r.image_bytes)}</td><td class="n">${r.data_gb} GB</td></tr>`).join("") + `</table></div></details>` +
    `<h3>What to do with the files</h3><ol><li>Download both files below.</li><li>Put them in your nOS folder, next to <code>default.config.yml</code>.</li><li>In a terminal there, run <code>nos</code>.</li></ol>
    <p class="hint"><code>credentials.yml</code> holds your master password, so it is not shown here. Keep it private.</p>
    <div class="bar"><button type="button" class="go" id="dl" ${P.length ? "disabled" : ""}>Download config.yml</button><button type="button" class="go" id="dlc" ${P.length || !creds ? "disabled" : ""}>Download credentials.yml</button><button type="button" class="ghost" id="cp" ${P.length ? "disabled" : ""}>Copy config.yml</button><span id="cpmsg" role="status"></span></div>
    <h3>config.yml</h3><pre id="out" tabindex="0">${esc(yaml)}</pre>`;
  $("#dl").onclick = () => download("config.yml", yaml);
  $("#dlc").onclick = () => download("credentials.yml", creds);
  $("#cp").onclick = () => {
    const fallback = () => { const r = document.createRange(); r.selectNodeContents($("#out")); getSelection().removeAllRanges(); getSelection().addRange(r); $("#cpmsg").textContent = "Selected — press Cmd+C (Ctrl+C)."; };
    if (navigator.clipboard) navigator.clipboard.writeText(yaml).then(() => { $("#cpmsg").textContent = "Copied."; }, fallback); else fallback();
  };
}
function draw(i) {
  const st = DATA.steps[i];
  if (st.id === "services") drawServices(i); else if (st.id === "review") drawReview(i); else drawFields(i);
}
go(0, true);
</script>
</body>
</html>
