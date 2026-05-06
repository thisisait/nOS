FROM ghcr.io/heyputer/puter:latest

# Upstream puter:latest runs as non-root (uid=1000/node) — switch to root for patch RUNs.
USER root

# Fix: Add CSS link to Puter homepage (bundle.min.css not included in self-hosted mode)
# File moved in newer upstream: dist/src/backend/services/homepage/PuterHomepageService.js
RUN f=$(find /opt/puter -name "PuterHomepageService.js" 2>/dev/null | head -1); \
    if [ -n "$f" ]; then \
      PUTER_FILE="$f" node -e " \
  const fs = require('fs'); \
  const f = process.env.PUTER_FILE; \
  let c = fs.readFileSync(f, 'utf8'); \
  const needle = '<link rel=\"preload\" as=\"image\" href=\"\${asset_dir}/images/wallpaper.webp\">'; \
  if (!c.includes(needle)) { console.log('WARNING: CSS needle not found in', f); process.exit(0); } \
  c = c.replace(needle, needle + '\\n        <link rel=\"stylesheet\" href=\"\${asset_dir}/bundle.min.css\">'); \
  fs.writeFileSync(f, c); \
  console.log('CSS link injected into', f); \
"; \
    else echo 'WARNING: PuterHomepageService.js not found — CSS patch skipped'; fi

# Fix CORS credentials (Puter 2.5.x bug — commented out in source)
# Skip gracefully if compiled layout no longer has this file separately
RUN f=$(find /opt/puter -name "WebServerService.js" 2>/dev/null | head -1); \
    if [ -n "$f" ]; then \
      sed -i "s|// res.setHeader('Access-Control-Allow-Credentials', true);|res.setHeader('Access-Control-Allow-Credentials', true);|g" "$f" && \
      echo "CORS credentials patched in $f"; \
    else echo 'INFO: WebServerService.js not found — CORS credentials patch skipped'; fi

# Fix Socket.IO CORS credentials
RUN f=$(find /opt/puter -name "SocketioService.js" 2>/dev/null | head -1); \
    if [ -n "$f" ]; then \
      sed -i "s|cors: {|cors: { credentials: true,|g" "$f" && \
      echo "Socket.IO CORS patched in $f"; \
    else echo 'INFO: SocketioService.js not found — Socket.IO CORS patch skipped'; fi

# Fix: Set cookie domain for cross-subdomain auth (api.os.dev.local ↔ os.dev.local)
# Without domain attribute, cookies are only sent to the exact host that set them.
RUN found=0; \
    for f in $(find /opt/puter -path "*/routers/login.js" -o -path "*/routers/signup.js" 2>/dev/null); do \
      found=1; \
      PUTER_FILE="$f" node -e " \
  const fs = require('fs'); \
  const f = process.env.PUTER_FILE; \
  let c = fs.readFileSync(f, 'utf8'); \
  c = c.replace(/sameSite: 'none',\n\s+secure: true,\n\s+httpOnly: true,/g, \
    \"sameSite: 'none',\\n        secure: true,\\n        httpOnly: true,\\n        domain: '.' + (require('/opt/puter/config.default.json').domain || 'os.dev.local'),\"); \
  fs.writeFileSync(f, c); \
  console.log('Cookie domain patched in', f); \
"; \
    done; \
    [ "$found" = "0" ] && echo 'INFO: login.js/signup.js not found — cookie domain patch skipped' || true

# Replace recommended apps list with nOS services (original has cloud-only games)
# File moved in newer upstream: dist/src/backend/services/apps/RecommendedAppsService.js
RUN f=$(find /opt/puter -name "RecommendedAppsService.js" 2>/dev/null | head -1); \
    if [ -n "$f" ]; then \
      PUTER_FILE="$f" node -e " \
  const fs = require('fs'); \
  const f = process.env.PUTER_FILE; \
  let c = fs.readFileSync(f, 'utf8'); \
  const oldList = c.match(/static APP_NAMES = \[[\s\S]*?\];/); \
  if (oldList) { \
    c = c.replace(oldList[0], \
      \"static APP_NAMES = [\\n\" + \
      \"        'terminal',\\n\" + \
      \"        'dev-center',\\n\" + \
      \"        'grafana',\\n\" + \
      \"        'gitea',\\n\" + \
      \"        'nextcloud',\\n\" + \
      \"        'openwebui',\\n\" + \
      \"        'n8n',\\n\" + \
      \"        'portainer',\\n\" + \
      \"        'outline',\\n\" + \
      \"        'metabase',\\n\" + \
      \"        'jellyfin',\\n\" + \
      \"        'authentik',\\n\" + \
      \"        'uptime-kuma',\\n\" + \
      \"        'wordpress',\\n\" + \
      \"        'home-assistant',\\n\" + \
      \"        'puter-linux',\\n\" + \
      \"    ];\" \
    ); \
    fs.writeFileSync(f, c); \
    console.log('Recommended apps replaced with nOS services'); \
  } else { \
    console.log('WARNING: APP_NAMES pattern not found — recommended apps patch skipped'); \
  } \
"; \
    else echo 'WARNING: RecommendedAppsService.js not found — recommended apps patch skipped'; fi

# Disable Camera/Recorder auto-launch (cloud-only apps, not available in self-hosted)
# GUI bundle is at src/gui/dist/ in newer upstream (not app/dist/)
RUN f=$(find /opt/puter/src/gui/dist -name "bundle.min.js" 2>/dev/null | head -1); \
    if [ -n "$f" ]; then \
      sed -i 's/app-5584fbf7-ed69-41fc-99cd-85da21b1ef51/disabled-camera/g' "$f" && \
      sed -i 's/app-7bdca1a4-6373-4c98-ad97-03ff2d608ca1/disabled-recorder/g' "$f" && \
      echo "Camera/Recorder disabled in $f"; \
    else echo 'WARNING: bundle.min.js not found — Camera/Recorder patch skipped'; fi

USER node
