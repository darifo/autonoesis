-- PostgreSQL authority roles. Run as the cluster administrator before migrations.
-- Login roles and credentials are deployment-specific and inherit one of these roles.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_migration') THEN
        CREATE ROLE autonoesis_migration NOLOGIN BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_app') THEN
        CREATE ROLE autonoesis_app NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_relay') THEN
        CREATE ROLE autonoesis_relay NOLOGIN BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_audit') THEN
        CREATE ROLE autonoesis_audit NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_breakglass') THEN
        CREATE ROLE autonoesis_breakglass NOLOGIN NOBYPASSRLS;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE autonoesis TO
    autonoesis_migration, autonoesis_app, autonoesis_relay, autonoesis_audit,
    autonoesis_breakglass;
GRANT USAGE ON SCHEMA public TO
    autonoesis_app, autonoesis_relay, autonoesis_audit, autonoesis_breakglass;
GRANT ALL ON SCHEMA public TO autonoesis_migration;

ALTER DEFAULT PRIVILEGES FOR ROLE autonoesis_migration IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO autonoesis_app;
ALTER DEFAULT PRIVILEGES FOR ROLE autonoesis_migration IN SCHEMA public
    GRANT SELECT, UPDATE ON TABLES TO autonoesis_relay;
ALTER DEFAULT PRIVILEGES FOR ROLE autonoesis_migration IN SCHEMA public
    GRANT SELECT ON TABLES TO autonoesis_audit;

-- Revision 0002 applies the object-specific grants after the tables exist.
