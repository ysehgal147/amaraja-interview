import json
import tempfile
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import database


_TEMPORARY_DATABASE = tempfile.TemporaryDirectory(
    prefix="amaraja-scheduling-lifecycle-"
)
database.DATABASE_PATH = Path(_TEMPORARY_DATABASE.name) / "tests.db"
database.initialize_database()

import main
import uvicorn


class SchedulingLifecycleAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = uvicorn.Server(
            uvicorn.Config(
                main.app,
                host="127.0.0.1",
                port=0,
                log_level="error",
                access_log=False,
            )
        )
        cls.server_thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.server_thread.start()
        for _ in range(100):
            if cls.server.started and cls.server.servers:
                address = cls.server.servers[0].sockets[0].getsockname()
                cls.base_url = "http://127.0.0.1:{}".format(address[1])
                break
            if not cls.server_thread.is_alive():
                raise RuntimeError("Test API server failed to start")
            time.sleep(0.05)
        else:
            raise RuntimeError("Test API server did not become ready")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.server_thread.join(timeout=10)
        _TEMPORARY_DATABASE.cleanup()

    def setUp(self) -> None:
        connection = database.connect_database()
        try:
            connection.execute("DELETE FROM bookings")
            connection.execute(
                """
                UPDATE technicians
                SET shift_start = '08:00', shift_end = '13:00'
                WHERE id = 1
                """
            )
            connection.execute(
                """
                UPDATE technicians
                SET shift_start = '10:00', shift_end = '18:00'
                WHERE id = 3
                """
            )
            connection.commit()
        finally:
            connection.close()
        self.requested_date = date.today() + timedelta(days=3)

    def request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers=headers or {},
        )
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def create_booking(self, key: str, start_time: str) -> dict:
        status, response = self.request(
            "POST",
            "/bookings",
            {
                "serviceId": 1,
                "pincode": "110001",
                "phone": "+919876543210",
                "date": self.requested_date.isoformat(),
                "bookingStartTime": start_time,
            },
            {"Idempotency-Key": key},
        )
        self.assertEqual(status, 201, response)
        self.assertEqual(response["status"], "booked")
        return response

    def availability_path(self) -> str:
        return (
            "/availability?serviceId=1&pincode=110001&date="
            + self.requested_date.isoformat()
        )

    def test_different_shifts_multiple_bookings_and_cancellation_update_availability(
        self,
    ) -> None:
        status, initial = self.request("GET", self.availability_path())
        self.assertEqual(status, 200, initial)
        self.assertIn("08:00", initial["availableSlots"])
        self.assertIn("17:00", initial["availableSlots"])
        self.assertNotIn("17:30", initial["availableSlots"])

        detailed_path = (
            "/availabilityDetailed?serviceId=1&pincode=110001&date="
            + self.requested_date.isoformat()
        )
        status, detailed = self.request("GET", detailed_path)
        self.assertEqual(status, 200, detailed)
        technicians = {
            technician["technicianId"]: technician
            for technician in detailed["technicians"]
        }
        self.assertEqual(technicians[1]["shiftStart"], "08:00")
        self.assertEqual(technicians[1]["shiftEnd"], "13:00")
        self.assertEqual(technicians[3]["shiftStart"], "10:00")
        self.assertEqual(technicians[3]["shiftEnd"], "18:00")
        self.assertIn("08:00", technicians[1]["availableSlots"])
        self.assertNotIn("08:00", technicians[3]["availableSlots"])
        self.assertIn("17:00", technicians[3]["availableSlots"])
        self.assertNotIn("17:30", technicians[3]["availableSlots"])

        first_at_ten = self.create_booking("lifecycle-10am-a", "10:00")
        second_at_ten = self.create_booking("lifecycle-10am-b", "10:00")
        self.assertEqual(first_at_ten["technicianId"], 1)
        self.assertEqual(second_at_ten["technicianId"], 3)

        status, unavailable = self.request("GET", self.availability_path())
        self.assertEqual(status, 200, unavailable)
        self.assertNotIn("10:00", unavailable["availableSlots"])

        third_booking = self.create_booking("lifecycle-1230", "12:30")
        self.assertEqual(third_booking["technicianId"], 3)

        status, after_one_cancel = self.request(
            "DELETE", "/bookings/{}".format(first_at_ten["id"])
        )
        self.assertEqual(status, 200, after_one_cancel)
        self.assertEqual(after_one_cancel["status"], "cancelled")
        status, available_after_first_cancel = self.request(
            "GET", self.availability_path()
        )
        self.assertEqual(status, 200, available_after_first_cancel)
        self.assertIn("10:00", available_after_first_cancel["availableSlots"])
        status, detailed_after_first_cancel = self.request(
            "GET", detailed_path
        )
        self.assertEqual(status, 200, detailed_after_first_cancel)
        technicians_after_first_cancel = {
            technician["technicianId"]: technician
            for technician in detailed_after_first_cancel["technicians"]
        }
        self.assertIn(
            "10:00",
            technicians_after_first_cancel[1]["availableSlots"],
        )
        self.assertNotIn(
            "10:00",
            technicians_after_first_cancel[3]["availableSlots"],
        )

        status, after_second_cancel = self.request(
            "DELETE", "/bookings/{}".format(second_at_ten["id"])
        )
        self.assertEqual(status, 200, after_second_cancel)
        self.assertEqual(after_second_cancel["status"], "cancelled")
        status, restored = self.request("GET", self.availability_path())
        self.assertEqual(status, 200, restored)
        self.assertIn("10:00", restored["availableSlots"])
        self.assertNotIn("12:30", restored["availableSlots"])
        status, fully_cancelled_details = self.request("GET", detailed_path)
        self.assertEqual(status, 200, fully_cancelled_details)
        fully_cancelled_technicians = {
            technician["technicianId"]: technician
            for technician in fully_cancelled_details["technicians"]
        }
        self.assertIn("10:00", fully_cancelled_technicians[1]["availableSlots"])
        self.assertIn("10:00", fully_cancelled_technicians[3]["availableSlots"])

        status, booking_page = self.request(
            "GET", "/bookings?phone=%2B919876543210&limit=10&offset=0"
        )
        self.assertEqual(status, 200, booking_page)
        self.assertEqual(booking_page["total"], 3)
        booking_statuses = {
            booking["id"]: booking["status"]
            for booking in booking_page["items"]
        }
        self.assertEqual(booking_statuses[first_at_ten["id"]], "cancelled")
        self.assertEqual(booking_statuses[second_at_ten["id"]], "cancelled")
        self.assertEqual(booking_statuses[third_booking["id"]], "booked")


if __name__ == "__main__":
    unittest.main()
