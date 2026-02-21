"""
setup_db.py

Create the knowledge base database and apply the schema.

Usage:
  conda activate openai
  python setup_db.py                        # creates db 'mngs_kb', applies schema
  python setup_db.py --dbname my_kb         # use a different db name
  python setup_db.py --drop-existing        # drop and recreate if db already exists

Connection defaults (override with env vars or flags):
  PGHOST     localhost
  PGPORT     5432
  PGUSER     current OS user
  PGPASSWORD (none, uses peer/trust auth)
"""

import argparse
import os
import sys
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_conn_params(dbname: str = "postgres") -> dict:
    return {
        "host":     os.environ.get("PGHOST", "localhost"),
        "port":     int(os.environ.get("PGPORT", 5432)),
        "user":     os.environ.get("PGUSER", os.environ.get("USER", "")),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname":   dbname,
    }


def db_exists(dbname: str) -> bool:
    params = get_conn_params("postgres")
    conn = psycopg2.connect(**{k: v for k, v in params.items() if v != ""})
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def create_db(dbname: str):
    params = get_conn_params("postgres")
    conn = psycopg2.connect(**{k: v for k, v in params.items() if v != ""})
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    cur.close()
    conn.close()
    print(f"Created database '{dbname}'")


def drop_db(dbname: str):
    params = get_conn_params("postgres")
    conn = psycopg2.connect(**{k: v for k, v in params.items() if v != ""})
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    # Terminate any existing connections first
    cur.execute("""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = %s AND pid <> pg_backend_pid()
    """, (dbname,))
    cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(dbname)))
    cur.close()
    conn.close()
    print(f"Dropped database '{dbname}'")


def apply_schema(dbname: str, schema_path: str):
    params = get_conn_params(dbname)
    conn = psycopg2.connect(**{k: v for k, v in params.items() if v != ""})
    with open(schema_path, "r") as f:
        schema_sql = f.read()
    cur = conn.cursor()
    cur.execute(schema_sql)
    conn.commit()
    cur.close()
    conn.close()
    print(f"Schema applied from {schema_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name to create (default: mngs_kb)")
    parser.add_argument("--schema", default="create_schema.sql",
                        help="Path to schema SQL file (default: create_schema.sql)")
    parser.add_argument("--drop-existing", action="store_true",
                        help="Drop and recreate the database if it already exists")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    schema_path = args.schema if os.path.isabs(args.schema) \
        else os.path.join(script_dir, args.schema)

    if not os.path.exists(schema_path):
        sys.exit(f"Schema file not found: {schema_path}")

    # Handle existing db
    if db_exists(args.dbname):
        if args.drop_existing:
            drop_db(args.dbname)
        else:
            print(f"Database '{args.dbname}' already exists.")
            answer = input("Apply schema to existing database? [y/N] ").strip().lower()
            if answer != "y":
                print("Aborted. Use --drop-existing to recreate from scratch.")
                return

    # Create if needed
    if not db_exists(args.dbname):
        create_db(args.dbname)

    # Apply schema
    apply_schema(args.dbname, schema_path)

    print(f"\nDatabase '{args.dbname}' is ready.")
    print(f"Connect with: psql {args.dbname}")


if __name__ == "__main__":
    main()
