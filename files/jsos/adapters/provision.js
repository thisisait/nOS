// ==============================================================================
// jsOS – Per-user resource provisioning (idempotent)
// Spouští se při každém loginu, ale vytváří prostředky pouze jednou.
//
// Provisioned resources:
//   1. VFS home directory:   {vfsRoot}/{handle}/
//   2. S3 bucket:            jsos-{sanitized_handle}  (pokud RustFS enabled)
//   3. PostgreSQL database:  jsos_{sanitized_handle}   (pokud enabled)
//   4. Redis namespace:      jsos:user:{handle}:*      (informační, nepotřebuje setup)
// ==============================================================================

const fs = require('fs');
const path = require('path');

// Sanitize handle for resource names (bucket, DB, role)
const sanitize = (handle) => {
  return handle
    .replace(/\./g, '_')
    .replace(/[^a-z0-9_]/gi, '')
    .toLowerCase()
    .substring(0, 50);
};

// Sanitize for S3 bucket (lowercase, hyphens, 3-63 chars)
const toBucketName = (handle) => {
  return 'jsos-' + handle
    .replace(/\./g, '-')
    .replace(/[^a-z0-9-]/gi, '')
    .toLowerCase()
    .substring(0, 50);
};

module.exports = (core, config) => {
  return async (user) => {
    const handle = user.username;
    const safe = sanitize(handle);

    // ── 1. VFS home directory ───────────────────────────────────────────────
    if (config.vfsRoot) {
      const homeDir = path.join(config.vfsRoot, safe);
      if (!fs.existsSync(homeDir)) {
        fs.mkdirSync(homeDir, { recursive: true });
        // Create default directories
        for (const sub of ['Documents', 'Desktop', 'Downloads']) {
          fs.mkdirSync(path.join(homeDir, sub), { recursive: true });
        }
        core.logger.info(`[jsOS:provision] VFS home: ${homeDir}`);
      }
    }

    // ── 2. S3 bucket (RustFS) ───────────────────────────────────────────────
    if (config.s3 && config.s3.enabled) {
      try {
        const {
          S3Client,
          CreateBucketCommand,
          HeadBucketCommand,
        } = require('@aws-sdk/client-s3');

        const s3 = new S3Client({
          region: 'us-east-1',
          endpoint: config.s3.endpoint,
          credentials: {
            accessKeyId: config.s3.accessKey,
            secretAccessKey: config.s3.secretKey,
          },
          forcePathStyle: true,
        });

        const bucketName = toBucketName(handle);

        try {
          await s3.send(new HeadBucketCommand({ Bucket: bucketName }));
          // Bucket already exists
        } catch {
          await s3.send(new CreateBucketCommand({ Bucket: bucketName }));
          core.logger.info(`[jsOS:provision] S3 bucket: ${bucketName}`);
        }
      } catch (err) {
        core.logger.warn(`[jsOS:provision] S3 error: ${err.message}`);
      }
    }

    // ── 3. PostgreSQL per-user database ─────────────────────────────────────
    if (config.db && config.db.provisionPerUser) {
      const { Client: PgClient } = require('pg');
      const pg = new PgClient({
        host: config.db.host || '127.0.0.1',
        port: config.db.port || 5432,
        user: config.db.adminUser,
        password: config.db.adminPassword,
        database: 'postgres',
      });

      try {
        await pg.connect();
        const dbName = `jsos_${safe}`;
        const roleName = `jsos_${safe}`;

        // Generate deterministic password from prefix + safe name (no user input in DDL)
        const crypto = require('crypto');
        const userPw = crypto.createHash('sha256')
          .update(`${config.db.userPasswordPrefix || 'jsos'}_${safe}`)
          .digest('hex')
          .substring(0, 32);

        // Create role if not exists (roleName is sanitized [a-z0-9_], userPw is hex hash)
        await pg.query(
          `DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${roleName}') THEN
              CREATE ROLE "${roleName}" WITH LOGIN PASSWORD '${userPw}';
            END IF;
          END $$`
        );

        // Create database if not exists
        const dbCheck = await pg.query(
          'SELECT 1 FROM pg_database WHERE datname = $1',
          [dbName]
        );
        if (dbCheck.rowCount === 0) {
          await pg.query(`CREATE DATABASE "${dbName}" OWNER "${roleName}"`);
          core.logger.info(`[jsOS:provision] PostgreSQL DB: ${dbName}`);
        }
      } catch (err) {
        core.logger.warn(`[jsOS:provision] DB error: ${err.message}`);
      } finally {
        await pg.end();
      }
    }

    // ── 4. Redis namespace (informational only) ─────────────────────────────
    // Redis nevyžaduje explicit provisioning — prefix jsos:user:{handle}:
    // je pouze konvence. Client-side info se předává přes /api/user/resources.
  };
};
