"""Provision a Tenant Authority record with migration-owner credentials."""

import argparse
import os
import re
from uuid import UUID

from sqlalchemy import create_engine, text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--name", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.name.strip():
        raise ValueError("tenant name must not be empty")
    database_url = os.environ["AUTONOESIS_MIGRATION_DATABASE_URL"]
    migration_role = os.getenv("AUTONOESIS_MIGRATION_ROLE")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            if migration_role:
                if re.fullmatch(r"[a-z_][a-z0-9_]*", migration_role) is None:
                    raise ValueError("AUTONOESIS_MIGRATION_ROLE is not a safe identifier")
                connection.execute(text(f'SET ROLE "{migration_role}"'))
            connection.execute(
                text(
                    """INSERT INTO tenants (id, name, created_at)
                    VALUES (:tenant_id, :name, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"""
                ),
                {"tenant_id": str(args.tenant_id), "name": args.name},
            )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
