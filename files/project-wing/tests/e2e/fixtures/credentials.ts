/**
 * Centralized credentials loader for e2e tests.
 *
 * Credentials come from env vars — set them either in ~/glasswing/.env
 * (written by Ansible glasswing role) or in tests/.env for local override.
 * Never hard-code secrets. Never commit tests/.env.
 *
 * All credentials are OPTIONAL — if a test's required env is not present,
 * the test is skipped gracefully rather than failing.
 */

export interface ServiceCreds {
  url: string;
  username: string;
  password: string;
  email?: string;
}

function req(name: string): string | undefined {
  const value = process.env[name];
  return value && value.length > 0 ? value : undefined;
}

function or(...candidates: (string | undefined)[]): string | undefined {
  for (const c of candidates) if (c) return c;
  return undefined;
}

/** Load credentials for a named service; returns null if env is missing. */
export function loadCreds(service: 'metabase' | 'jellyfin' | 'openwebui' | 'portainer' | 'uptime_kuma'): ServiceCreds | null {
  const baseDomain = process.env.DEV_DOMAIN || 'dev.local';

  switch (service) {
    case 'metabase': {
      const password = or(req('METABASE_ADMIN_PASSWORD'), req('SERVICE_ADMIN_PASSWORD'));
      const url = req('METABASE_URL') || `https://bi.${baseDomain}`;
      const username = req('METABASE_ADMIN_EMAIL') || `admin@${baseDomain}`;
      if (!password) return null;
      return { url, username, password, email: username };
    }
    case 'jellyfin': {
      const password = or(req('JELLYFIN_ADMIN_PASSWORD'), req('SERVICE_ADMIN_PASSWORD'));
      const url = req('JELLYFIN_URL') || `https://media.${baseDomain}`;
      const username = req('JELLYFIN_ADMIN_USER') || 'admin';
      if (!password) return null;
      return { url, username, password };
    }
    case 'openwebui': {
      const password = or(req('OPENWEBUI_ADMIN_PASSWORD'), req('SERVICE_ADMIN_PASSWORD'));
      const url = req('OPENWEBUI_URL') || `https://ai.${baseDomain}`;
      const email = req('OPENWEBUI_ADMIN_EMAIL') || `admin@${baseDomain}`;
      if (!password) return null;
      return { url, username: email, password, email };
    }
    case 'portainer': {
      const password = or(req('PORTAINER_ADMIN_PASSWORD'), req('SERVICE_ADMIN_PASSWORD'));
      const url = req('PORTAINER_URL') || `https://portainer.${baseDomain}`;
      const username = req('PORTAINER_ADMIN_USER') || 'admin';
      if (!password) return null;
      return { url, username, password };
    }
    case 'uptime_kuma': {
      const password = or(req('UPTIME_KUMA_ADMIN_PASSWORD'), req('SERVICE_ADMIN_PASSWORD'));
      const url = req('UPTIME_KUMA_URL') || `http://127.0.0.1:3001`;
      const username = req('UPTIME_KUMA_ADMIN_USER') || 'admin';
      if (!password) return null;
      return { url, username, password };
    }
  }
}

/** Returns true if the test should run (all required env present). */
export function hasCreds(...services: Parameters<typeof loadCreds>[0][]): boolean {
  return services.every(s => loadCreds(s) !== null);
}
