import unittest
from prices import retail_price, wholesale_price

class T(unittest.TestCase):
    def test_retail_unchanged(self):
        self.assertEqual(retail_price(100), 100)
    def test_wholesale_discount(self):
        self.assertEqual(wholesale_price(100), 90.0)
