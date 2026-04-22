// ==============================================================================
// HomelabPortal – Dashboard for all homelab services
// Shows a grid of cards; clicking opens the service in a new OS.js window (iframe)
// ==============================================================================

import osjs from 'osjs';
import { name as applicationName } from './metadata.json';

// Icon map (emoji fallback)
const ICONS = {
  grafana: '\u{1F4CA}', nextcloud: '\u{2601}\uFE0F', gitea: '\u{1F4E6}',
  gitlab: '\u{1F98A}', n8n: '\u26A1', openwebui: '\u{1F916}',
  portainer: '\u{1F433}', jellyfin: '\u{1F3AC}', uptime_kuma: '\u{1F4DF}',
  calibreweb: '\u{1F4DA}', kiwix: '\u{1F4D6}', maps: '\u{1F5FA}\uFE0F',
  wordpress: '\u{1F4DD}', homeassistant: '\u{1F3E0}', rustfs: '\u{1F4E6}',
  erpnext: '\u{1F4BC}', freescout: '\u{1F4E9}', mattermost: '\u{1F4AC}',
  outline: '\u{1F4D3}', metabase: '\u{1F4C8}', superset: '\u{1F4CA}',
  freepbx: '\u{1F4DE}', qgis: '\u{1F30D}', woodpecker: '\u{1F528}',
  default: '\u{1F5A5}\uFE0F',
};

const getIcon = (id) => ICONS[id] || ICONS.default;

// Create a DOM element safely
const el = (tag, attrs, children) => {
  const node = document.createElement(tag);
  if (attrs) {
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'textContent') {
        node.textContent = v;
      } else if (k === 'style' && typeof v === 'string') {
        node.style.cssText = v;
      } else if (k.startsWith('data-')) {
        node.setAttribute(k, v);
      } else if (k === 'className') {
        node.className = v;
      } else {
        node.setAttribute(k, v);
      }
    });
  }
  if (children) {
    (Array.isArray(children) ? children : [children]).forEach((child) => {
      if (typeof child === 'string') {
        node.appendChild(document.createTextNode(child));
      } else if (child) {
        node.appendChild(child);
      }
    });
  }
  return node;
};

// Build service card DOM
const buildCard = (svc) => {
  const card = el('div', {
    className: 'homelab-card',
    'data-id': svc.id,
    'data-url': svc.url,
    'data-name': svc.name,
  }, [
    el('div', { className: 'homelab-card-icon', textContent: getIcon(svc.id) }),
    el('div', { className: 'homelab-card-name', textContent: svc.name }),
    el('div', { className: 'homelab-card-desc', textContent: svc.description || '' }),
    el('div', { className: 'homelab-card-status' }),
  ]);
  return card;
};

// Build service grid
const buildGrid = (services) => {
  if (!services.length) {
    return el('div', {
      style: 'padding:2rem;text-align:center;color:#64748b;',
      textContent: 'No services are active. Enable them in config.yml and re-run the playbook.',
    });
  }

  const grid = el('div', { className: 'homelab-grid' },
    services.map((svc) => buildCard(svc))
  );
  return grid;
};

// Open service in iframe window
const openService = (core, svc) => {
  const existing = core.make('osjs/windows').list()
    .find((w) => w.id === `homelab_${svc.id}`);

  if (existing) {
    existing.focus();
    return;
  }

  const proc = core.make('osjs/application', {
    args: {},
    options: {},
    metadata: { name: `HomelabFrame_${svc.id}` },
  });

  proc.createWindow({
    id: `homelab_${svc.id}`,
    title: svc.name,
    dimension: { width: 1200, height: 800 },
    position: {
      left: 80 + Math.floor(Math.random() * 120),
      top: 40 + Math.floor(Math.random() * 80),
    },
  })
  .on('destroy', () => proc.destroy())
  .render(($content) => {
    const iframe = document.createElement('iframe');
    iframe.src = svc.url;
    iframe.setAttribute('sandbox',
      'allow-scripts allow-forms allow-popups allow-modals');
    iframe.style.cssText = 'width:100%;height:100%;border:none;background:#fff;';
    $content.appendChild(iframe);
  });
};

// ── Application entry ────────────────────────────────────────────────────────
osjs.register(applicationName, (core, args, options, metadata) => {
  const proc = core.make('osjs/application', {
    args, options, metadata,
  });

  const win = proc.createWindow({
    id: 'HomelabPortalWindow',
    title: metadata.title.en_EN || 'Homelab Portal',
    dimension: { width: 820, height: 560 },
    position: { left: 100, top: 80 },
  });

  win.on('destroy', () => proc.destroy());

  win.render(($content) => {
    const loading = el('div', {
      style: 'padding:2rem;color:#64748b;',
      textContent: 'Loading services\u2026',
    });
    $content.appendChild(loading);

    fetch('/api/homelab/services')
      .then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then((services) => {
        $content.removeChild(loading);
        const grid = buildGrid(services);
        $content.appendChild(grid);

        $content.querySelectorAll('.homelab-card[data-url]').forEach((card) => {
          card.addEventListener('click', () => {
            openService(core, {
              id: card.dataset.id,
              name: card.dataset.name,
              url: card.dataset.url,
            });
          });
        });
      })
      .catch((err) => {
        loading.textContent = 'Error: ' + err.message;
        loading.style.color = '#ef4444';
      });
  });

  return proc;
});

export default applicationName;
