// hub-icons.js (P1a icon glyph render, 2026-05-29)
// Maps per-plugin hub_card.icon names to lucide standard names + renders SVGs
// into the .sys-icon span via lucide.createIcons(). The wing-base aggregator
// already wires data-icon="<name>" onto each sys-card; this turns the hint
// into a visible glyph without touching the plugin manifests.

(function () {
  // Aliases: plugin authors used some non-standard names (kept for semantic
  // clarity in the manifests); map to the closest lucide v0.x icon.
  const ALIAS = {
    'ai-chat':     'message-square-text',
    'chart-line':  'trending-up',
    'ci-pipeline': 'git-branch',
    // keap-base (cortex) declares `compass` (knowledge exploration); the slim
    // subset carries no compass glyph — `map` is the closest (knowledge map).
    'compass':     'map',
    'docker':      'container',
    'git':         'git-branch',
    // W6.5: was a silent miss — homeassistant-base declares it, no lucide
    // icon of that name exists, the span rendered empty.
    'home-automation': 'home',
    'vault':       'lock-keyhole',
    'wiki':        'book-open',
  };

  const els = document.querySelectorAll('.sys-icon[data-icon]');
  if (!els.length || !window.lucide) {
    return;
  }
  for (const el of els) {
    const raw = el.dataset.icon || '';
    if (!raw) continue;
    el.setAttribute('data-lucide', ALIAS[raw] || raw);
  }
  window.lucide.createIcons();
})();
