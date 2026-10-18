import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Optional

from constants import (
    CANCELLATION_NOTICE,
    MAX_BOOKING_LEAD,
    MIN_BOOKING_LEAD,
    SLOT_INTERVAL,
    TRAVEL_BUFFER,
)
from errors import APIError
from models import (
    AvailabilityResponse,
    AvailabilityTechnicianResponse,
    BookingInterval,
    BookingPageResponse,
    BookingResponse,
    DetailedAvailabilityResponse,
    BookingCancellationRecord,
    SampleDataResponse,
    ServiceResponse,
    SkillRecord,
    TechnicianAvailability,
    TechnicianResponse,
    ZoneResponse,
    AvailabilityQueryRow,
)
from queries import (
    find_service_and_zone,
    get_booking_by_idempotency_key,
    get_booking_for_cancellation,
    get_bookable_slots as get_bookable_slots_query,
    get_bookings as get_bookings_query,
    get_eligible_technician_rows,
    get_services as get_services_query,
    get_skills as get_skills_query,
    get_sample_data as get_sample_data_query,
    get_technicians as get_technicians_query,
    get_zones as get_zones_query,
    insert_booking,
    mark_booking_cancelled,
)


def get_service_and_zone(
    connection: sqlite3.Connection, service_id: int, pincode: str
) -> int:
    service, zone_id = find_service_and_zone(connection, service_id, pincode)
    if service is None:
        raise APIError(404, "not_found", "Service not found")
    if zone_id is None:
        raise APIError(404, "not_found", "No service zone for this pincode")
    return zone_id


def can_schedule(
    technician: TechnicianAvailability,
    start: datetime,
    duration_minutes: int,
) -> bool:
    # Reject work outside the technician's shift.
    service_end = start + timedelta(minutes=duration_minutes)
    shift_start = datetime.combine(
        start.date(), time.fromisoformat(technician.shift_start)
    )
    shift_end = datetime.combine(start.date(), time.fromisoformat(technician.shift_end))
    if start < shift_start or service_end > shift_end:
        return False

    # Expand the requested interval and compare it with each existing booking.
    reserved_start = start - TRAVEL_BUFFER
    reserved_end = service_end + TRAVEL_BUFFER
    for booked_start, booked_end in technician.booked_intervals:
        if reserved_start < booked_end and booked_start < reserved_end:
            return False
    return True


def validate_booking_window(start: datetime, now: datetime) -> bool:
    return now + MIN_BOOKING_LEAD <= start <= now + MAX_BOOKING_LEAD


def group_technician_rows(
    rows: list[AvailabilityQueryRow], requested_date: date
) -> list[TechnicianAvailability]:
    # Combine one SQL row per booking into one typed record per technician.
    technicians = []
    for row in rows:
        technician = None
        for existing in technicians:
            if existing.id == row.technician_id:
                technician = existing
                break

        if technician is None:
            technician = TechnicianAvailability(
                id=row.technician_id,
                name=row.technician_name,
                shift_start=row.shift_start,
                shift_end=row.shift_end,
                service_id=row.service_id,
                duration_minutes=row.service_duration,
                daily_booking_count=row.daily_booking_count,
            )
            technicians.append(technician)

        if (
            row.booking_id is None
            or row.booking_start is None
            or row.booking_end is None
        ):
            continue

        technician.bookings.append(
            BookingInterval(
                bookingId=row.booking_id,
                bookingStart=row.booking_start,
                bookingEnd=row.booking_end,
            )
        )
        booked_start = datetime.combine(
            requested_date, time.fromisoformat(row.booking_start)
        )
        booked_end = datetime.combine(
            requested_date, time.fromisoformat(row.booking_end)
        )
        technician.booked_intervals.append((booked_start, booked_end))
    return technicians


def get_available_slots(
    technician: TechnicianAvailability, requested_date: date, now: datetime
) -> list[str]:
    # Walk the technician's shift in fixed intervals and keep bookable starts.
    shift_start = time.fromisoformat(technician.shift_start)
    shift_end = datetime.combine(
        requested_date, time.fromisoformat(technician.shift_end)
    )
    slot = datetime.combine(requested_date, shift_start)
    slot = slot.replace(minute=(slot.minute // 30) * 30, second=0, microsecond=0)
    if slot.time() < shift_start:
        slot += SLOT_INTERVAL

    available_slots = []
    while slot + timedelta(minutes=technician.duration_minutes) <= shift_end:
        if validate_booking_window(slot, now) and can_schedule(
            technician, slot, technician.duration_minutes
        ):
            available_slots.append(slot.strftime("%H:%M"))
        slot += SLOT_INTERVAL
    return available_slots


def get_availability(
    connection: sqlite3.Connection,
    service_id: int,
    pincode: str,
    requested_date: date,
    now: datetime,
) -> AvailabilityResponse:
    # Bound candidate slots by qualified shifts, then let SQL check availability.
    available_slots = get_bookable_slots_query(
        connection, service_id, pincode, requested_date, now
    )
    return AvailabilityResponse(
        serviceId=service_id,
        pincode=pincode,
        date=requested_date,
        availableSlots=available_slots,
    )


def get_detailed_availability(
    connection: sqlite3.Connection,
    service_id: int,
    pincode: str,
    requested_date: date,
    now: datetime,
) -> DetailedAvailabilityResponse:
    # Load the same query data, but keep slots separate for every technician.
    rows = get_eligible_technician_rows(
        connection, service_id, pincode, requested_date
    )
    technicians = group_technician_rows(rows, requested_date)

    technician_responses = []
    for technician in technicians:
        technician_responses.append(
            AvailabilityTechnicianResponse(
                technicianId=technician.id,
                technicianName=technician.name,
                shiftStart=technician.shift_start,
                shiftEnd=technician.shift_end,
                serviceId=technician.service_id,
                serviceDurationMinutes=technician.duration_minutes,
                bookings=technician.bookings,
                availableSlots=get_available_slots(
                    technician, requested_date, now
                ),
            )
        )
    return DetailedAvailabilityResponse(
        serviceId=service_id,
        pincode=pincode,
        date=requested_date,
        technicians=technician_responses,
    )


def create_booking(
    connection: sqlite3.Connection,
    service_id: int,
    pincode: str,
    phone: str,
    requested_date: date,
    booking_start_time: str,
    idempotency_key: str,
    now: datetime,
) -> BookingResponse:
    # Return the first result for a repeated key instead of creating another booking.
    existing_booking = get_booking_by_idempotency_key(
        connection, idempotency_key
    )
    if existing_booking is not None:
        return booking_response_from_record(existing_booking)

    start_time = time.fromisoformat(booking_start_time)
    if start_time.minute not in (0, 30):
        raise APIError(
            422, "invalid_input", "Start time must be on a 30-minute boundary"
        )

    start = datetime.combine(requested_date, start_time)
    if not validate_booking_window(start, now):
        raise APIError(
            422,
            "invalid_input",
            "Bookings must start between 2 hours and 7 days from now",
        )

    # Find qualified technicians and build their booking intervals.
    get_service_and_zone(connection, service_id, pincode)
    rows = get_eligible_technician_rows(
        connection, service_id, pincode, requested_date
    )
    technicians = group_technician_rows(rows, requested_date)

    # Select an available technician with the fewest active bookings.
    selected_technician: Optional[TechnicianAvailability] = None
    for technician in technicians:
        if not can_schedule(technician, start, technician.duration_minutes):
            continue
        if selected_technician is None:
            selected_technician = technician
        elif technician.daily_booking_count < selected_technician.daily_booking_count:
            selected_technician = technician
        elif (
            technician.daily_booking_count == selected_technician.daily_booking_count
            and technician.id < selected_technician.id
        ):
            selected_technician = technician

    if selected_technician is None:
        raise APIError(
            409, "no_availability", "No technician is available at that time"
        )

    booking_id = insert_booking(
        connection,
        service_id,
        pincode,
        phone,
        requested_date,
        start_time,
        selected_technician.id,
        idempotency_key,
    )
    return BookingResponse(
        id=booking_id,
        serviceId=service_id,
        pincode=pincode,
        phone=phone,
        date=requested_date,
        bookingStartTime=start_time.strftime("%H:%M"),
        technicianId=selected_technician.id,
        status="booked",
    )


def booking_response_from_record(
    booking: BookingCancellationRecord,
) -> BookingResponse:
    status = "booked"
    if booking.cancelled_at is not None:
        status = "cancelled"
    return BookingResponse(
        id=booking.id,
        serviceId=booking.service_id,
        pincode=booking.pincode,
        phone=booking.phone,
        date=booking.booking_date,
        bookingStartTime=booking.start_time,
        technicianId=booking.technician_id,
        status=status,
    )


def cancel_booking(
    connection: sqlite3.Connection, booking_id: int, now: datetime
) -> BookingResponse:
    booking = get_booking_for_cancellation(connection, booking_id)
    if booking is None:
        raise APIError(404, "not_found", "Booking not found")
    if booking.cancelled_at is not None:
        raise APIError(409, "booking_already_cancelled", "Booking is already cancelled")

    booking_start = datetime.combine(
        booking.booking_date, time.fromisoformat(booking.start_time)
    )
    if now > booking_start - CANCELLATION_NOTICE:
        raise APIError(
            409,
            "cancellation_too_late",
            "Bookings can only be cancelled at least 1 hour before start",
        )

    # Mark the booking cancelled so it no longer blocks availability.
    mark_booking_cancelled(
        connection, booking_id, now.isoformat(timespec="seconds")
    )
    return BookingResponse(
        id=booking.id,
        serviceId=booking.service_id,
        pincode=booking.pincode,
        phone=booking.phone,
        date=booking.booking_date,
        bookingStartTime=booking.start_time,
        technicianId=booking.technician_id,
        status="cancelled",
    )


def get_sample_data(connection: sqlite3.Connection) -> SampleDataResponse:
    return get_sample_data_query(connection)


def get_services(connection: sqlite3.Connection) -> list[ServiceResponse]:
    return get_services_query(connection)


def get_skills(connection: sqlite3.Connection) -> list[SkillRecord]:
    return get_skills_query(connection)


def get_zones(connection: sqlite3.Connection) -> list[ZoneResponse]:
    return get_zones_query(connection)


def get_technicians(connection: sqlite3.Connection) -> list[TechnicianResponse]:
    return get_technicians_query(connection)


def get_bookings(
    connection: sqlite3.Connection,
    phone: Optional[str],
    limit: int,
    offset: int,
) -> BookingPageResponse:
    return get_bookings_query(connection, phone, limit, offset)
