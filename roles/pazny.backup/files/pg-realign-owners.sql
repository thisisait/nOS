-- Every relation back to the db owner; owned sequences follow their table. ONE copy:
-- tasks/_restore_postgres_db.yml feeds it to psql, backup-verify.sh includes it (10-31:
-- Paperclip's dump carried 3 tables OWNER TO postgres and the app restarted 74x).
SELECT format('ALTER %s %I.%I OWNER TO %I',
              CASE c.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END,
              n.nspname, c.relname, pg_get_userbyid(d.datdba))
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_database d ON d.datname = current_database()
WHERE c.relkind IN ('r', 'p', 'S', 'v', 'm') AND c.relowner <> d.datdba
  AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'
  AND NOT (c.relkind = 'S' AND EXISTS (SELECT 1 FROM pg_depend dp
           WHERE dp.objid = c.oid AND dp.classid = 'pg_class'::regclass AND dp.deptype IN ('a', 'i')))
\gexec
