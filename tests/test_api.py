import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mibulb import api


class ApiServerTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def handle(command, params):
            self.calls.append((command, params))
            if command == "boom":
                raise api.ApiError(400, "bad value")
            return {"echo": command} if command == "status" else None

        self.server = api.ApiServer(handle, key="secret-key", port=0)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = f"http://127.0.0.1:{self.server.port}"

    def get(self, path, headers=None, data=None):
        request = Request(self.base + path, headers=headers or {}, data=data)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_needs_the_key(self):
        status, body = self.get("/api/toggle")
        self.assertEqual((status, body["ok"]), (401, False))
        status, _ = self.get("/api/toggle?key=wrong")
        self.assertEqual(status, 401)
        self.assertEqual(self.calls, [])

    def test_key_in_query_or_header(self):
        self.assertEqual(self.get("/api/toggle?key=secret-key")[0], 200)
        self.assertEqual(self.get("/api/on", headers={"X-API-Key": "secret-key"})[0], 200)
        self.assertEqual([c for c, _p in self.calls], ["toggle", "on"])

    def test_parameters_and_answers(self):
        status, body = self.get("/api/status?key=secret-key")
        self.assertEqual((status, body), (200, {"ok": True, "echo": "status"}))
        self.get("/api/brightness?value=40&key=secret-key")
        self.assertEqual(self.calls[-1], ("brightness", {"value": "40"}))

    def test_post_json(self):
        status, _ = self.get("/api/scene", headers={"X-API-Key": "secret-key", "Content-Type": "application/json"},
                             data=json.dumps({"name": "Relax"}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(self.calls[-1], ("scene", {"name": "Relax"}))

    def test_errors(self):
        self.assertEqual(self.get("/api/boom?key=secret-key"), (400, {"ok": False, "error": "bad value"}))
        self.assertEqual(self.get("/other?key=secret-key")[0], 404)

    def test_only_this_pc_by_default(self):
        self.assertEqual(self.server.host, "127.0.0.1")
        self.assertEqual(api.ApiServer(lambda c, p: None, "k", lan=True).host, "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
