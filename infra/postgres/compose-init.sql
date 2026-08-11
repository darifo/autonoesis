-- Local Compose login roles only. Production credentials must be provisioned by
-- the deployment secret manager and must only inherit the NOLOGIN roles above.

\ir /docker-entrypoint-initdb.d/roles.sql

CREATE ROLE autonoesis_api LOGIN PASSWORD 'autonoesis-local-only' IN ROLE autonoesis_app;
CREATE ROLE autonoesis_worker LOGIN PASSWORD 'autonoesis-local-only' IN ROLE autonoesis_app;
CREATE ROLE autonoesis_outbox LOGIN PASSWORD 'autonoesis-local-only' IN ROLE autonoesis_relay;
CREATE ROLE autonoesis_auditor LOGIN PASSWORD 'autonoesis-local-only' IN ROLE autonoesis_audit;
CREATE ROLE autonoesis_migrator LOGIN PASSWORD 'autonoesis-local-only' IN ROLE autonoesis_migration;

GRANT autonoesis_migration TO autonoesis, autonoesis_migrator;
