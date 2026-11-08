import unittest
from settings import load_settings

class T(unittest.TestCase):
    def test_default(self):
        self.assertEqual(load_settings({})["timeout"], 30)
    def test_given(self):
        self.assertEqual(load_settings({"timeout": "5"})["timeout"], 5)
