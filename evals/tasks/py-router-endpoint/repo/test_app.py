import unittest
from app import handle

class T(unittest.TestCase):
    def test_health(self):
        self.assertEqual(handle("GET", "/health"), (200, {"ok": True}))
    def test_users(self):
        self.assertEqual(handle("GET", "/users")[0], 200)
    def test_missing(self):
        self.assertEqual(handle("GET", "/nope")[0], 404)
