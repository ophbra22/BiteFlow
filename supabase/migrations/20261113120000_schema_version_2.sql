-- Run as the database owner after 20261011194917_apple_sign_in.sql.
-- Marks databases that contain the Apple sign-in tables as schema version 2, so the
-- server can verify at startup that the migration was applied. Additive and
-- idempotent: no table, row or permission other than the version marker changes.
UPDATE foodlogger.schema_version SET version = 2 WHERE id = 1 AND version = 1;
