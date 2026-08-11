-- Ephemeral CI login roles. Never use these credentials outside CI.
\ir roles.sql

CREATE ROLE autonoesis_api LOGIN PASSWORD 'autonoesis-ci-only' IN ROLE autonoesis_app;
CREATE ROLE autonoesis_worker LOGIN PASSWORD 'autonoesis-ci-only' IN ROLE autonoesis_app;
CREATE ROLE autonoesis_migrator LOGIN PASSWORD 'autonoesis-ci-only' IN ROLE autonoesis_migration;
GRANT autonoesis_migration TO autonoesis, autonoesis_migrator;
