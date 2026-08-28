import unittest

from range_utils import values_below


class ValuesBelowTests(unittest.TestCase):
    def test_zero_is_empty(self):
        self.assertEqual(values_below(0), [])

    def test_upper_bound_is_excluded(self):
        self.assertEqual(values_below(4), [0, 1, 2, 3])

    def test_negative_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            values_below(-1)


if __name__ == "__main__":
    unittest.main()
