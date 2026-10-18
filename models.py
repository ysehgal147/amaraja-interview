from datetime import date as Date, datetime
import re
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)


class Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


def validate_date_format(value: object) -> Date:
    if isinstance(value, datetime):
        raise ValueError("Date must use YYYY-MM-DD format")
    if isinstance(value, Date):
        return value
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("Date must use YYYY-MM-DD format")
    try:
        return Date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Date must be a valid date in YYYY-MM-DD format") from error


Pincode = Annotated[str, StringConstraints(pattern=r"^\d{6,}$")]
Phone = Annotated[
    str,
    StringConstraints(
        min_length=6,
        max_length=20,
        pattern=r"^\+?[0-9][0-9 -]{5,19}$",
    ),
]
DateInput = Annotated[Date, BeforeValidator(validate_date_format)]


class SkillRecord(Model):
    code: str


class AppSettingRecord(Model):
    key: str
    value: str


class SampleItemRecord(Model):
    id: int
    name: str


class ServiceRecord(Model):
    id: int
    name: str
    duration_minutes: int
    required_skill: str


class ServiceResponse(Model):
    id: int
    name: str
    duration_minutes: int = Field(alias="durationMinutes")
    required_skill: str = Field(alias="requiredSkill")


class ZoneRecord(Model):
    id: int
    name: str
    pincodes: list[str] = Field(default_factory=list)


class ZoneResponse(Model):
    id: int
    name: str
    pincodes: list[str]


class ZonePincodeRecord(Model):
    pincode: str
    zone_id: int


class TechnicianSkillRecord(Model):
    technician_id: int
    skill_code: str


class TechnicianRecord(Model):
    id: int
    name: str
    zone_id: int
    skills: list[str] = Field(default_factory=list)
    shift_start: str
    shift_end: str


class TechnicianResponse(Model):
    id: int
    name: str
    zone_id: int = Field(alias="zoneId")
    skills: list[str]
    shift_start: str = Field(alias="shiftStart")
    shift_end: str = Field(alias="shiftEnd")


class BookingRecord(Model):
    id: int
    service_id: int
    pincode: str
    phone: Optional[str] = None
    booking_date: Date
    start_time: str
    technician_id: int
    cancelled_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None


class BookingRequest(Model):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "serviceId": 1,
                    "pincode": "110001",
                    "phone": "+919876543210",
                    "date": "2026-10-20",
                    "bookingStartTime": "10:00",
                }
            ]
        },
    )

    serviceId: int
    pincode: Pincode = Field(
        description="Numeric pincode containing at least 6 digits.",
        examples=["110001"],
    )
    phone: Phone = Field(
        description="Contact phone number; digits may be separated by spaces or hyphens.",
        examples=["+919876543210"],
    )
    date: Date = Field(
        description="Valid calendar date in YYYY-MM-DD format.",
        examples=["2026-10-20"],
    )
    bookingStartTime: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @field_validator("date", mode="before")
    @classmethod
    def validate_booking_date(cls, value: object) -> Date:
        return validate_date_format(value)


class AvailabilityQueryRow(Model):
    technician_id: int
    technician_name: str
    shift_start: str
    shift_end: str
    service_id: int
    service_duration: int
    booking_id: Optional[int] = None
    booking_start: Optional[str] = None
    booking_end: Optional[str] = None
    daily_booking_count: int


class BookingInterval(Model):
    booking_id: int = Field(alias="bookingId")
    booking_start: str = Field(alias="bookingStart")
    booking_end: str = Field(alias="bookingEnd")


class TechnicianAvailability(Model):
    id: int
    name: str
    shift_start: str
    shift_end: str
    service_id: int
    duration_minutes: int
    daily_booking_count: int
    bookings: list[BookingInterval] = Field(default_factory=list)
    booked_intervals: list[tuple[datetime, datetime]] = Field(default_factory=list)
    available_slots: list[str] = Field(default_factory=list)


class AvailabilityTechnicianResponse(Model):
    technician_id: int = Field(alias="technicianId")
    technician_name: str = Field(alias="technicianName")
    shift_start: str = Field(alias="shiftStart")
    shift_end: str = Field(alias="shiftEnd")
    service_id: int = Field(alias="serviceId")
    service_duration_minutes: int = Field(alias="serviceDurationMinutes")
    bookings: list[BookingInterval]
    available_slots: list[str] = Field(alias="availableSlots")


class AvailabilityResponse(Model):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "serviceId": 1,
                    "pincode": "110001",
                    "date": "2026-10-20",
                    "availableSlots": ["10:00", "10:30", "11:00"],
                }
            ]
        },
    )

    service_id: int = Field(alias="serviceId")
    pincode: str
    booking_date: Date = Field(alias="date")
    available_slots: list[str] = Field(alias="availableSlots")


class DetailedAvailabilityResponse(Model):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "serviceId": 1,
                    "pincode": "110001",
                    "date": "2026-10-20",
                    "technicians": [
                        {
                            "technicianId": 1,
                            "technicianName": "Aarav",
                            "shiftStart": "08:00",
                            "shiftEnd": "20:00",
                            "serviceId": 1,
                            "serviceDurationMinutes": 60,
                            "bookings": [
                                {
                                    "bookingId": 42,
                                    "bookingStart": "10:00",
                                    "bookingEnd": "11:00",
                                }
                            ],
                            "availableSlots": ["12:00", "12:30"],
                        }
                    ],
                }
            ]
        },
    )

    service_id: int = Field(alias="serviceId")
    pincode: str
    booking_date: Date = Field(alias="date")
    technicians: list[AvailabilityTechnicianResponse]


class BookingResponse(Model):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 42,
                    "serviceId": 1,
                    "pincode": "110001",
                    "phone": "+919876543210",
                    "date": "2026-10-20",
                    "bookingStartTime": "10:00",
                    "technicianId": 1,
                    "status": "booked",
                }
            ]
        },
    )

    id: int
    service_id: int = Field(alias="serviceId")
    pincode: str
    phone: Optional[str] = None
    booking_date: Date = Field(alias="date")
    booking_start_time: str = Field(alias="bookingStartTime")
    technician_id: int = Field(alias="technicianId")
    status: Literal["booked", "cancelled"]


class SampleDataResponse(Model):
    message: str
    items: list[SampleItemRecord]


class ValidationIssue(Model):
    field: str
    message: str


class ErrorDetail(Model):
    code: str
    message: str
    details: Optional[list[ValidationIssue]] = None


class ErrorResponse(Model):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "no_availability",
                        "message": "No technician is available at that time",
                    }
                }
            ]
        }
    )

    error: ErrorDetail


class BookingCancellationRecord(Model):
    id: int
    service_id: int
    pincode: str
    phone: Optional[str] = None
    booking_date: Date
    start_time: str
    technician_id: int
    cancelled_at: Optional[str]
    idempotency_key: Optional[str] = None


class BookingPageResponse(Model):
    items: list[BookingResponse]
    total: int
    limit: int
    offset: int


class HealthResponse(Model):
    status: Literal["ok"]
    database: Literal["ok"]
