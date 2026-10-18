import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Optional

from constants import (
    MAX_BOOKING_LEAD,
    MIN_BOOKING_LEAD,
    SLOT_INTERVAL_MINUTES,
    TRAVEL_BUFFER_MINUTES,
)
from models import (
    AvailabilityQueryRow,
    BookingPageResponse,
    BookingResponse,
    BookingCancellationRecord,
    SampleDataResponse,
    SampleItemRecord,
    ServiceRecord,
    ServiceResponse,
    SkillRecord,
    TechnicianResponse,
    ZoneResponse,
)


def get_bookable_slots(
    connection: sqlite3.Connection,
    service_id: int,
    pincode: str,
    requested_date: date,
    now: datetime,
) -> list[str]:
    # Use eligible shifts to bound Python's 30-minute candidate generation.
    shift_bounds = connection.execute(
        """
        SELECT MIN(technicians.shift_start) AS earliest_shift_start,
            MAX(technicians.shift_end) AS latest_shift_end
        FROM services
        JOIN technician_skills
            ON technician_skills.skill_code = services.required_skill
        JOIN technicians
            ON technicians.id = technician_skills.technician_id
        JOIN zone_pincodes
            ON zone_pincodes.zone_id = technicians.zone_id
        WHERE services.id = :service_id
            AND zone_pincodes.pincode = :pincode
        """,
        {"service_id": service_id, "pincode": pincode},
    ).fetchone()

    if (
        shift_bounds is None
        or shift_bounds["earliest_shift_start"] is None
        or shift_bounds["latest_shift_end"] is None
    ):
        return []

    earliest_start = max(
        now + MIN_BOOKING_LEAD,
        datetime.combine(
            requested_date,
            time.fromisoformat(shift_bounds["earliest_shift_start"]),
        ),
    )
    latest_start = min(
        now + MAX_BOOKING_LEAD,
        datetime.combine(
            requested_date,
            time.fromisoformat(shift_bounds["latest_shift_end"]),
        ),
    )
    if earliest_start > latest_start:
        return []

    # Round up to the next wall-clock half-hour, then generate bounded candidates.
    interval_seconds = SLOT_INTERVAL_MINUTES * 60
    seconds_since_midnight = (
        earliest_start.hour * 3600
        + earliest_start.minute * 60
        + earliest_start.second
    )
    rounded_seconds = (
        (seconds_since_midnight + interval_seconds - 1) // interval_seconds
    ) * interval_seconds
    candidate = datetime.combine(requested_date, time.min) + timedelta(
        seconds=rounded_seconds
    )
    candidate_slots = []
    while candidate <= latest_start:
        candidate_slots.append(candidate.strftime("%H:%M"))
        candidate += timedelta(minutes=SLOT_INTERVAL_MINUTES)

    if not candidate_slots:
        return []

    # For each candidate, keep it when any qualified technician can take it.
    candidate_values = []
    parameters = {
        "requested_date": requested_date.isoformat(),
        "service_id": service_id,
        "pincode": pincode,
        "travel_buffer_minutes": TRAVEL_BUFFER_MINUTES,
    }
    for index, slot in enumerate(candidate_slots):
        parameter_name = "slot_{}".format(index)
        candidate_values.append("(:{})".format(parameter_name))
        parameters[parameter_name] = slot

    rows = connection.execute(
        """
        WITH candidate_slots(slot_time) AS (
            VALUES {}
        )
        SELECT candidate_slots.slot_time
        FROM candidate_slots
        WHERE EXISTS (
            SELECT 1
            FROM services AS requested_service
            JOIN technician_skills
                ON technician_skills.skill_code =
                    requested_service.required_skill
            JOIN technicians
                ON technicians.id = technician_skills.technician_id
            JOIN zone_pincodes
                ON zone_pincodes.zone_id = technicians.zone_id
            WHERE requested_service.id = :service_id
                AND zone_pincodes.pincode = :pincode
                AND julianday(
                    :requested_date || ' ' || candidate_slots.slot_time
                ) >= julianday(
                    :requested_date || ' ' || technicians.shift_start
                )
                AND julianday(
                    :requested_date || ' ' || candidate_slots.slot_time,
                    '+' || requested_service.duration_minutes || ' minutes'
                ) <= julianday(
                    :requested_date || ' ' || technicians.shift_end
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM bookings
                    JOIN services AS booked_service
                        ON booked_service.id = bookings.service_id
                    WHERE bookings.technician_id = technicians.id
                        AND bookings.booking_date = :requested_date
                        AND bookings.cancelled_at IS NULL
                        AND julianday(
                            :requested_date || ' ' || candidate_slots.slot_time,
                            '-' || :travel_buffer_minutes || ' minutes'
                        ) < julianday(
                            bookings.booking_date || ' ' || bookings.start_time,
                            '+' || booked_service.duration_minutes || ' minutes'
                        )
                        AND julianday(
                            bookings.booking_date || ' ' || bookings.start_time
                        ) < julianday(
                            :requested_date || ' ' || candidate_slots.slot_time,
                            '+' || requested_service.duration_minutes ||
                                ' minutes',
                            '+' || :travel_buffer_minutes || ' minutes'
                        )
                )
        )
        ORDER BY candidate_slots.slot_time
        """.format(", ".join(candidate_values)),
        parameters,
    ).fetchall()
    return [row["slot_time"] for row in rows]


def find_service_and_zone(
    connection: sqlite3.Connection, service_id: int, pincode: str
) -> tuple[Optional[ServiceRecord], Optional[int]]:
    service_row = connection.execute(
        "SELECT id, name, duration_minutes, required_skill "
        "FROM services WHERE id = ?",
        (service_id,),
    ).fetchone()
    zone_row = connection.execute(
        "SELECT zone_id FROM zone_pincodes WHERE pincode = ?", (pincode,)
    ).fetchone()

    service = None
    zone_id = None
    if service_row is not None:
        service = ServiceRecord(
            id=service_row["id"],
            name=service_row["name"],
            duration_minutes=service_row["duration_minutes"],
            required_skill=service_row["required_skill"],
        )
    if zone_row is not None:
        zone_id = zone_row["zone_id"]
    return service, zone_id


def get_eligible_technician_rows(
    connection: sqlite3.Connection,
    service_id: int,
    pincode: str,
    requested_date: date,
) -> list[AvailabilityQueryRow]:
    rows = connection.execute(
        """
        SELECT technicians.id AS technician_id,
            technicians.name AS technician_name,
            technicians.shift_start,
            technicians.shift_end,
            requested_service.id AS service_id,
            requested_service.duration_minutes AS service_duration,
            booking.id AS booking_id,
            booking.start_time AS booking_start,
            strftime(
                '%H:%M',
                booking.start_time,
                '+' || booked_service.duration_minutes || ' minutes'
            ) AS booking_end,
            COUNT(booking.id) OVER (
                PARTITION BY technicians.id
            ) AS daily_booking_count
        FROM services AS requested_service
        JOIN technician_skills
            ON technician_skills.skill_code = requested_service.required_skill
        JOIN technicians
            ON technicians.id = technician_skills.technician_id
        JOIN zone_pincodes
            ON zone_pincodes.zone_id = technicians.zone_id
        LEFT JOIN bookings AS booking
            ON booking.technician_id = technicians.id
            AND booking.booking_date = :requested_date
            AND booking.cancelled_at IS NULL
        LEFT JOIN services AS booked_service
            ON booked_service.id = booking.service_id
        WHERE requested_service.id = :service_id
            AND zone_pincodes.pincode = :pincode
        ORDER BY technicians.id, booking.start_time
        """,
        {
            "service_id": service_id,
            "pincode": pincode,
            "requested_date": requested_date.isoformat(),
        },
    ).fetchall()

    # Convert raw SQLite rows into typed query-result models.
    technician_rows: list[AvailabilityQueryRow] = []
    for row in rows:
        technician_rows.append(
            AvailabilityQueryRow(
                technician_id=row["technician_id"],
                technician_name=row["technician_name"],
                shift_start=row["shift_start"],
                shift_end=row["shift_end"],
                service_id=row["service_id"],
                service_duration=row["service_duration"],
                booking_id=row["booking_id"],
                booking_start=row["booking_start"],
                booking_end=row["booking_end"],
                daily_booking_count=row["daily_booking_count"],
            )
        )
    return technician_rows


def get_services(connection: sqlite3.Connection) -> list[ServiceResponse]:
    rows = connection.execute(
        """
        SELECT id, name, duration_minutes, required_skill
        FROM services
        ORDER BY id
        """
    ).fetchall()
    services = []
    for row in rows:
        services.append(
            ServiceResponse(
                id=row["id"],
                name=row["name"],
                durationMinutes=row["duration_minutes"],
                requiredSkill=row["required_skill"],
            )
        )
    return services


def get_skills(connection: sqlite3.Connection) -> list[SkillRecord]:
    rows = connection.execute("SELECT code FROM skills ORDER BY code").fetchall()
    skills = []
    for row in rows:
        skills.append(SkillRecord(code=row["code"]))
    return skills


def get_zones(connection: sqlite3.Connection) -> list[ZoneResponse]:
    rows = connection.execute(
        """
        SELECT zones.id, zones.name, zone_pincodes.pincode
        FROM zones
        LEFT JOIN zone_pincodes ON zone_pincodes.zone_id = zones.id
        ORDER BY zones.id, zone_pincodes.pincode
        """
    ).fetchall()
    zones = []
    for row in rows:
        # The LEFT JOIN repeats each zone once per pincode; group them into one response.
        zone = None
        for existing_zone in zones:
            if existing_zone.id == row["id"]:
                zone = existing_zone
                break
        if zone is None:
            zone = ZoneResponse(id=row["id"], name=row["name"], pincodes=[])
            zones.append(zone)
        if row["pincode"] is not None:
            zone.pincodes.append(row["pincode"])
    return zones


def get_technicians(connection: sqlite3.Connection) -> list[TechnicianResponse]:
    rows = connection.execute(
        """
        SELECT technicians.id, technicians.name, technicians.zone_id,
            technicians.shift_start, technicians.shift_end,
            technician_skills.skill_code
        FROM technicians
        LEFT JOIN technician_skills
            ON technician_skills.technician_id = technicians.id
        ORDER BY technicians.id, technician_skills.skill_code
        """
    ).fetchall()
    technicians = []
    for row in rows:
        # The LEFT JOIN repeats each technician once per skill; group their skills.
        technician = None
        for existing_technician in technicians:
            if existing_technician.id == row["id"]:
                technician = existing_technician
                break
        if technician is None:
            technician = TechnicianResponse(
                id=row["id"],
                name=row["name"],
                zoneId=row["zone_id"],
                skills=[],
                shiftStart=row["shift_start"],
                shiftEnd=row["shift_end"],
            )
            technicians.append(technician)
        if row["skill_code"] is not None:
            technician.skills.append(row["skill_code"])
    return technicians


def get_sample_data(connection: sqlite3.Connection) -> SampleDataResponse:
    message_row = connection.execute(
        "SELECT value FROM app_settings WHERE key = 'data_message'"
    ).fetchone()
    item_rows = connection.execute(
        "SELECT id, name FROM sample_items ORDER BY id"
    ).fetchall()

    items = []
    for row in item_rows:
        items.append(SampleItemRecord(id=row["id"], name=row["name"]))
    return SampleDataResponse(message=message_row["value"], items=items)


def insert_booking(
    connection: sqlite3.Connection,
    service_id: int,
    pincode: str,
    phone: str,
    requested_date: date,
    start_time: time,
    technician_id: int,
    idempotency_key: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO bookings
            (service_id, pincode, phone, booking_date, start_time, technician_id,
             idempotency_key)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            service_id,
            pincode,
            phone,
            requested_date.isoformat(),
            start_time.strftime("%H:%M"),
            technician_id,
            idempotency_key,
        ),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("Booking insert did not return an ID")
    return cursor.lastrowid


def get_bookings(
    connection: sqlite3.Connection,
    phone: Optional[str],
    limit: int,
    offset: int,
) -> BookingPageResponse:
    # Apply the same exact phone filter to page data and total count.
    where_clause = "WHERE phone = ?" if phone is not None else ""
    parameters = (phone,) if phone is not None else ()
    total = connection.execute(
        "SELECT COUNT(*) FROM bookings " + where_clause,
        parameters,
    ).fetchone()[0]
    rows = connection.execute(
        """
        SELECT id, service_id, pincode, phone, booking_date, start_time,
            technician_id, cancelled_at
        FROM bookings
        """
        + where_clause
        + " ORDER BY id DESC LIMIT ? OFFSET ?",
        parameters + (limit, offset),
    ).fetchall()

    bookings = []
    for row in rows:
        bookings.append(
            BookingResponse(
                id=row["id"],
                serviceId=row["service_id"],
                pincode=row["pincode"],
                phone=row["phone"],
                date=date.fromisoformat(row["booking_date"]),
                bookingStartTime=row["start_time"],
                technicianId=row["technician_id"],
                status="cancelled" if row["cancelled_at"] is not None else "booked",
            )
        )
    return BookingPageResponse(items=bookings, total=total, limit=limit, offset=offset)


def get_booking_by_idempotency_key(
    connection: sqlite3.Connection, idempotency_key: str
) -> Optional[BookingCancellationRecord]:
    row = connection.execute(
        """
        SELECT id, service_id, pincode, phone, booking_date, start_time,
            technician_id, cancelled_at, idempotency_key
        FROM bookings
        WHERE idempotency_key = ?
        """,
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return BookingCancellationRecord(
        id=row["id"],
        service_id=row["service_id"],
        pincode=row["pincode"],
        phone=row["phone"],
        booking_date=date.fromisoformat(row["booking_date"]),
        start_time=row["start_time"],
        technician_id=row["technician_id"],
        cancelled_at=row["cancelled_at"],
        idempotency_key=row["idempotency_key"],
    )


def get_booking_for_cancellation(
    connection: sqlite3.Connection, booking_id: int
) -> Optional[BookingCancellationRecord]:
    row = connection.execute(
        """
        SELECT id, service_id, pincode, phone, booking_date, start_time,
            technician_id, cancelled_at
        FROM bookings
        WHERE id = ?
        """,
        (booking_id,),
    ).fetchone()
    if row is None:
        return None
    return BookingCancellationRecord(
        id=row["id"],
        service_id=row["service_id"],
        pincode=row["pincode"],
        phone=row["phone"],
        booking_date=date.fromisoformat(row["booking_date"]),
        start_time=row["start_time"],
        technician_id=row["technician_id"],
        cancelled_at=row["cancelled_at"],
    )


def mark_booking_cancelled(
    connection: sqlite3.Connection, booking_id: int, cancelled_at: str
) -> None:
    connection.execute(
        "UPDATE bookings SET cancelled_at = ? WHERE id = ?",
        (cancelled_at, booking_id),
    )
