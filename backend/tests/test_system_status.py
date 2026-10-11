import unittest
from fastapi.testclient import TestClient
from app.main import app


class TestSystemStatus(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_system_status_endpoint(self):
        response = self.client.get("/api/system/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["overall_status"], "Active")
        self.assertTrue(data["demo_mode"])
        self.assertIn("modules", data)
        self.assertGreaterEqual(len(data["modules"]), 7)

        module_names = [m["name"] for m in data["modules"]]
        self.assertIn("Transit Data", module_names)
        self.assertIn("Bus GPS Simulator", module_names)
        self.assertIn("ETA Engine", module_names)
        self.assertIn("Crowd Prediction", module_names)
        self.assertIn("AI Assistant", module_names)
        self.assertIn("Ticket Engine", module_names)
        self.assertIn("Conductor Mode", module_names)

        for module in data["modules"]:
            self.assertEqual(module["status"], "Active")

    def test_demo_reset_endpoint(self):
        response = self.client.post("/api/demo/reset")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("reset successfully", data["message"])


if __name__ == "__main__":
    unittest.main()
