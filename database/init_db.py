#!/usr/bin/env python3
"""Initialize SQLite database for database.

This script is used by previews/CI to ensure the SQLite database file exists and
contains the required schema and seed data for the Resident Directory app.

It also maintains helper artifacts:
- db_connection.txt (human-readable connection info)
- db_visualizer/sqlite.env (used by the db_visualizer Node app)
"""

import os
import sqlite3
from typing import Iterable, Tuple

DB_NAME = "myapp.db"
DB_USER = "kaviasqlite"  # Not used for SQLite, but kept for consistency
DB_PASSWORD = "kaviadefaultpassword"  # Not used for SQLite, but kept for consistency
DB_PORT = "5000"  # Not used for SQLite, but kept for consistency

# A simple schema version record to ensure we can re-run idempotently while still
# having a durable "migration applied" marker.
RESIDENT_DIRECTORY_MIGRATION_NAME = "resident_directory_v1"


def _exec_many(cursor: sqlite3.Cursor, statements: Iterable[str]) -> None:
    """Execute statements sequentially.

    SQLite's Python driver can execute multi-line statements, but we keep it as a
    list to make the workflow explicit and easy to maintain.
    """
    for stmt in statements:
        cursor.execute(stmt)


def _ensure_template_tables(cursor: sqlite3.Cursor) -> None:
    """Create template compatibility tables that existed previously."""
    _exec_many(
        cursor,
        [
            """
            CREATE TABLE IF NOT EXISTS app_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ],
    )


def _ensure_migrations_table(cursor: sqlite3.Cursor) -> None:
    """Create schema_migrations table used to track applied schema versions."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _apply_resident_directory_schema(cursor: sqlite3.Cursor) -> None:
    """Apply Resident Directory schema and indexes (idempotent)."""

    # Core tables
    _exec_many(
        cursor,
        [
            """
            CREATE TABLE IF NOT EXISTS buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                address_line1 TEXT,
                address_line2 TEXT,
                city TEXT,
                state TEXT,
                postal_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
                unit_number TEXT NOT NULL,
                floor TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(building_id, unit_number)
            )
            """,
            # NOTE: display_name is GENERATED ALWAYS AS VIRTUAL, which is supported by
            # modern SQLite versions (including the one used in previews here).
            """
            CREATE TABLE IF NOT EXISTS residents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                preferred_name TEXT,
                display_name TEXT GENERATED ALWAYS AS (
                    trim(
                        coalesce(preferred_name, '') ||
                        case
                            when preferred_name is not null and preferred_name != '' then ' '
                            else ''
                        end ||
                        first_name || ' ' || last_name
                    )
                ) VIRTUAL,
                phone TEXT,
                email TEXT,
                unit_id INTEGER REFERENCES units(id) ON DELETE SET NULL,
                move_in_date TEXT,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','moved_out')),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS resident_tags (
                resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(resident_id, tag_id)
            )
            """,
        ],
    )

    # Indexes (idempotent)
    _exec_many(
        cursor,
        [
            "CREATE INDEX IF NOT EXISTS idx_residents_last_first ON residents(last_name, first_name)",
            "CREATE INDEX IF NOT EXISTS idx_residents_status ON residents(status)",
            "CREATE INDEX IF NOT EXISTS idx_residents_unit_id ON residents(unit_id)",
            "CREATE INDEX IF NOT EXISTS idx_units_building_id ON units(building_id)",
            "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)",
            "CREATE INDEX IF NOT EXISTS idx_resident_tags_tag_id ON resident_tags(tag_id)",
            "CREATE INDEX IF NOT EXISTS idx_resident_search_email ON residents(email)",
            "CREATE INDEX IF NOT EXISTS idx_resident_search_phone ON residents(phone)",
        ],
    )


def _seed_app_info(cursor: sqlite3.Cursor) -> None:
    """Seed template app_info records (idempotent)."""
    cursor.execute(
        "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
        ("project_name", "database"),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
        ("version", "0.1.0"),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
        ("author", "John Doe"),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
        ("description", ""),
    )


def _get_id_by_unique(
    cursor: sqlite3.Cursor, table: str, unique_col: str, unique_val: str
) -> int:
    """Get a row's ID using a unique column value; raise if not found."""
    cursor.execute(f"SELECT id FROM {table} WHERE {unique_col} = ?", (unique_val,))
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(
            f"Expected row in {table} where {unique_col}={unique_val!r}, but none found."
        )
    return int(row[0])


def _seed_resident_directory(cursor: sqlite3.Cursor) -> None:
    """Seed sample buildings/units/residents/tags (idempotent)."""

    # Buildings
    buildings: Tuple[Tuple[str, str, str, str, str, str, str], ...] = (
        ("SUNSET", "Sunset Towers", "123 Sunset Blvd", "", "Retro City", "CA", "90210"),
        ("OAK", "Oak Ridge", "45 Oak St", "Bldg A", "Retro City", "CA", "90211"),
    )
    for code, name, a1, a2, city, state, postal in buildings:
        cursor.execute(
            """
            INSERT OR IGNORE INTO buildings
                (code, name, address_line1, address_line2, city, state, postal_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (code, name, a1, a2, city, state, postal),
        )

    # Units
    sunset_id = _get_id_by_unique(cursor, "buildings", "code", "SUNSET")
    oak_id = _get_id_by_unique(cursor, "buildings", "code", "OAK")

    units = (
        (sunset_id, "101", "1", ""),
        (sunset_id, "102", "1", ""),
        (sunset_id, "201", "2", "Corner unit"),
        (oak_id, "A1", "1", ""),
        (oak_id, "B2", "2", ""),
    )
    for building_id, unit_number, floor, notes in units:
        cursor.execute(
            """
            INSERT OR IGNORE INTO units (building_id, unit_number, floor, notes)
            VALUES (?, ?, ?, ?)
            """,
            (building_id, unit_number, floor, notes),
        )

    # Helper: unit ids by (building_code, unit_number)
    def unit_id(building_code: str, unit_number: str) -> int:
        bid = _get_id_by_unique(cursor, "buildings", "code", building_code)
        cursor.execute(
            "SELECT id FROM units WHERE building_id=? AND unit_number=?",
            (bid, unit_number),
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError(
                f"Expected unit for building_code={building_code!r}, unit_number={unit_number!r}."
            )
        return int(row[0])

    # Residents (use INSERT OR IGNORE on email, but schema doesn't enforce unique email.
    # Instead, we do a presence check by (first,last,unit_id) which is stable for the sample set.
    residents = (
        ("Alice", "Anderson", "Ally", "555-0101", "alice@example.com", unit_id("SUNSET", "101"), "2023-06-01", "active", "Loves bingo night."),
        ("Bob", "Baker", None, "555-0102", "bob@example.com", unit_id("SUNSET", "102"), "2022-03-15", "active", ""),
        ("Carol", "Clark", "CC", "555-0103", "carol@example.com", unit_id("SUNSET", "201"), "2021-11-20", "inactive", "On extended travel."),
        ("Dave", "Dawson", None, "555-0201", "dave@example.com", unit_id("OAK", "A1"), "2020-01-05", "active", ""),
        ("Eve", "Edwards", None, "555-0202", "eve@example.com", unit_id("OAK", "B2"), "2019-09-10", "moved_out", "Moved to assisted living."),
    )

    for first, last, pref, phone, email, u_id, move_in, status, notes in residents:
        cursor.execute(
            """
            SELECT 1
            FROM residents
            WHERE first_name=? AND last_name=? AND coalesce(unit_id, -1)=coalesce(?, -1)
            """,
            (first, last, u_id),
        )
        exists = cursor.fetchone() is not None
        if not exists:
            cursor.execute(
                """
                INSERT INTO residents
                    (first_name, last_name, preferred_name, phone, email, unit_id, move_in_date, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (first, last, pref, phone, email, u_id, move_in, status, notes),
            )

    # Tags
    tags = (
        ("Board Member", "#3b82f6"),
        ("Maintenance", "#06b6d4"),
        ("VIP", "#f59e0b"),
    )
    for name, color in tags:
        cursor.execute(
            "INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)",
            (name, color),
        )

    # Resident-tag links (idempotent via composite PK)
    def resident_id_by_email(email_addr: str) -> int:
        cursor.execute("SELECT id FROM residents WHERE email=?", (email_addr,))
        row = cursor.fetchone()
        if not row:
            raise RuntimeError(f"Expected resident with email={email_addr!r}.")
        return int(row[0])

    tag_board = _get_id_by_unique(cursor, "tags", "name", "Board Member")
    tag_maint = _get_id_by_unique(cursor, "tags", "name", "Maintenance")
    tag_vip = _get_id_by_unique(cursor, "tags", "name", "VIP")

    links = (
        (resident_id_by_email("alice@example.com"), tag_vip),
        (resident_id_by_email("bob@example.com"), tag_maint),
        (resident_id_by_email("carol@example.com"), tag_board),
    )
    for rid, tid in links:
        cursor.execute(
            "INSERT OR IGNORE INTO resident_tags (resident_id, tag_id) VALUES (?, ?)",
            (rid, tid),
        )


def _is_migration_applied(cursor: sqlite3.Cursor, name: str) -> bool:
    """Return True if a migration row exists."""
    cursor.execute("SELECT 1 FROM schema_migrations WHERE name=?", (name,))
    return cursor.fetchone() is not None


def _record_migration(cursor: sqlite3.Cursor, name: str) -> None:
    """Insert a migration marker idempotently."""
    cursor.execute("INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)", (name,))


def main() -> None:
    """Main entrypoint to initialize the SQLite DB file and apply schema/seeds."""
    print("Starting SQLite setup...")

    # Check if database already exists
    db_exists = os.path.exists(DB_NAME)
    if db_exists:
        print(f"SQLite database already exists at {DB_NAME}")
        # Verify it's accessible
        try:
            conn = sqlite3.connect(DB_NAME)
            conn.execute("SELECT 1")
            conn.close()
            print("Database is accessible and working.")
        except Exception as e:
            print(f"Warning: Database exists but may be corrupted: {e}")
    else:
        print("Creating new SQLite database...")

    # Create/open database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Ensure foreign keys are enforced (they are OFF by default in SQLite).
    cursor.execute("PRAGMA foreign_keys = ON")

    # Ensure base tables (existing template behavior)
    _ensure_template_tables(cursor)
    _ensure_migrations_table(cursor)

    # Apply Resident Directory schema and seed data.
    # This is safe to re-run even if the migration marker exists; but we keep the
    # marker so other scripts can check for readiness.
    _apply_resident_directory_schema(cursor)

    # Seed data
    _seed_app_info(cursor)
    _seed_resident_directory(cursor)

    # Record migration marker
    if not _is_migration_applied(cursor, RESIDENT_DIRECTORY_MIGRATION_NAME):
        _record_migration(cursor, RESIDENT_DIRECTORY_MIGRATION_NAME)

    conn.commit()

    # Get database statistics
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    table_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM app_info")
    app_info_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM residents")
    residents_count = cursor.fetchone()[0]

    conn.close()

    # Save connection information to a file
    current_dir = os.getcwd()
    connection_string = f"sqlite:///{current_dir}/{DB_NAME}"

    try:
        with open("db_connection.txt", "w") as f:
            f.write("# SQLite connection methods:\n")
            f.write(f"# Python: sqlite3.connect('{DB_NAME}')\n")
            f.write(f"# Connection string: {connection_string}\n")
            f.write(f"# File path: {current_dir}/{DB_NAME}\n")
        print("Connection information saved to db_connection.txt")
    except Exception as e:
        print(f"Warning: Could not save connection info: {e}")

    # Create environment variables file for Node.js viewer
    db_path = os.path.abspath(DB_NAME)

    # Ensure db_visualizer directory exists
    if not os.path.exists("db_visualizer"):
        os.makedirs("db_visualizer", exist_ok=True)
        print("Created db_visualizer directory")

    try:
        with open("db_visualizer/sqlite.env", "w") as f:
            f.write(f'export SQLITE_DB="{db_path}"\n')
        print("Environment variables saved to db_visualizer/sqlite.env")
    except Exception as e:
        print(f"Warning: Could not save environment variables: {e}")

    print("\nSQLite setup complete!")
    print(f"Database: {DB_NAME}")
    print(f"Location: {current_dir}/{DB_NAME}")
    print("")

    print("To use with Node.js viewer, run: source db_visualizer/sqlite.env")

    print("\nTo connect to the database, use one of the following methods:")
    print(f"1. Python: sqlite3.connect('{DB_NAME}')")
    print(f"2. Connection string: {connection_string}")
    print(f"3. Direct file access: {current_dir}/{DB_NAME}")
    print("")

    print("Database statistics:")
    print(f"  Tables: {table_count}")
    print(f"  App info records: {app_info_count}")
    print(f"  Residents: {residents_count}")

    # If sqlite3 CLI is available, show how to use it
    try:
        import subprocess

        result = subprocess.run(["which", "sqlite3"], capture_output=True, text=True)
        if result.returncode == 0:
            print("")
            print("SQLite CLI is available. You can also use:")
            print(f"  sqlite3 {DB_NAME}")
    except Exception:
        pass

    # Exit successfully
    print("\nScript completed successfully.")


if __name__ == "__main__":
    main()
