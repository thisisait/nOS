// ==============================================================================
// jsOS – Bluesky AT Protocol auth adapter
// Login: handle (e.g. user.bsky.social) + app password
// Validace: XRPC com.atproto.server.createSession
// Storage: PostgreSQL tabulka jsos_users (upsert při každém loginu)
// ==============================================================================

const { Client: PgClient } = require('pg');

module.exports = (core, config) => {
  const provision = require('./provision')(core, config.provision || {});

  // Lazy-init DB pool
  let _pool = null;
  const getPool = () => {
    if (!_pool) {
      const { Pool } = require('pg');
      _pool = new Pool({
        host: config.db.host || '127.0.0.1',
        port: config.db.port || 5432,
        user: config.db.user,
        password: config.db.password,
        database: config.db.database,
        max: 5,
      });
    }
    return _pool;
  };

  // Ensure users table exists
  const ensureTable = async () => {
    const pool = getPool();
    await pool.query(`
      CREATE TABLE IF NOT EXISTS jsos_users (
        did TEXT PRIMARY KEY,
        handle TEXT NOT NULL UNIQUE,
        display_name TEXT,
        avatar_url TEXT,
        groups TEXT[] DEFAULT ARRAY['user'],
        created_at TIMESTAMPTZ DEFAULT NOW(),
        last_login TIMESTAMPTZ DEFAULT NOW()
      )
    `);
  };

  let tableReady = false;

  // Resolve handle to PDS service URL via DNS/HTTP
  const resolvePds = async (handle) => {
    // Try well-known DID resolution first
    try {
      const https = require('https');
      const http = require('http');
      const url = `https://${handle}/.well-known/atproto-did`;
      const fetch = globalThis.fetch || require('node-fetch');
      const res = await fetch(url, { signal: AbortSignal.timeout(5000) });
      if (res.ok) {
        const did = (await res.text()).trim();
        if (did.startsWith('did:')) {
          return { did, pds: config.pdsUrl || 'https://bsky.social' };
        }
      }
    } catch {
      // Fall through to default PDS
    }
    return { did: null, pds: config.pdsUrl || 'https://bsky.social' };
  };

  return {
    async login(req, res) {
      const { username, password } = req.body;

      if (!username || !password) {
        return false;
      }

      try {
        // Resolve PDS for this handle
        const { pds } = await resolvePds(username);

        // Validate credentials via AT Protocol XRPC
        const atproto = require('@atproto/api');
        const AgentClass = atproto.AtpAgent || atproto.Agent || atproto.BskyAgent;
        const agent = new AgentClass({ service: pds });

        const session = await agent.login({
          identifier: username,
          password: password,
        });

        const did = session.data.did;
        const handle = session.data.handle;

        // Fetch profile for display name + avatar
        let displayName = handle;
        let avatarUrl = null;
        try {
          const profile = await agent.getProfile({ actor: did });
          displayName = profile.data.displayName || handle;
          avatarUrl = profile.data.avatar || null;
        } catch {
          // Profile fetch is optional
        }

        // Determine groups
        const adminHandles = config.adminHandles || [];
        const groups = adminHandles.includes(handle)
          ? ['admin', 'user']
          : ['user'];

        // Ensure DB table
        if (!tableReady) {
          await ensureTable();
          tableReady = true;
        }

        // Upsert user in PostgreSQL
        const pool = getPool();
        await pool.query(`
          INSERT INTO jsos_users (did, handle, display_name, avatar_url, groups, last_login)
          VALUES ($1, $2, $3, $4, $5, NOW())
          ON CONFLICT (did) DO UPDATE SET
            handle = EXCLUDED.handle,
            display_name = EXCLUDED.display_name,
            avatar_url = EXCLUDED.avatar_url,
            groups = EXCLUDED.groups,
            last_login = NOW()
        `, [did, handle, displayName, avatarUrl, groups]);

        const user = {
          id: did,
          username: handle,
          name: displayName,
          groups,
        };

        // Provision per-user resources (idempotent)
        try {
          await provision(user);
        } catch (err) {
          core.logger.warn(`[jsOS] Provisioning warning for ${handle}: ${err.message}`);
        }

        core.logger.info(`[jsOS] Login OK: ${handle} (${did})`);
        return user;

      } catch (err) {
        core.logger.warn(`[jsOS] Auth failed for ${username}: ${err.message}`);
        return false;
      }
    },

    async logout(req, res) {
      return true;
    },
  };
};
