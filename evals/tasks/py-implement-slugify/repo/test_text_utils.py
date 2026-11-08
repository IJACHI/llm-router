import unittest
from text_utils import slugify

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")
    def test_punctuation(self):
        self.assertEqual(slugify("  Rock & Roll!! 2024 "), "rock-roll-2024")
    def test_empty(self):
        self.assertEqual(slugify("!!!"), "")
