/* hub-map.js — Hub "Service Map" schematic view.
 * A20 scaffold 2026-05-23; reviewed + enriched 2026-05-24.
 *
 * A toggleable, interactive node-graph of the registered systems, rendered as
 * an SVG force-directed graph. Built ENTIRELY client-side from the existing
 * `.sys-card` DOM nodes the cards view already emits (no presenter change) —
 * so it stays in sync with the cards and needs zero server round-trips.
 *
 * Nodes  : one per system (service) + one synthetic hub per stack. Service
 *          nodes carry name · health · version · port · category · scan
 *          findings (everything the card exposes).
 * Edges  : service → its stack hub; every stack hub → the `infra` hub
 *          (stacks depend on the shared infra bus). This is the first
 *          dependency model; richer data-flow edges (Bone telemetry, Traefik
 *          access graph) plug into `buildGraph()` later.
 * Interact: drag to pan, wheel / +- to zoom, hover to focus a node + its
 *          edges, click for the detail panel, drag a node to reposition.
 *          View choice persists in localStorage.
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  // Map every health_status the registry can emit → a dot colour. Missing
  // synonyms previously all fell through to grey "unknown".
  var HEALTH_COLORS = {
    up: '#3fb950', healthy: '#3fb950', ok: '#3fb950', online: '#3fb950',
    down: '#f85149', error: '#f85149', unhealthy: '#f85149', offline: '#f85149',
    degraded: '#d29922', starting: '#d29922', warn: '#d29922', restarting: '#d29922',
    unknown: '#6e7681'
  };
  var STORE_KEY = 'nos.hub.view';
  var W = 1600, H = 1000;

  var state = {
    built: false, wired: false, scale: 1, tx: 0, ty: 0,
    graph: null, byId: null, svg: null, gRoot: null, drag: null, pan: null
  };

  function el(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in (attrs || {})) e.setAttribute(k, attrs[k]);
    return e;
  }
  function txt(card, sel, def) {
    var e = card.querySelector(sel);
    return (e && e.textContent.trim()) ? e.textContent.trim() : (def || '');
  }
  function digits(s) { var m = String(s || '').match(/\d+/); return m ? parseInt(m[0], 10) : 0; }
  function color(h) { return HEALTH_COLORS[h] || HEALTH_COLORS.unknown; }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  // ── Read the cards DOM into a graph ────────────────────────────────────────
  function buildGraph() {
    var cards = Array.prototype.slice.call(document.querySelectorAll('#hub-cards-view .sys-card'));
    var nodes = {}, edges = [], stacks = {};

    cards.forEach(function (c) {
      var id = c.getAttribute('data-id');
      if (!id) return;
      var stack = (c.getAttribute('data-stack') || 'other').trim() || 'other';
      var portEl = c.querySelector('.sys-link-port');
      var domEl = c.querySelector('.sys-link-https');
      var findEl = c.querySelector('.sys-scan-findings');
      nodes[id] = {
        id: id, kind: 'service',
        name: txt(c, '.sys-name', id),
        stack: stack,
        category: c.getAttribute('data-category') || '',
        health: c.getAttribute('data-health') || 'unknown',
        version: txt(c, '.version', ''),
        desc: txt(c, '.sys-desc', ''),
        port: portEl ? portEl.textContent.replace(/[^0-9]/g, '') : '',
        domain: domEl ? domEl.textContent.trim() : '',
        domainUrl: domEl ? (domEl.getAttribute('href') || '') : '',
        findings: findEl ? digits(findEl.textContent) : 0
      };
      if (!stacks[stack]) {
        var hubId = '__stack__' + stack;
        stacks[stack] = hubId;
        nodes[hubId] = { id: hubId, kind: 'stack', name: stack, stack: stack, health: 'up', count: 0, findings: 0 };
      }
      nodes[stacks[stack]].count++;
      nodes[stacks[stack]].findings += nodes[id].findings;
      edges.push({ from: id, to: stacks[stack] });
    });

    // stack hubs depend on the shared infra bus
    var infraHub = stacks['infra'];
    if (infraHub) {
      Object.keys(stacks).forEach(function (s) {
        if (s !== 'infra') edges.push({ from: stacks[s], to: infraHub, weak: true });
      });
    }
    // adjacency map → hover focus
    var adj = {};
    edges.forEach(function (e) {
      (adj[e.from] = adj[e.from] || {})[e.to] = 1;
      (adj[e.to] = adj[e.to] || {})[e.from] = 1;
    });
    return { nodes: Object.keys(nodes).map(function (k) { return nodes[k]; }), edges: edges, adj: adj };
  }

  // ── Tiny spring-electrical layout (deterministic seed → stable each open) ──
  function layout(graph, w, h) {
    var byId = {};
    var seed = 1;
    function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
    graph.nodes.forEach(function (n) {
      n.x = w / 2 + (rnd() - 0.5) * w * 0.8;
      n.y = h / 2 + (rnd() - 0.5) * h * 0.8;
      n.vx = 0; n.vy = 0;
      byId[n.id] = n;
    });
    var k = Math.sqrt((w * h) / Math.max(graph.nodes.length, 1)) * 0.9;
    for (var iter = 0; iter < 220; iter++) {
      var t = 1 - iter / 220;
      for (var i = 0; i < graph.nodes.length; i++) {
        var a = graph.nodes[i]; var fx = 0, fy = 0;
        for (var j = 0; j < graph.nodes.length; j++) {
          if (i === j) continue;
          var b = graph.nodes[j];
          var dx = a.x - b.x, dy = a.y - b.y;
          var d2 = dx * dx + dy * dy + 0.01;
          var rep = (k * k) / d2;
          fx += dx * rep; fy += dy * rep;
        }
        a.vx = (a.vx + fx) * 0.85; a.vy = (a.vy + fy) * 0.85;
      }
      graph.edges.forEach(function (e) {
        var a = byId[e.from], b = byId[e.to];
        if (!a || !b) return;
        var dx = b.x - a.x, dy = b.y - a.y;
        var d = Math.sqrt(dx * dx + dy * dy) + 0.01;
        var att = (d * d) / k * (e.weak ? 0.4 : 1);
        var ux = dx / d, uy = dy / d;
        a.vx += ux * att; a.vy += uy * att;
        b.vx -= ux * att; b.vy -= uy * att;
      });
      graph.nodes.forEach(function (n) {
        if (n.fixed) return;
        var sp = Math.sqrt(n.vx * n.vx + n.vy * n.vy) + 0.01;
        var max = 40 * t + 2;
        var f = Math.min(sp, max) / sp;
        n.x += n.vx * f * 0.02; n.y += n.vy * f * 0.02;
        n.x = Math.max(40, Math.min(w - 40, n.x));
        n.y = Math.max(40, Math.min(h - 40, n.y));
      });
    }
    return byId;
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function edgePath(a, b) {
    var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - 30;
    return 'M' + a.x + ',' + a.y + ' Q' + mx + ',' + my + ' ' + b.x + ',' + b.y;
  }

  function render(view) {
    var graph = state.graph = buildGraph();
    var wrap = view.querySelector('.hub-map-canvas-wrap');
    if (!graph.nodes.length) {
      wrap.innerHTML =
        '<div class="empty-state"><div class="empty-state-title">No systems to map</div>' +
        '<div class="empty-state-hint">Register systems first (Hub cards view).</div></div>';
      return;
    }
    var byId = state.byId = layout(graph, W, H);

    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'hub-map-svg', preserveAspectRatio: 'xMidYMid meet' });
    var gRoot = el('g', { class: 'hub-map-root' });
    var gEdges = el('g', { class: 'hub-map-edges' });
    var gNodes = el('g', { class: 'hub-map-nodes' });
    gRoot.appendChild(gEdges); gRoot.appendChild(gNodes); svg.appendChild(gRoot);

    graph.edges.forEach(function (e) {
      var a = byId[e.from], b = byId[e.to];
      if (!a || !b) return;
      gEdges.appendChild(el('path', {
        d: edgePath(a, b), class: 'hub-edge' + (e.weak ? ' weak' : ''),
        'data-from': e.from, 'data-to': e.to
      }));
    });

    graph.nodes.forEach(function (n) {
      var g = el('g', {
        class: 'hub-node hub-node-' + n.kind, 'data-id': n.id,
        transform: 'translate(' + n.x + ',' + n.y + ')'
      });
      if (n.kind === 'stack') {
        g.appendChild(el('circle', { r: 30, class: 'hub-node-stack-c' }));
        var st = el('text', { class: 'hub-node-stack-t', 'text-anchor': 'middle', dy: -1 });
        st.textContent = n.name.toUpperCase();
        g.appendChild(st);
        var sc = el('text', { class: 'hub-node-stack-n', 'text-anchor': 'middle', dy: 12 });
        sc.textContent = n.count + ' svc';
        g.appendChild(sc);
      } else {
        var bw = 168, bh = 48;
        g.appendChild(el('rect', { x: -bw / 2, y: -bh / 2, width: bw, height: bh, rx: 9, class: 'hub-node-box' }));
        g.appendChild(el('circle', { cx: -bw / 2 + 14, cy: -7, r: 5, fill: color(n.health), class: 'hub-node-dot' }));
        var nt = el('text', { x: -bw / 2 + 26, y: -3, class: 'hub-node-name' });
        nt.textContent = n.name.length > 17 ? n.name.slice(0, 16) + '…' : n.name;
        g.appendChild(nt);
        var meta = [n.version, n.port ? ':' + n.port : '', n.category].filter(Boolean).join('  ·  ');
        if (meta) {
          var mt = el('text', { x: -bw / 2 + 26, y: 12, class: 'hub-node-meta' });
          mt.textContent = meta.length > 25 ? meta.slice(0, 24) + '…' : meta;
          g.appendChild(mt);
        }
        if (n.findings > 0) {
          var fb = el('g', { class: 'hub-node-find', transform: 'translate(' + (bw / 2 - 15) + ',' + (-bh / 2 + 14) + ')' });
          fb.appendChild(el('circle', { r: 9, class: 'hub-node-find-c' }));
          var ft = el('text', { class: 'hub-node-find-t', 'text-anchor': 'middle', dy: 3.5 });
          ft.textContent = n.findings > 9 ? '9+' : String(n.findings);
          fb.appendChild(ft);
          g.appendChild(fb);
        }
      }
      g.addEventListener('click', function (ev) { ev.stopPropagation(); selectNode(n); });
      g.addEventListener('mouseenter', function () { focusNode(n.id); });
      g.addEventListener('mouseleave', clearFocus);
      gNodes.appendChild(g);
    });

    wrap.innerHTML = '';
    wrap.appendChild(svg);
    state.svg = svg; state.gRoot = gRoot;
    fit();
    wireInteractions(svg);
  }

  function redrawEdges() {
    var paths = state.svg.querySelectorAll('.hub-map-edges path'); var i = 0;
    state.graph.edges.forEach(function (e) {
      var a = state.byId[e.from], b = state.byId[e.to], p = paths[i++];
      if (a && b && p) p.setAttribute('d', edgePath(a, b));
    });
  }

  // ── Hover focus (dim everything not adjacent to the hovered node) ──────────
  function focusNode(id) {
    if (state.drag || state.pan) return;
    var adj = state.graph.adj[id] || {};
    state.svg.classList.add('focusing');
    state.svg.querySelectorAll('.hub-node').forEach(function (g) {
      var gid = g.getAttribute('data-id');
      g.classList.toggle('faded', gid !== id && !adj[gid]);
    });
    state.svg.querySelectorAll('.hub-map-edges path').forEach(function (p) {
      var on = p.getAttribute('data-from') === id || p.getAttribute('data-to') === id;
      p.classList.toggle('faded', !on);
      p.classList.toggle('lit', on);
    });
  }
  function clearFocus() {
    if (!state.svg) return;
    state.svg.classList.remove('focusing');
    state.svg.querySelectorAll('.faded').forEach(function (x) { x.classList.remove('faded'); });
    state.svg.querySelectorAll('.lit').forEach(function (x) { x.classList.remove('lit'); });
  }

  // ── Pan / zoom / drag — window listeners wired ONCE (no per-node leak) ─────
  function applyTransform() {
    state.gRoot.setAttribute('transform', 'translate(' + state.tx + ',' + state.ty + ') scale(' + state.scale + ')');
  }
  function fit() { state.scale = 1; state.tx = 0; state.ty = 0; applyTransform(); }

  function wireInteractions(svg) {
    // svg-local handlers: the <svg> is recreated each render, so these die with
    // it — no accumulation. The drag/pan MOVE + UP handlers live on window and
    // are wired exactly once (state.wired), reading the shared drag/pan state.
    svg.addEventListener('mousedown', function (e) {
      var node = e.target.closest('.hub-node');
      if (node) {
        var id = node.getAttribute('data-id');
        state.drag = { g: node, n: state.byId[id] };
      } else {
        state.pan = { sx: e.clientX - state.tx, sy: e.clientY - state.ty };
        svg.classList.add('panning');
      }
    });
    svg.addEventListener('wheel', function (e) {
      e.preventDefault();
      var f = e.deltaY < 0 ? 1.1 : 0.9;
      state.scale = Math.max(0.3, Math.min(3, state.scale * f));
      applyTransform();
    }, { passive: false });

    if (state.wired) return;
    state.wired = true;

    window.addEventListener('mousemove', function (e) {
      if (state.drag && state.svg) {
        var pt = state.svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
        var loc = pt.matrixTransform(state.gRoot.getScreenCTM().inverse());
        state.drag.n.x = loc.x; state.drag.n.y = loc.y;
        state.drag.g.setAttribute('transform', 'translate(' + loc.x + ',' + loc.y + ')');
        redrawEdges();
      } else if (state.pan && state.svg) {
        state.tx = e.clientX - state.pan.sx; state.ty = e.clientY - state.pan.sy; applyTransform();
      }
    });
    window.addEventListener('mouseup', function () {
      state.drag = null; state.pan = null;
      if (state.svg) state.svg.classList.remove('panning');
    });

    var stage = document.querySelector('.hub-map-stage');
    if (stage) {
      var z = function (sel, fn) { var b = stage.querySelector(sel); if (b) b.onclick = fn; };
      z('[data-zoom="in"]', function () { state.scale = Math.min(3, state.scale * 1.2); applyTransform(); });
      z('[data-zoom="out"]', function () { state.scale = Math.max(0.3, state.scale * 0.83); applyTransform(); });
      z('[data-zoom="fit"]', fit);
    }
  }

  // ── Detail panel ───────────────────────────────────────────────────────────
  function selectNode(n) {
    state.svg.querySelectorAll('.hub-node.selected').forEach(function (x) { x.classList.remove('selected'); });
    var sel = (window.CSS && CSS.escape) ? CSS.escape(n.id) : n.id;
    var g = state.svg.querySelector('.hub-node[data-id="' + sel + '"]');
    if (g) g.classList.add('selected');
    var panel = document.getElementById('hub-map-detail');
    if (n.kind === 'stack') {
      panel.innerHTML = detailHead(n.name.toUpperCase(), 'STACK') +
        row('Services', String(n.count)) +
        (n.findings ? row('Open findings', String(n.findings)) : '') +
        row('Role', 'compose project / dependency bus');
    } else {
      var links = n.domainUrl
        ? '<div class="hub-d-links"><a class="hub-d-link" href="' + esc(n.domainUrl) +
          '" target="_blank" rel="noopener">' + esc(n.domain || 'open ↗') + '</a></div>'
        : '';
      panel.innerHTML = detailHead(n.name, (n.category || 'service').toUpperCase()) +
        '<div class="hub-d-status"><span class="hub-d-dot" style="background:' + color(n.health) + '"></span>' +
        '<span class="hub-d-health">' + esc(n.health) + '</span></div>' +
        row('Stack', n.stack) +
        (n.version ? row('Version', n.version) : '') +
        (n.port ? row('Port', n.port) : '') +
        (n.domain ? row('Domain', n.domain) : '') +
        row('Findings', String(n.findings || 0)) +
        (n.desc ? '<p class="hub-d-desc">' + esc(n.desc) + '</p>' : '') +
        links +
        '<div class="hub-d-hint">Live metrics (REQ/s · ERR% · p95 latency) wire in from Bone telemetry — coming next.</div>';
    }
    panel.classList.add('open');
  }
  function detailHead(t, b) {
    return '<div class="hub-d-head"><span class="hub-d-title">' + esc(t) + '</span><span class="hub-d-badge">' +
      esc(b) + '</span><button class="hub-d-close" aria-label="close">&times;</button></div>';
  }
  function row(k, v) {
    return '<div class="hub-d-row"><span class="hub-d-k">' + esc(k) + '</span><span class="hub-d-v">' + esc(v) + '</span></div>';
  }

  // ── View toggle ──────────────────────────────────────────────────────────
  function setView(mode) {
    var cards = document.getElementById('hub-cards-view');
    var map = document.getElementById('hub-map-view');
    if (!cards || !map) return;
    var isMap = mode === 'map';
    cards.hidden = isMap; map.hidden = !isMap;
    document.querySelectorAll('.hub-viewtoggle [data-view]').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-view') === mode);
    });
    try { localStorage.setItem(STORE_KEY, mode); } catch (e) {}
    if (isMap && !state.built) { state.built = true; render(map); }
  }

  function init() {
    var toggle = document.querySelector('.hub-viewtoggle');
    if (!toggle) return;
    toggle.addEventListener('click', function (e) {
      var b = e.target.closest('[data-view]'); if (b) setView(b.getAttribute('data-view'));
    });
    document.addEventListener('click', function (e) {
      if (e.target.closest('.hub-d-close')) document.getElementById('hub-map-detail').classList.remove('open');
    });
    var saved = 'cards';
    try { saved = localStorage.getItem(STORE_KEY) || 'cards'; } catch (e) {}
    setView(saved);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
