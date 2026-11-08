import sqlite3, unittest
from queries import top_customers

class T(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.executescript("""
            create table customers(id integer primary key, name text);
            create table orders(id integer primary key, customer_id int, amount real);
            insert into customers values (1,'ann'),(2,'bob'),(3,'cyd');
            insert into orders(customer_id, amount) values (1,10),(2,50),(1,45),(3,5),(2,1);
        """)
    def test_top2(self):
        self.assertEqual(top_customers(self.c, 2), ["ann", "bob"])
    def test_top1(self):
        self.assertEqual(top_customers(self.c, 1), ["ann"])
