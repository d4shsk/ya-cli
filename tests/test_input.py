from __future__ import annotations

import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from yandexcli.cli import decode_history_line, encode_history_item
from yandexcli.input import _active_at_token, _display_value, file_completion_choices, visible_input_text
from yandexcli.ui import prompt as ui_prompt, _plain


class InputTests(unittest.TestCase):
    def test_paste_display_hides_multiline_content(self) -> None:
        self.assertEqual(_display_value("one\ntwo\nthree", [3]), "[Вставлено строк: 3]")

    def test_history_items_are_json_encoded(self) -> None:
        item = "one\ntwo\nthree"
        encoded = encode_history_item(item)
        self.assertEqual(decode_history_line(encoded), item)

    def test_plain_history_lines_still_load(self) -> None:
        self.assertEqual(decode_history_line("старый промпт"), "старый промпт")

    def test_prompt_labels_modes(self) -> None:
        edit_prompt = ui_prompt(mode="edit", color=False)
        edit_lines = edit_prompt.splitlines()
        # New layout: 3 visible rows (input, meta, hint) + cursor escape line
        self.assertGreaterEqual(len(edit_lines), 3)
        # Row 0 (input) starts with bar
        self.assertTrue(edit_lines[0].lstrip().startswith("|"))
        # Row 1 (meta) starts with bar and contains mode label
        self.assertTrue(edit_lines[1].lstrip().startswith("|"))
        self.assertIn("Код", edit_lines[1])
        # Mode label present in prompt
        self.assertIn("Код", edit_prompt)
        self.assertIn("Tab режим", edit_prompt)
        # Plan mode has "План"
        self.assertIn("План", ui_prompt(mode="plan", color=False))

    def test_active_at_token_only_matches_at_started_token(self) -> None:
        self.assertEqual(_active_at_token("объясни @READ"), (8, "READ"))
        self.assertIsNone(_active_at_token("mail me@example.com"))
        self.assertIsNone(_active_at_token("объясни @README.md "))

    def test_file_completion_choices_return_at_references(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("hello", encoding="utf-8")
            (root / "notes dir").mkdir()
            (root / "notes dir" / "daily note.txt").write_text("note", encoding="utf-8")

            self.assertEqual(file_completion_choices(root, "read"), ["@README.md"])
            self.assertEqual(file_completion_choices(root, "daily"), ["@'notes dir/daily note.txt'"])

    def test_file_completion_with_subdirectories_and_skipped_dirs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "index.js").write_text("console.log()", encoding="utf-8")
            (root / "Library").mkdir()
            (root / "Library" / "cache.db").write_text("cache", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "some_dep.js").write_text("dep", encoding="utf-8")

            # Scanning from root should find index.js but skip Library and node_modules
            self.assertEqual(file_completion_choices(root, "index"), ["@src/index.js"])
            self.assertEqual(file_completion_choices(root, "cache"), [])
            self.assertEqual(file_completion_choices(root, "some_dep"), [])

            # Explicitly scanning inside a skipped directory should work if specified in query
            self.assertEqual(file_completion_choices(root, "Library/cache"), ["@Library/cache.db"])
            self.assertEqual(file_completion_choices(root, "src/ind"), ["@src/index.js"])

    def test_visible_input_text_clamps_long_input(self) -> None:
        """Long input should be clamped to inner_width (horizontal scroll)."""
        inner = 20
        long_text = "a" * 100
        vis, col = visible_input_text(long_text, [], inner)
        self.assertEqual(len(vis), inner)
        self.assertEqual(col, inner)
        # Shows the trailing slice
        self.assertEqual(vis, "a" * inner)

    def test_visible_input_text_short_input(self) -> None:
        """Short input returns as-is with cursor at end."""
        vis, col = visible_input_text("hello", [], 50)
        self.assertEqual(vis, "hello")
        self.assertEqual(col, 5)

    def test_visible_input_text_paste_summary(self) -> None:
        """Pasted content uses the [Вставлено строк: N] summary."""
        vis, col = visible_input_text("one\ntwo\nthree", [3], 50)
        self.assertEqual(vis, "[Вставлено строк: 3]")
        self.assertEqual(col, len("[Вставлено строк: 3]"))

    def test_prompt_frame_render_width_bounded(self) -> None:
        """Rendered rows never exceed box_width visible characters."""
        from yandexcli.ui import build_prompt_frame
        frame = build_prompt_frame("edit", color=False)
        output = frame.render("x" * 200, cursor_col=200)
        for line in output.splitlines():
            stripped = _plain(line)
            self.assertLessEqual(len(stripped), frame.left + frame.box_width,
                                 f"Row exceeds box boundary: {len(stripped)} > {frame.left + frame.box_width}")


if __name__ == "__main__":
    unittest.main()
