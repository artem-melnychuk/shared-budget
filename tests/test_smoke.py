import unittest

import budget


class SmokeTest(unittest.TestCase):
    def test_package_imports(self):
        self.assertTrue(budget.__version__)


if __name__ == "__main__":
    unittest.main()
