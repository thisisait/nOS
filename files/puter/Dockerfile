FROM ghcr.io/heyputer/puter:latest

# Fix: Copy pre-built GUI assets (CSS, fonts, images, manifest) to runtime gui/dist
# Puter serves from src/gui/dist/ but only JS is there; CSS/fonts/images are in app/dist/
RUN mkdir -p /opt/puter/app/src/gui/dist && \
    cp -r /opt/puter/app/dist/* /opt/puter/app/src/gui/dist/

# Fix: Add CSS link to HTML (Puter homepage doesn't include it in self-hosted/bundled mode)
# Inject CSS link after the </head> opening — template uses JS backtick strings
RUN node -e " \
  const fs = require('fs'); \
  const f = '/opt/puter/app/src/backend/src/services/PuterHomepageService.js'; \
  let c = fs.readFileSync(f, 'utf8'); \
  c = c.replace( \
    '<link rel=\"preload\" as=\"image\" href=\"\${asset_dir}/images/wallpaper.webp\">', \
    '<link rel=\"preload\" as=\"image\" href=\"\${asset_dir}/images/wallpaper.webp\">\\n        <link rel=\"stylesheet\" href=\"\${asset_dir}/bundle.min.css\">' \
  ); \
  fs.writeFileSync(f, c); \
  console.log('CSS link injected'); \
"

# Fix CORS credentials (Puter 2.5.x bug — commented out in source)
RUN sed -i "s|// res.setHeader('Access-Control-Allow-Credentials', true);|res.setHeader('Access-Control-Allow-Credentials', true);|g" \
    /opt/puter/app/src/backend/src/modules/web/WebServerService.js

# Fix Socket.IO CORS credentials
RUN sed -i "s|cors: {|cors: { credentials: true,|g" \
    /opt/puter/app/src/backend/src/modules/web/SocketioService.js

# Fix: Set cookie domain to parent domain for cross-subdomain auth (api.os.dev.local ↔ os.dev.local)
# Without domain attribute, cookies are only sent to the exact host that set them.
# We add domain: '.' + config.domain to make cookies valid across all subdomains.
RUN node -e " \
  const fs = require('fs'); \
  const files = [ \
    '/opt/puter/app/src/backend/src/routers/login.js', \
    '/opt/puter/app/src/backend/src/routers/signup.js' \
  ]; \
  files.forEach(f => { \
    let c = fs.readFileSync(f, 'utf8'); \
    c = c.replace(/sameSite: 'none',\n\s+secure: true,\n\s+httpOnly: true,/g, \
      \"sameSite: 'none',\\n        secure: true,\\n        httpOnly: true,\\n        domain: '.' + (require('/opt/puter/app/src/backend/src/config').domain || 'os.dev.local'),\" \
    ); \
    fs.writeFileSync(f, c); \
  }); \
  console.log('Cookie domain patched'); \
"

# Replace recommended apps list with nOS services (original has cloud-only games)
RUN node -e " \
  const fs = require('fs'); \
  const f = '/opt/puter/app/src/backend/src/modules/apps/RecommendedAppsService.js'; \
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
    console.log('WARNING: APP_NAMES pattern not found'); \
  } \
"

# Disable Camera/Recorder auto-launch (cloud-only apps, not available in self-hosted)
RUN sed -i 's/app-5584fbf7-ed69-41fc-99cd-85da21b1ef51/disabled-camera/g' \
    /opt/puter/app/src/gui/dist/bundle.min.js && \
    sed -i 's/app-7bdca1a4-6373-4c98-ad97-03ff2d608ca1/disabled-recorder/g' \
    /opt/puter/app/src/gui/dist/bundle.min.js
