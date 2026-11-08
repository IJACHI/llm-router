import unittest
from pagination import paginate

class T(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(paginate(list(range(10)), 1, 3), [0, 1, 2])
    def test_last_page(self):
        self.assertEqual(paginate(list(range(10)), 4, 3), [9])
