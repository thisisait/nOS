// ==============================================================================
// jsOS – S3 VFS adapter pro RustFS / MinIO
// Per-user buckety: jsos-{sanitized_handle}
// OS.js VFS interface: readdir, readfile, writefile, copy, rename, mkdir,
//                      unlink, exists, stat, search
// ==============================================================================

const {
  S3Client,
  ListObjectsV2Command,
  GetObjectCommand,
  PutObjectCommand,
  DeleteObjectCommand,
  HeadObjectCommand,
  CopyObjectCommand,
} = require('@aws-sdk/client-s3');
const path = require('path');

// Lightweight MIME lookup (no external dependency)
const MIME_MAP = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
  '.json': 'application/json', '.xml': 'application/xml', '.csv': 'text/csv',
  '.txt': 'text/plain', '.md': 'text/markdown', '.yaml': 'text/yaml',
  '.yml': 'text/yaml', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
  '.webp': 'image/webp', '.ico': 'image/x-icon', '.pdf': 'application/pdf',
  '.zip': 'application/zip', '.gz': 'application/gzip',
  '.tar': 'application/x-tar', '.mp3': 'audio/mpeg', '.mp4': 'video/mp4',
  '.webm': 'video/webm', '.ogg': 'audio/ogg', '.wav': 'audio/wav',
  '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf',
};

const getMime = (filename) => {
  const ext = path.extname(filename).toLowerCase();
  return MIME_MAP[ext] || 'application/octet-stream';
};

// Sanitize Bluesky handle → S3 bucket name
const toBucketName = (handle) => {
  return 'jsos-' + handle
    .replace(/\./g, '-')
    .replace(/[^a-z0-9-]/gi, '')
    .toLowerCase()
    .substring(0, 50);
};

// Extract S3 key from OS.js VFS path (e.g. "cloud:/docs/file.txt" → "docs/file.txt")
const toKey = (vfsPath) => {
  const idx = vfsPath.indexOf(':/');
  const raw = idx >= 0 ? vfsPath.substring(idx + 2) : vfsPath;
  const cleaned = raw.replace(/^\/+/, '');
  const normalized = path.posix.normalize(cleaned);
  if (normalized.startsWith('..') || normalized.includes('/../')) {
    throw new Error('Path traversal not allowed');
  }
  return normalized;
};

module.exports = (core) => {
  let _client = null;

  const getClient = (vfs) => {
    if (!_client) {
      const attrs = vfs.mount.attributes || {};
      _client = new S3Client({
        region: 'us-east-1',
        endpoint: attrs.endpoint,
        credentials: {
          accessKeyId: attrs.accessKey,
          secretAccessKey: attrs.secretKey,
        },
        forcePathStyle: true,
      });
    }
    return _client;
  };

  const getBucket = (vfs) => {
    const username = vfs.req?.session?.user?.username || 'default';
    return toBucketName(username);
  };

  return {
    // ── readdir ─────────────────────────────────────────────────────────────
    readdir: (vfs) => async (dirPath) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      const prefix = toKey(dirPath);
      const normPrefix = prefix ? (prefix.endsWith('/') ? prefix : prefix + '/') : '';

      const cmd = new ListObjectsV2Command({
        Bucket: bucket,
        Prefix: normPrefix,
        Delimiter: '/',
      });

      const result = await s3.send(cmd);
      const items = [];

      // Directories
      if (result.CommonPrefixes) {
        for (const cp of result.CommonPrefixes) {
          const name = cp.Prefix.replace(normPrefix, '').replace(/\/$/, '');
          if (name) {
            items.push({
              isDirectory: true,
              isFile: false,
              path: dirPath.replace(/\/$/, '') + '/' + name,
              filename: name,
              mime: null,
              size: 0,
            });
          }
        }
      }

      // Files
      if (result.Contents) {
        for (const obj of result.Contents) {
          const name = obj.Key.replace(normPrefix, '');
          if (name && !name.includes('/')) {
            items.push({
              isDirectory: false,
              isFile: true,
              path: dirPath.replace(/\/$/, '') + '/' + name,
              filename: name,
              mime: getMime(name),
              size: obj.Size || 0,
            });
          }
        }
      }

      return items;
    },

    // ── readfile ────────────────────────────────────────────────────────────
    readfile: (vfs) => async (filePath) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      const cmd = new GetObjectCommand({ Bucket: bucket, Key: toKey(filePath) });
      const result = await s3.send(cmd);
      return result.Body;
    },

    // ── writefile ───────────────────────────────────────────────────────────
    writefile: (vfs) => async (filePath, stream) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      const key = toKey(filePath);

      // Collect stream into buffer
      const chunks = [];
      for await (const chunk of stream) {
        chunks.push(chunk);
      }
      const body = Buffer.concat(chunks);

      await s3.send(new PutObjectCommand({
        Bucket: bucket,
        Key: key,
        Body: body,
        ContentType: getMime(key),
      }));

      return body.length;
    },

    // ── copy ────────────────────────────────────────────────────────────────
    copy: (vfs) => async (from, to) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      await s3.send(new CopyObjectCommand({
        Bucket: bucket,
        CopySource: `${bucket}/${toKey(from)}`,
        Key: toKey(to),
      }));
      return true;
    },

    // ── rename ──────────────────────────────────────────────────────────────
    rename: (vfs) => async (from, to) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      const fromKey = toKey(from);
      const toKey_ = toKey(to);

      await s3.send(new CopyObjectCommand({
        Bucket: bucket,
        CopySource: `${bucket}/${fromKey}`,
        Key: toKey_,
      }));
      await s3.send(new DeleteObjectCommand({
        Bucket: bucket,
        Key: fromKey,
      }));
      return true;
    },

    // ── mkdir ────────────────────────────────────────────────────────────────
    mkdir: (vfs) => async (dirPath) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      const key = toKey(dirPath);
      const dirKey = key.endsWith('/') ? key : key + '/';

      await s3.send(new PutObjectCommand({
        Bucket: bucket,
        Key: dirKey,
        Body: '',
      }));
      return true;
    },

    // ── unlink ──────────────────────────────────────────────────────────────
    unlink: (vfs) => async (filePath) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      await s3.send(new DeleteObjectCommand({
        Bucket: bucket,
        Key: toKey(filePath),
      }));
      return true;
    },

    // ── exists ──────────────────────────────────────────────────────────────
    exists: (vfs) => async (filePath) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      const key = toKey(filePath);

      try {
        await s3.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
        return true;
      } catch {
        try {
          await s3.send(new HeadObjectCommand({ Bucket: bucket, Key: key + '/' }));
          return true;
        } catch {
          return false;
        }
      }
    },

    // ── stat ────────────────────────────────────────────────────────────────
    stat: (vfs) => async (filePath) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      const key = toKey(filePath);
      const filename = path.basename(key);

      try {
        const result = await s3.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
        return {
          isDirectory: false,
          isFile: true,
          mime: result.ContentType || getMime(key),
          size: result.ContentLength || 0,
          path: filePath,
          filename,
        };
      } catch {
        return {
          isDirectory: true,
          isFile: false,
          mime: null,
          size: 0,
          path: filePath,
          filename,
        };
      }
    },

    // ── search ──────────────────────────────────────────────────────────────
    search: (vfs) => async (root, pattern) => {
      const s3 = getClient(vfs);
      const bucket = getBucket(vfs);
      const prefix = toKey(root);
      const regex = new RegExp(pattern.replace(/\*/g, '.*'), 'i');

      const cmd = new ListObjectsV2Command({ Bucket: bucket, Prefix: prefix });
      const result = await s3.send(cmd);
      const mountName = root.split(':')[0];

      return (result.Contents || [])
        .filter((obj) => regex.test(path.basename(obj.Key)))
        .slice(0, 100)
        .map((obj) => ({
          isDirectory: false,
          isFile: true,
          path: mountName + ':/' + obj.Key,
          filename: path.basename(obj.Key),
          mime: getMime(obj.Key),
          size: obj.Size || 0,
        }));
    },
  };
};
