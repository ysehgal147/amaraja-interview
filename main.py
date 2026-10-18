import json
import logging
import re
import sqlite3
from datetime import datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import connect_database, initialize_database
from errors import APIError
from models import (
    AvailabilityResponse,
    BookingPageResponse,
    BookingRequest,
    BookingResponse,
    DetailedAvailabilityResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    SampleDataResponse,
    ServiceResponse,
    SkillRecord,
    TechnicianResponse,
    ValidationIssue,
    ZoneResponse,
)
from openapi_docs import (
    AVAILABILITY_DOCS,
    BookingIdPath,
    BOOKING_LIST_DOCS,
    CANCEL_BOOKING_DOCS,
    CREATE_BOOKING_DOCS,
    DateQuery,
    DETAILED_AVAILABILITY_DOCS,
    HEALTH_DOCS,
    IdempotencyKeyHeader,
    LimitQuery,
    OffsetQuery,
    PincodeQuery,
    PhoneFilterQuery,
    ServiceIdQuery,
)
from service import (
    cancel_booking as cancel_booking_service,
    create_booking as create_booking_service,
    get_detailed_availability as get_detailed_availability_service,
    get_availability as get_availability_service,
    get_bookings as get_bookings_service,
    get_sample_data,
    get_services,
    get_skills,
    get_technicians,
    get_zones,
    get_service_and_zone,
)

app = FastAPI(title="Service Availability API")
request_logger = logging.getLogger("service_api")
request_logger.setLevel(logging.INFO)
request_logger.propagate = False
if not request_logger.handlers:
    request_handler = logging.StreamHandler()
    request_handler.setFormatter(logging.Formatter("%(message)s"))
    request_logger.addHandler(request_handler)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@app.middleware("http")
async def log_requests_with_request_id(request: Request, call_next: Any) -> Any:
    # Reuse safe caller-provided IDs or assign one, and return it for correlation.
    request_id = request.headers.get("X-Request-ID", "")
    if REQUEST_ID_PATTERN.fullmatch(request_id) is None:
        request_id = str(uuid4())
    request.state.request_id = request_id
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        request_logger.error(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": (perf_counter() - started_at) * 1000,
                    "exception_type": type(error).__name__,
                }
            )
        )
        raise

    response.headers["X-Request-ID"] = request_id
    request_logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": (perf_counter() - started_at) * 1000,
            }
        )
    )
    return response

@app.get(
    "/health",
    response_model=HealthResponse,
    **HEALTH_DOCS,
)
def health_check() -> HealthResponse:
    # Confirm the application can open and query its configured database.
    connection = None
    try:
        connection = connect_database()
        connection.execute("SELECT 1").fetchone()
        return HealthResponse(status="ok", database="ok")
    except sqlite3.Error as error:
        raise APIError(
            503, "database_unavailable", "Database health check failed"
        ) from error
    finally:
        if connection is not None:
            connection.close()


@app.exception_handler(RequestValidationError)
def handle_validation_error(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    # Convert framework validation details to the same error envelope as API errors.
    del _request
    issues = []
    for item in error.errors():
        location = []
        for part in item["loc"]:
            location.append(str(part))
        issues.append(
            ValidationIssue(
                field=".".join(location),
                message=item["msg"],
            )
        )
    body = ErrorResponse(
        error=ErrorDetail(
            code="invalid_input",
            message="Request validation failed",
            details=issues,
        )
    )
    return JSONResponse(status_code=422, content=body.model_dump(exclude_none=True))


@app.exception_handler(StarletteHTTPException)
def handle_http_error(
    _request: Request, error: StarletteHTTPException
) -> JSONResponse:
    # Keep router errors and service errors in one stable response format.
    del _request
    if isinstance(error, APIError):
        code = error.code
    elif error.status_code == 404:
        code = "not_found"
    else:
        code = "http_error"
    message = error.detail if isinstance(error.detail, str) else "Request failed"
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(
        status_code=error.status_code,
        content=body.model_dump(exclude_none=True),
    )


@app.get("/api/data")
def get_data() -> SampleDataResponse:
    connection = connect_database()
    try:
        return get_sample_data(connection)
    finally:
        connection.close()


@app.get("/services", response_model=list[ServiceResponse])
def list_services() -> list[ServiceResponse]:
    connection = connect_database()
    try:
        return get_services(connection)
    finally:
        connection.close()


@app.get("/skills", response_model=list[SkillRecord])
def list_skills() -> list[SkillRecord]:
    connection = connect_database()
    try:
        return get_skills(connection)
    finally:
        connection.close()


@app.get("/zones", response_model=list[ZoneResponse])
def list_zones() -> list[ZoneResponse]:
    connection = connect_database()
    try:
        return get_zones(connection)
    finally:
        connection.close()


@app.get("/technicians", response_model=list[TechnicianResponse])
def list_technicians() -> list[TechnicianResponse]:
    connection = connect_database()
    try:
        return get_technicians(connection)
    finally:
        connection.close()


@app.get(
    "/bookings",
    response_model=BookingPageResponse,
    **BOOKING_LIST_DOCS,
)
def list_bookings(
    phone: PhoneFilterQuery = None,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> BookingPageResponse:
    connection = connect_database()
    try:
        return get_bookings_service(connection, phone, limit, offset)
    finally:
        connection.close()


@app.get(
    "/availability",
    response_model=AvailabilityResponse,
    **AVAILABILITY_DOCS,
)
def get_availability(
    service_id: ServiceIdQuery,
    pincode: PincodeQuery,
    requested_date: DateQuery,
) -> AvailabilityResponse:
    connection = connect_database()
    try:
        get_service_and_zone(connection, service_id, pincode)
        return get_availability_service(
            connection, service_id, pincode, requested_date, datetime.now()
        )
    finally:
        connection.close()


@app.get(
    "/availabilityDetailed",
    response_model=DetailedAvailabilityResponse,
    **DETAILED_AVAILABILITY_DOCS,
)
def get_availability_detailed(
    service_id: ServiceIdQuery,
    pincode: PincodeQuery,
    requested_date: DateQuery,
) -> DetailedAvailabilityResponse:
    connection = connect_database()
    try:
        get_service_and_zone(connection, service_id, pincode)
        return get_detailed_availability_service(
            connection,
            service_id,
            pincode,
            requested_date,
            datetime.now(),
        )
    finally:
        connection.close()


@app.post(
    "/bookings",
    response_model=BookingResponse,
    **CREATE_BOOKING_DOCS,
)
def create_booking(
    request: BookingRequest,
    idempotency_key: IdempotencyKeyHeader,
) -> BookingResponse:
    connection = connect_database()
    try:
        # Serialize check-and-insert so concurrent requests cannot double-book.
        connection.execute("BEGIN IMMEDIATE")
        booking = create_booking_service(
            connection,
            request.serviceId,
            request.pincode,
            request.phone,
            request.date,
            request.bookingStartTime,
            idempotency_key,
            datetime.now(),
        )
        connection.commit()
        return booking
    except HTTPException:
        connection.rollback()
        raise
    finally:
        connection.close()


@app.delete(
    "/bookings/{booking_id}",
    response_model=BookingResponse,
    **CANCEL_BOOKING_DOCS,
)
def cancel_booking(
    booking_id: BookingIdPath,
) -> BookingResponse:
    connection = connect_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = cancel_booking_service(connection, booking_id, datetime.now())
        connection.commit()
        return result
    except HTTPException:
        connection.rollback()
        raise
    finally:
        connection.close()


initialize_database()
