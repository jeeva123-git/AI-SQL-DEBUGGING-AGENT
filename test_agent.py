import os
import unittest

from sql_debug_agent import DebugAgent, Schema

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "examples", "schema.sql")


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = DebugAgent(Schema.from_file(SCHEMA), use_llm=False)

    def fix(self, sql):
        r = self.agent.debug(sql)
        return r

    def test_valid_query_untouched(self):
        r = self.fix("SELECT name FROM customers WHERE city = 'Chennai'")
        self.assertTrue(r.valid)
        self.assertEqual(r.issues, [])

    def test_keyword_typos(self):
        r = self.fix("SELCT name FORM customers WEHRE city = 'Chennai'")
        self.assertTrue(r.valid)
        self.assertEqual(r.fixed, "SELECT name FROM customers WHERE city = 'Chennai';")

    def test_merged_keywords(self):
        r = self.fix("SELECT city, COUNT(*) FROM customers GROUPBY city")
        self.assertTrue(r.valid)
        self.assertIn("GROUP BY city", r.fixed)

    def test_unknown_table(self):
        r = self.fix("SELECT name FROM custmers")
        self.assertTrue(r.valid)
        self.assertIn("FROM customers", r.fixed)

    def test_unknown_column(self):
        r = self.fix("SELECT nme FROM customers")
        self.assertTrue(r.valid)
        self.assertIn("SELECT name", r.fixed)

    def test_qualified_unknown_column(self):
        r = self.fix("SELECT c.nam FROM customers c")
        self.assertTrue(r.valid)
        self.assertIn("c.name", r.fixed)

    def test_missing_join_condition(self):
        r = self.fix("SELECT c.name, o.total FROM customers c JOIN orders o")
        self.assertTrue(r.valid)
        self.assertIn("ON c.id = o.customer_id", r.fixed)

    def test_aggregate_in_where(self):
        r = self.fix("SELECT city, COUNT(*) FROM customers WHERE COUNT(*) > 1 GROUP BY city")
        self.assertTrue(r.valid)
        self.assertIn("HAVING COUNT(*) > 1", r.fixed)
        self.assertNotIn("WHERE", r.fixed)

    def test_missing_group_by(self):
        r = self.fix("SELECT city, COUNT(*) FROM customers")
        self.assertTrue(r.valid)
        self.assertIn("GROUP BY city", r.fixed)

    def test_null_comparison(self):
        r = self.fix("SELECT name FROM customers WHERE email = NULL")
        self.assertIn("email IS NULL", r.fixed)

    def test_double_equals_and_quotes(self):
        r = self.fix('SELECT name FROM customers WHERE city == "Chennai"')
        self.assertEqual(r.fixed, "SELECT name FROM customers WHERE city = 'Chennai';")

    def test_trailing_comma(self):
        r = self.fix("SELECT name, FROM customers")
        self.assertEqual(r.fixed, "SELECT name FROM customers;")

    def test_clause_order(self):
        r = self.fix("SELECT name FROM customers LIMIT 2 ORDER BY name")
        self.assertTrue(r.valid)
        self.assertTrue(r.fixed.index("ORDER BY") < r.fixed.index("LIMIT"))

    def test_ambiguous_column(self):
        r = self.fix("SELECT id FROM customers c JOIN orders o ON c.id = o.customer_id")
        self.assertTrue(r.valid)
        self.assertIn("c.id", r.fixed)

    def test_unclosed_paren(self):
        r = self.fix("SELECT name FROM customers WHERE id IN (SELECT customer_id FROM orders")
        self.assertTrue(r.valid)

    def test_combined_errors(self):
        r = self.fix("SELCT c.name, COUNT(o.id) FORM custmers c JOIN orders o WHERE COUNT(o.id) > 1")
        self.assertTrue(r.valid, r.remaining_error)
        self.assertGreaterEqual(len(r.issues), 4)

    def test_join_fixed_after_table_name_repair(self):
        r = self.fix("SELECT c.name FROM custmers c JOIN orders o")
        self.assertIn("ON c.id = o.customer_id", r.fixed)

    def test_unfixable_reports_error(self):
        r = self.fix("SELECT xyzzy FROM customers")
        self.assertFalse(r.valid)
        self.assertTrue(r.remaining_error)

    def test_string_literal_not_modified(self):
        r = self.fix("SELECT name FROM customers WHERE city = 'from where select'")
        self.assertEqual(r.issues, [])


if __name__ == "__main__":
    unittest.main()
