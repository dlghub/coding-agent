import unittest

from text_utils import slugify


class SlugifyTests(unittest.TestCase):
    def test_words_and_spaces(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_repeated_separators_collapse(self):
        self.assertEqual(slugify("  One___Two---Three  "), "one-two-three")

    def test_non_ascii_is_removed(self):
        self.assertEqual(slugify("Café déjà vu"), "cafe-deja-vu")

    def test_empty_input(self):
        self.assertEqual(slugify(""), "")


if __name__ == "__main__":
    unittest.main()
