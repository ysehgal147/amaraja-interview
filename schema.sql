CREATE TABLE IF NOT EXISTS skills (
    code TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sample_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    required_skill TEXT NOT NULL REFERENCES skills(code)
);

CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zone_pincodes (
    pincode TEXT PRIMARY KEY,
    zone_id INTEGER NOT NULL REFERENCES zones(id)
);

CREATE TABLE IF NOT EXISTS technicians (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    zone_id INTEGER NOT NULL REFERENCES zones(id),
    shift_start TEXT NOT NULL,
    shift_end TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS technician_skills (
    technician_id INTEGER NOT NULL REFERENCES technicians(id),
    skill_code TEXT NOT NULL REFERENCES skills(code),
    PRIMARY KEY (technician_id, skill_code)
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id),
    pincode TEXT NOT NULL REFERENCES zone_pincodes(pincode),
    phone TEXT,
    booking_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    technician_id INTEGER NOT NULL REFERENCES technicians(id),
    cancelled_at TEXT,
    idempotency_key TEXT
);
