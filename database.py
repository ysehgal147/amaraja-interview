import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).parent / "app.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

SEED_SKILLS = ["BATTERY_FIT", "JUMPSTART", "DIAGNOSTICS"]
SEED_DATA_MESSAGE = "Data loaded from a JSON file"
SEED_SAMPLE_ITEMS = [
    (1, "First item"),
    (2, "Second item"),
    (3, "Third item"),
]
SEED_SERVICES = [
    (1, "Battery replacement", 60, "BATTERY_FIT"),
    (2, "Jump-start", 30, "JUMPSTART"),
    (3, "Battery health check", 30, "DIAGNOSTICS"),
]
SEED_ZONES = [(1, "North"), (2, "South")]
SEED_PINCODES = [
    ("110001", 1),
    ("110002", 1),
    ("110003", 1),
    ("560001", 2),
    ("560002", 2),
    ("560003", 2),
]
SEED_TECHNICIANS = [
    (1, "Aarav", 1, "08:00", "20:00"),
    (2, "Diya", 1, "08:30", "20:30"),
    (3, "Kabir", 1, "09:00", "21:00"),
    (4, "Meera", 2, "09:30", "21:30"),
    (5, "Rohan", 2, "10:00", "22:00"),
]
SEED_TECHNICIAN_SKILLS = [
    (1, "BATTERY_FIT"),
    (1, "JUMPSTART"),
    (2, "DIAGNOSTICS"),
    (2, "JUMPSTART"),
    (3, "BATTERY_FIT"),
    (3, "DIAGNOSTICS"),
    (4, "JUMPSTART"),
    (4, "DIAGNOSTICS"),
    (5, "BATTERY_FIT"),
    (5, "JUMPSTART"),
]


def connect_database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    connection = connect_database()
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        booking_columns = set()
        for row in connection.execute("PRAGMA table_info(bookings)").fetchall():
            booking_columns.add(row["name"])
        if "cancelled_at" not in booking_columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN cancelled_at TEXT")
        if "idempotency_key" not in booking_columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN idempotency_key TEXT"
            )
        if "phone" not in booking_columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN phone TEXT")
        technician_columns = set()
        for row in connection.execute("PRAGMA table_info(technicians)").fetchall():
            technician_columns.add(row["name"])
        if "booked_slots" in technician_columns:
            connection.execute("ALTER TABLE technicians DROP COLUMN booked_slots")
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS bookings_active_by_day_and_technician
            ON bookings (booking_date, technician_id)
            WHERE cancelled_at IS NULL
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS bookings_idempotency_key_unique
            ON bookings (idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS bookings_phone_by_id
            ON bookings (phone, id DESC)
            """
        )

        # Seed reference and example data only when it is missing; keep bookings intact.
        skill_rows = []
        for skill in SEED_SKILLS:
            skill_rows.append((skill,))
        connection.executemany(
            "INSERT OR IGNORE INTO skills (code) VALUES (?)", skill_rows
        )
        connection.execute(
            "INSERT OR IGNORE INTO app_settings VALUES (?, ?)",
            ("data_message", SEED_DATA_MESSAGE),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO sample_items VALUES (?, ?)",
            SEED_SAMPLE_ITEMS,
        )
        connection.executemany(
            "INSERT OR IGNORE INTO services VALUES (?, ?, ?, ?)", SEED_SERVICES
        )
        connection.executemany(
            "INSERT OR IGNORE INTO zones VALUES (?, ?)", SEED_ZONES
        )
        connection.executemany(
            "INSERT OR IGNORE INTO zone_pincodes VALUES (?, ?)", SEED_PINCODES
        )
        connection.executemany(
            """
            INSERT INTO technicians
                (id, name, zone_id, shift_start, shift_end)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                shift_start = excluded.shift_start,
                shift_end = excluded.shift_end
            """,
            SEED_TECHNICIANS,
        )
        connection.executemany(
            "INSERT OR IGNORE INTO technician_skills VALUES (?, ?)",
            SEED_TECHNICIAN_SKILLS,
        )
        connection.commit()
    finally:
        connection.close()
