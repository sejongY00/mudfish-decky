import unittest

import mudfish_decky


class SmokeTest(unittest.TestCase):
    def test_package_imports(self):
        self.assertTrue(hasattr(mudfish_decky, "__name__"))


if __name__ == "__main__":
    unittest.main()
