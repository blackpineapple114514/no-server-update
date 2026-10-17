# -*- coding: utf-8 -*-
"""版本号比较。这里每一条都是踩过的坑。"""
import unittest

from nou.version import is_newer, max_version, parse


class TestParse(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse("1.2.3"), (1, 2, 3))
        self.assertEqual(parse("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse("  V2.0.0 "), (2, 0, 0))

    def test_padding(self):
        self.assertEqual(parse("1.2"), (1, 2, 0))
        self.assertEqual(parse("1"), (1, 0, 0))

    def test_prerelease_dropped(self):
        self.assertEqual(parse("1.2.3-beta.1"), (1, 2, 3))
        self.assertEqual(parse("1.2.3+build.9"), (1, 2, 3))

    def test_garbage_is_zero(self):
        self.assertEqual(parse(""), (0, 0, 0))
        self.assertEqual(parse("build-x"), (0, 0, 0))

    def test_padding_inside_segment(self):
        self.assertEqual(parse("1.02.3"), (1, 2, 3))


class TestCompare(unittest.TestCase):
    def test_numeric_not_lexicographic(self):
        # 字符串比较会把 "1.10.0" 判成小于 "1.9.0"
        self.assertTrue(is_newer("1.10.0", "1.9.0"))
        self.assertFalse(is_newer("1.9.0", "1.10.0"))

    def test_equal(self):
        self.assertFalse(is_newer("1.2.0", "1.2.0"))
        self.assertFalse(is_newer("v1.2.0", "1.2"))

    def test_empty_never_updates(self):
        self.assertFalse(is_newer("", "1.0.0"))
        self.assertFalse(is_newer("1.0.0", ""))

    def test_max_version(self):
        self.assertEqual(max_version(["1.9.0", "1.10.0", "1.2.0"]), "1.10.0")
        self.assertEqual(max_version(["x", "", "2.0"]), "2.0")
        self.assertEqual(max_version([]), "")


if __name__ == "__main__":
    unittest.main()
