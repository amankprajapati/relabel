"""HTTP tests for the "Ask AI" routes, with a fake advisor injected into the real server."""
import base64
import json
import os
import sys
import threading
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "relabel_gui_app"))
from advisors import Advisor, AdvisorError, AdvisorRegistry, Suggestion  # noqa: E402
from app import Server  # noqa: E402
from server import make_handler  # noqa: E402


class FakeAdvisor(Advisor):
    id, label = "fake", "Fake"

    def __init__(self):
        self.requests = []

    def availability(self):
        return True, "always ready"

    def suggest(self, request):
        self.requests.append(request)
        if request.current_class == "explode":
            raise AdvisorError("model unavailable")
        return Suggestion(cls="truck", reason="Open cargo bed.", in_list="truck" in request.classes)


class SuggestRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.advisor = FakeAdvisor()
        cls.srv = Server(("127.0.0.1", 0), make_handler({}, (), AdvisorRegistry([cls.advisor])))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST")
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    def test_lists_advisors_with_status(self):
        with urllib.request.urlopen(self.base + "/advisors") as r:
            self.assertEqual(json.load(r)["advisors"],
                             [{"id": "fake", "label": "Fake", "ready": True, "hint": "always ready"}])

    def test_suggest_decodes_images_and_returns_the_answer(self):
        crop = b"\xff\xd8 crop bytes"
        out = self.post("/suggest", {"advisor": "fake", "classes": ["car", "truck"], "current": "car",
                                     "crop": "data:image/jpeg;base64," + base64.b64encode(crop).decode(),
                                     "context": base64.b64encode(b"frame").decode()})
        self.assertEqual(out, {"ok": True, "class": "truck", "reason": "Open cargo bed.", "in_list": True})
        got = self.advisor.requests[-1]
        self.assertEqual((got.crop_jpeg, got.context_jpeg, got.classes), (crop, b"frame", ["car", "truck"]))

    def test_errors_come_back_as_messages(self):
        crop = base64.b64encode(b"x").decode()
        self.assertEqual(self.post("/suggest", {"advisor": "fake", "crop": crop, "current": "explode"}),
                         {"ok": False, "error": "model unavailable"})
        self.assertFalse(self.post("/suggest", {"advisor": "nope", "crop": crop})["ok"])
        self.assertFalse(self.post("/suggest", {"advisor": "fake"})["ok"])                 # no image
        self.assertFalse(self.post("/suggest", {"advisor": "fake", "crop": "not base64!"})["ok"])


if __name__ == "__main__":
    unittest.main()
