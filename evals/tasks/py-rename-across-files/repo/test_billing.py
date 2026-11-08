import unittest
from billing.totals import compute_total
from billing.invoice import invoice_total
from report import summary

class T(unittest.TestCase):
    def test_all(self):
        items = [{"price": 2, "qty": 3}]
        self.assertEqual(compute_total(items), 6)
        self.assertEqual(invoice_total({"items": items, "shipping": 1}), 7)
        self.assertEqual(summary([items]), [6])
