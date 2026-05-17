from __future__ import annotations

import unittest

from yandexcli.cli import decode_history_line, encode_history_item
from yandexcli.input import _display_value


class InputTests(unittest.TestCase):
    def test_paste_display_hides_multiline_content(self) -> None:
        self.assertEqual(_display_value("one\ntwo\nthree", [3]), "[Вставлено строк: 3]")

    def test_history_items_are_json_encoded(self) -> None:
        item = "one\ntwo\nthree"
        encoded = encode_history_item(item)
        self.assertEqual(decode_history_line(encoded), item)

    def test_plain_history_lines_still_load(self) -> None:
        self.assertEqual(decode_history_line("старый промпт"), "старый промпт")


if __name__ == "__main__":
    unittest.main()
