/* hub-map.js — Hub "Service Map" schematic view (A20 scaffold, 2026-05-23).
 *
 * A toggleable, interactive node-graph of the registered systems, rendered as
 * an SVG force-directed graph. Built ENTIRELY client-side from the existing
 * `.sys-card` DOM nodes the cards view already emits (no presenter change) —
 * so it stays in sync with the cards and needs zero server round-trips.
 *
 * Nodes  : one per system (service) + one synthetic hub per stack.
 * Edges  : service → its stack hub; every stack hub → the `infra` hub
 *          (stacks depend on the shared infra bus). This is the first
 *          dependency model; richer data-flow edges (Bone telemetry, Traefik
 *          access graph) plug into `buildGraph()` later.
 * Interact: drag to pan, wheel / +- to zoom, click a node for the detail
 *          panel, drag a node to reposition. Choice persists in localStorage.
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var HEALTH_COLORS = { up: '#3fb950', down: '#f85149', degraded: '#d29922', unknown: '#6e7681' };
  var STORE_KEY = 'nos.hub.view';

  function el(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in (attrs || {})) e.setAttribute(k, attrs[k]);
    return e;
  }

  // ── Read the cards DOM into a graph ────────────────────────────────────────
  function buildGraph() {
    var cards = Array.prototype.slice.call(document.querySelectorAll('#hub-cards-view .sys-card'));
    var nodes = {}, edges = [], stacks = {};

    cards.forEach(function (c) {
      var id = c.getAttribute('data-id');
      if (!id) return;
      var stack = (c.getAttribute('data-stack') || 'other').trim() || 'other';
      var nameEl = c.querySelector('.sys-name');
      var node = {
        id: id,
        kind: 'service',
        name: nameEl ? nameEl.textContent.trim() : id,
        stack: stack,
        category: c.getAttribute('data-category') || '',
        health: c.getAttribute('data-health') || 'unknown',
        version: (c.querySelector('.version') || {}).textContent || '',
        desc: (c.querySelector('.sys-desc') || {}).textContent || ''
      };
      nodes[id] = node;
      if (!stacks[stack]) {
        var hubId = '__stack__' + stack;
        stacks[stack] = hubId;
        nodes[hubId] = { id: hubId, kind: 'stack', name: stack, stack: stack, health: 'up' };
      }
      edges.push({ from: id, to: stacks[stack] });
    });

    // stack hubs depend on the shared infra bus
    var infraHub = stacks['infra'];
    if (infraHub) {
      Object.keys(stacks).forEach(function (s) {
        if (s !== 'infra') edges.push({ from: stacks[s], to: infraHub, weak: true });
      });
    }
    return { nodes: Object.keys(nodes).map(function (k) { return nodes[k]; }), edges: edges };
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
      // repulsion
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
      // attraction along edges
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
  var state = { built: false, scale: 1, tx: 0, ty: 0, graph: null, byId: null };

  function render(view) {
    var W = 1600, H = 1000;
    var graph = state.graph = buildGraph();
    if (!graph.nodes.length) {
      view.querySelector('.hub-map-canvas-wrap').innerHTML =
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
      var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - 30;
      var path = el('path', {
        d: 'M' + a.x + ',' + a.y + ' Q' + mx + ',' + my + ' ' + b.x + ',' + b.y,
        class: 'hub-edge' + (e.weak ? ' weak' : '')
      });
      gEdges.appendChild(path);
    });

    graph.nodes.forEach(function (n) {
      var g = el('g', { class: 'hub-node hub-node-' + n.kind, 'data-id': n.id, transform: 'translate(' + n.x + ',' + n.y + ')' });
      if (n.kind === 'stack') {
        g.appendChild(el('circle', { r: 26, class: 'hub-node-stack-c' }));
        var st = el('text', { class: 'hub-node-stack-t', 'text-anchor': 'middle', dy: 4 });
        st.textContent = n.name.toUpperCase();
        g.appendChild(st);
      } else {
        var bw = 150, bh = 40;
        g.appendChild(el('rect', { x: -bw / 2, y: -bh / 2, width: bw, height: bh, rx: 8, class: 'hub-node-box' }));
        g.appendChild(el('circle', { cx: -bw / 2 + 14, cy: 0, r: 5, fill: HEALTH_COLORS[n.health] || HEALTH_COLORS.unknown, class: 'hub-node-dot' }));
        var nt = el('text', { x: -bw / 2 + 26, y: 4, class: 'hub-node-name' });
        nt.textContent = n.name.length > 16 ? n.name.slice(0, 15) + '…' : n.name;
        g.appendChild(nt);
      }
      g.addEventListener('click', function (ev) { ev.stopPropagation(); selectNode(n); });
      enableDrag(g, n, svg);
      gNodes.appendChild(g);
    });

    var wrap = view.querySelector('.hub-map-canvas-wrap');
    wrap.innerHTML = '';
    wrap.appendChild(svg);
    state.svg = svg; state.gRoot = gRoot;
    fit();
    enablePanZoom(svg, wrap);
  }

  function applyTransform() {
    state.gRoot.setAttribute('transform', 'translate(' + state.tx + ',' + state.ty + ') scale(' + state.scale + ')');
  }
  function fit() { state.scale = 1; state.tx = 0; state.ty = 0; applyTransform(); }

  function enablePanZoom(svg, wrap) {
    var panning = false, sx = 0, sy = 0;
    svg.addEventListener('mousedown', function (e) { if (e.target.closest('.hub-node')) return; panning = true; sx = e.clientX - state.tx; sy = e.clientY - state.ty; svg.classList.add('panning'); });
    window.addEventListener('mousemove', function (e) { if (!panning) return; state.tx = e.clientX - sx; state.ty = e.clientY - sy; applyTransform(); });
    window.addEventListener('mouseup', function () { panning = false; svg.classList.remove('panning'); });
    svg.addEventListener('wheel', function (e) { e.preventDefault(); var f = e.deltaY < 0 ? 1.1 : 0.9; state.scale = Math.max(0.3, Math.min(3, state.scale * f)); applyTransform(); }, { passive: false });
    wrap.parentNode.querySelector('[data-zoom="in"]').onclick = function () { state.scale = Math.min(3, state.scale * 1.2); applyTransform(); };
    wrap.parentNode.querySelector('[data-zoom="out"]').onclick = function () { state.scale = Math.max(0.3, state.scale * 0.83); applyTransform(); };
    wrap.parentNode.querySelector('[data-zoom="fit"]').onclick = fit;
  }

  function enableDrag(g, n, svg) {
    var dragging = false;
    g.addEventListener('mousedown', function (e) { e.stopPropagation(); dragging = true; });
    window.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      var pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
      var loc = pt.matrixTransform(state.gRoot.getScreenCTM().inverse());
      n.x = loc.x; n.y = loc.y; g.setAttribute('transform', 'translate(' + n.x + ',' + n.y + ')');
      redrawEdges();
    });
    window.addEventListener('mouseup', function () { dragging = false; });
  }
  function redrawEdges() {
    var paths = state.svg.querySelectorAll('.hub-map-edges path'); var i = 0;
    state.graph.edges.forEach(function (e) {
      var a = state.byId[e.from], b = state.byId[e.to]; var p = paths[i++];
      if (!a || !b || !p) return;
      var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - 30;
      p.setAttribute('d', 'M' + a.x + ',' + a.y + ' Q' + mx + ',' + my + ' ' + b.x + ',' + b.y);
    });
  }

  function selectNode(n) {
    state.svg.querySelectorAll('.hub-node.selected').forEach(function (x) { x.classList.remove('selected'); });
    var g = state.svg.querySelector('.hub-node[data-id="' + (window.CSS && CSS.escape ? CSS.escape(n.id) : n.id) + '"]');
    if (g) g.classList.add('selected');
    var panel = document.getElementById('hub-map-detail');
    if (n.kind === 'stack') {
      var count = state.graph.nodes.filter(function (x) { return x.kind === 'service' && x.stack === n.stack; }).length;
      panel.innerHTML = detailHead(n.name.toUpperCase(), 'STACK') +
        row('Services', String(count)) + row('Role', 'compose project / cluster');
    } else {
      panel.innerHTML = detailHead(n.name, (n.category || 'service').toUpperCase()) +
        '<span class="hub-d-dot" style="background:' + (HEALTH_COLORS[n.health] || HEALTH_COLORS.unknown) + '"></span>' +
        '<span class="hub-d-health">' + n.health + '</span>' +
        row('Stack', n.stack) + (n.version ? row('Version', n.version) : '') +
        (n.desc ? '<p class="hub-d-desc">' + esc(n.desc) + '</p>' : '') +
        '<div class="hub-d-hint">Metrics (REQ/s · ERR% · latency) wire in from Bone telemetry — coming next.</div>';
    }
    panel.classList.add('open');
  }
  function detailHead(t, b) { return '<div class="hub-d-head"><span class="hub-d-title">' + esc(t) + '</span><span class="hub-d-badge">' + esc(b) + '</span><button class="hub-d-close" aria-label="close">&times;</button></div>'; }
  function row(k, v) { return '<div class="hub-d-row"><span class="hub-d-k">' + esc(k) + '</span><span class="hub-d-v">' + esc(v) + '</span></div>'; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

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
