# Service Availability API

A FastAPI application using SQLite for its service, zone, technician, and booking data. The database schema is defined in `schema.sql` and initialized automatically on startup. Missing seed rows are inserted without clearing or overwriting existing data, so bookings persist across restarts. `database.py` applies additive migrations for older databases.

The Part B production-scale design discussion is in [DESIGN.md](./DESIGN.md).

API routes are defined in `main.py`; their OpenAPI descriptions and parameter documentation live in `openapi_docs.py`. Request, response, and table models live in `models.py`; business and scheduling logic lives in `service.py`; SQL queries live in `queries.py`; scheduling values live in `constants.py`; database initialization and seed setup live in `database.py`.

## One-command setup and run

On macOS or Linux, install Python 3.9 or newer, then run this from the project
directory:

```bash
./start.sh
```

The script creates `.venv` if needed, installs the dependencies from
`requirements.txt`, and starts the API at `http://127.0.0.1:8000`. The database
is SQLite, so there is no separate database server to install. On startup, the
app creates the schema and inserts any missing seed data while preserving
existing bookings. Stop the server with `Ctrl+C`.

To select a different bind address or port, set `HOST` or `PORT`, for example:

```bash
HOST=0.0.0.0 PORT=8080 ./start.sh
```

The script can be run from outside the project directory as well. On Windows,
use WSL or Git Bash with Python installed.

## Manual setup and run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --reload
```

## Tests

Run the focused unit, API integration, error-handling, and concurrency tests with:

```bash
python -m unittest discover -s tests -v
```

The test suite uses a temporary SQLite database and does not modify `app.db`.

## Endpoints

- `GET /api/data` returns the sample message and items stored in the database.
- `GET /services` returns the available services with duration and required skill.
- `GET /skills` returns the available skill codes.
- `GET /zones` returns zones with their pincodes.
- `GET /technicians` returns technicians with their zone, shift, and skills.
- `GET /bookings?phone=919876543210&limit=20&offset=0` returns bookings filtered by exact phone number, newest first. `phone` is optional; `limit` defaults to 50 (maximum 100), and `offset` defaults to 0. The response includes the page items and total match count.
- `GET /health` checks that the API can query its SQLite database.
- `GET /availability?serviceId=1&pincode=110001&date=2026-10-20` returns the available 30-minute start times for the requested service, pincode, and date. Candidate times are bounded by eligible-technician shifts; a time is returned if at least one qualified technician can take it, accounting for service duration and travel buffer.
- `GET /availabilityDetailed?serviceId=1&pincode=110001&date=2026-10-20` returns each qualified technician's details, active bookings with start/end times, and the start times available for that technician.
- `POST /bookings` creates a booking and assigns an eligible technician. Include a contact `phone` (6–20 characters; digits may include spaces, hyphens, and a leading `+`) and a unique `Idempotency-Key` header; retrying with the same key returns the original booking instead of creating another. `bookingStartTime` must use the `HH:MM` format, such as `"08:00"`, and be on a 30-minute boundary. For example, send `{"serviceId":1,"pincode":"110001","phone":"+919876543210","date":"2026-10-17","bookingStartTime":"10:00"}` as the JSON body with `Idempotency-Key: order-123`.
- `DELETE /bookings/{booking_id}` cancels a booking at least one hour before its start; the time is immediately available again.

Availability and booking inputs require a pincode containing at least six digits and a calendar date formatted as `YYYY-MM-DD`.

Booking requests must use 30-minute boundaries, start between two hours and seven days from the server's local time, and fit entirely within the technician's shift. Availability uses the same booking window. The full service duration and 30-minute travel buffer are reserved. Eligible technicians with the fewest active bookings on that date are assigned first; ties go to the lower technician ID. SQLite serializes booking writes to prevent concurrent double-booking. The idempotency key is unique per booking and stored in the database so retries return the original booking. Cancelled bookings are retained for history but do not block availability or count toward assignment. Data is stored in the local `app.db` SQLite database. Seed services, zones, pincodes, and skills are inserted when missing; the five seeded technicians' shift times are refreshed on startup to match their seed schedule.

The seeded technician shifts use 30-minute increments with varied starts and ends: 08:00–20:00, 08:30–20:30, 09:00–21:00, 09:30–21:30, and 10:00–22:00.

Errors use the same JSON envelope: `{"error":{"code":"...","message":"..."}}`. Invalid inputs return `422` (`invalid_input`), missing services/pincodes/bookings return `404` (`not_found`), unavailable booking requests return `409` (`no_availability`), and cancellation after the one-hour deadline returns `409` (`cancellation_too_late`). Validation errors may also include `error.details` with field-specific messages.

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

Swagger/OpenAPI documents the accepted request types and formats, including the numeric 6+ digit pincode, `YYYY-MM-DD` date, `HH:MM` booking start, required idempotency header, response examples, and standard error response envelope.

Each HTTP request is logged as one JSON object containing the method, path,
status code, duration, and request ID. Send `X-Request-ID` to correlate a
request with its log entry; otherwise, the API generates one and returns it in
the response header.
