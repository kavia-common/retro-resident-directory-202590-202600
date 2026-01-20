# Resident Directory SQLite Schema (v1)

This database uses SQLite (`myapp.db`) and is intended to support the Resident Directory app.

Connection info is tracked in:
- `db_connection.txt`

Helper scripts:
- `init_db.py` (creates `myapp.db` if missing and writes `db_connection.txt`)
- `db_shell.py` (interactive shell)
- `test_db.py` (connectivity test)

## Tables

### `schema_migrations`
Tracks applied schema versions.

- `id` INTEGER PK
- `name` TEXT UNIQUE NOT NULL
- `applied_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP

### `buildings`
Buildings/properties.

- `id` INTEGER PK
- `code` TEXT UNIQUE NOT NULL (e.g., "SUNSET")
- `name` TEXT NOT NULL
- `address_line1`, `address_line2`, `city`, `state`, `postal_code`
- `created_at`, `updated_at`

### `units`
Units within buildings.

- `id` INTEGER PK
- `building_id` INTEGER NOT NULL REFERENCES `buildings(id)` ON DELETE CASCADE
- `unit_number` TEXT NOT NULL
- `floor` TEXT
- `notes` TEXT
- `created_at`, `updated_at`
- UNIQUE(`building_id`, `unit_number`)

### `residents`
Main resident directory table.

- `id` INTEGER PK
- `first_name` TEXT NOT NULL
- `last_name` TEXT NOT NULL
- `preferred_name` TEXT
- `display_name` TEXT GENERATED ALWAYS AS (...) VIRTUAL
- `phone` TEXT
- `email` TEXT
- `unit_id` INTEGER REFERENCES `units(id)` ON DELETE SET NULL
- `move_in_date` TEXT (ISO-8601 date string)
- `status` TEXT NOT NULL DEFAULT 'active' CHECK IN ('active','inactive','moved_out')
- `notes` TEXT
- `created_at`, `updated_at`

### `tags`
Simple tag taxonomy.

- `id` INTEGER PK
- `name` TEXT UNIQUE NOT NULL
- `color` TEXT
- `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP

### `resident_tags`
Many-to-many between residents and tags.

- `resident_id` INTEGER NOT NULL REFERENCES `residents(id)` ON DELETE CASCADE
- `tag_id` INTEGER NOT NULL REFERENCES `tags(id)` ON DELETE CASCADE
- `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
- PRIMARY KEY(`resident_id`, `tag_id`)

## Indexes

- `idx_residents_last_first` on `residents(last_name, first_name)`
- `idx_residents_status` on `residents(status)`
- `idx_residents_unit_id` on `residents(unit_id)`
- `idx_units_building_id` on `units(building_id)`
- `idx_tags_name` on `tags(name)`
- `idx_resident_tags_tag_id` on `resident_tags(tag_id)`
- `idx_resident_search_email` on `residents(email)`
- `idx_resident_search_phone` on `residents(phone)`

## Seed Data (sample)

- Buildings: SUNSET, OAK
- Units: a few units across those buildings
- Residents: 5 sample residents across those units
- Tags: Board Member, Maintenance, VIP
- Resident-tag links for a few residents

## Notes

- Existing `app_info` and `users` tables created by `init_db.py` remain present for template compatibility.
- Schema + seeds are applied idempotently (CREATE IF NOT EXISTS, INSERT OR IGNORE / existence checks).
