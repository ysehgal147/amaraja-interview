from typing import Annotated, Any, Dict, Optional, Union

from fastapi import Header, Path, Query

from models import DateInput, ErrorResponse, Phone


ERROR_RESPONSES: Dict[Union[int, str], Dict[str, Any]] = {
    422: {
        "model": ErrorResponse,
        "description": "Input is invalid.",
        "content": {
            "application/json": {
                "example": {
                    "error": {
                        "code": "invalid_input",
                        "message": "Request validation failed",
                        "details": [
                            {
                                "field": "query.pincode",
                                "message": "String should match pattern '^\\d{6,}$'",
                            }
                        ],
                    }
                }
            }
        },
    },
    404: {
        "model": ErrorResponse,
        "description": "The requested service, pincode, or booking was not found.",
        "content": {
            "application/json": {
                "example": {
                    "error": {
                        "code": "not_found",
                        "message": "Service not found",
                    }
                }
            }
        },
    },
}

NO_AVAILABILITY_RESPONSE = {
    "model": ErrorResponse,
    "description": "No eligible technician can take this time.",
    "content": {
        "application/json": {
            "example": {
                "error": {
                    "code": "no_availability",
                    "message": "No technician is available at that time",
                }
            }
        }
    },
}

CANCELLATION_CONFLICT_RESPONSE = {
    "model": ErrorResponse,
    "description": "The booking is already cancelled or cancellation is too late.",
    "content": {
        "application/json": {
            "example": {
                "error": {
                    "code": "cancellation_too_late",
                    "message": "Bookings can only be cancelled at least 1 hour before start",
                }
            }
        }
    },
}

HEALTH_DOCS = {
    "summary": "Check API and database health",
    "responses": {
        503: {
            "model": ErrorResponse,
            "description": "Database is unavailable.",
        }
    },
}

BOOKING_LIST_DOCS = {
    "summary": "List bookings",
    "description": (
        "Returns bookings ordered newest first. Filter by an exact phone number "
        "and page with limit/offset."
    ),
    "responses": {422: ERROR_RESPONSES[422]},
}

AVAILABILITY_DOCS = {
    "summary": "Get available start times",
    "description": (
        "Returns 30-minute start times where at least one qualified technician "
        "can complete the service within their shift and travel-buffer rules. "
        "Candidate times are bounded by eligible technicians' shifts."
    ),
    "responses": ERROR_RESPONSES,
}

DETAILED_AVAILABILITY_DOCS = {
    "summary": "Get detailed technician availability",
    "description": (
        "Returns each eligible technician, their active bookings, and their "
        "individual available start times."
    ),
    "responses": ERROR_RESPONSES,
}

CREATE_BOOKING_DOCS = {
    "status_code": 201,
    "summary": "Create a booking",
    "description": (
        "Creates one booking for an eligible technician. Supply an "
        "Idempotency-Key to safely retry the same request."
    ),
    "responses": {
        **ERROR_RESPONSES,
        409: NO_AVAILABILITY_RESPONSE,
    },
}

CANCEL_BOOKING_DOCS = {
    "summary": "Cancel a booking",
    "description": "Cancels a booking at least one hour before its start time.",
    "responses": {
        422: ERROR_RESPONSES[422],
        404: ERROR_RESPONSES[404],
        409: CANCELLATION_CONFLICT_RESPONSE,
    },
}

ServiceIdQuery = Annotated[
    int,
    Query(
        alias="serviceId",
        description="ID of the requested service.",
        examples=[1],
    ),
]
PincodeQuery = Annotated[
    str,
    Query(
        pattern=r"^\d{6,}$",
        description="Numeric pincode containing at least 6 digits.",
        examples=["110001"],
    ),
]
DateQuery = Annotated[
    DateInput,
    Query(
        alias="date",
        description="Valid calendar date in YYYY-MM-DD format.",
        examples=["2026-10-20"],
    ),
]
PhoneFilterQuery = Annotated[
    Optional[Phone],
    Query(
        description="Filter by the exact phone number supplied when booking.",
        examples=["+919876543210"],
    ),
]
LimitQuery = Annotated[int, Query(ge=1, le=100, description="Page size (1–100).")]
OffsetQuery = Annotated[
    int, Query(ge=0, description="Number of matching bookings to skip.")
]
IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        description="Unique key for this booking operation; reuse it for retries.",
        examples=["order-123"],
    ),
]
BookingIdPath = Annotated[
    int,
    Path(
        gt=0,
        description="Positive integer ID of the booking to cancel.",
        examples=[42],
    ),
]
