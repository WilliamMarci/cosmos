"""Reading layout, thumbnail bounds, source-coordinate geometry, and interaction."""

import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / n) for n in ("python", "terminal_agent")
]
from cosmos_tui.features.reader.media import Media  # noqa: E402
from cosmos_tui.features.reader.layout import Reader  # noqa: E402
from cosmos_tui.app import DARK  # noqa: E402


class ReadingTests(unittest.TestCase):
    def test_gallery_and_footer_do_not_overlap_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(3):
                Image.new("RGB", (600, 400), (index * 70, 40, 120)).save(
                    Path(tmp) / f"{index}.png"
                )
            state = dict(path=str(Path(tmp) / "1.png"), page=1, zoom=1, pan=[0, 0])
            media = Media()
            reader = Reader(media)
            source, pages, _ = media.load(state)
            frame = reader.render(source, state, pages, 80, 24, (10, 20), DARK, True)
            self.assertEqual(frame.image.size, (800, 480))
            self.assertEqual(frame.main_rows, 18)
            self.assertEqual(frame.selected, 1)
            self.assertEqual(len(frame.hits), 4)
            self.assertIn("2/3", frame.lines[frame.main_rows].plain)
            self.assertTrue(
                all(
                    top > frame.main_rows
                    for _, top, _, _, index in frame.hits
                    if index >= 0
                )
            )
            self.assertEqual(
                Path(reader.change(state, 2, frame.entries)["path"]).name, "2.png"
            )
            self.assertIs(
                frame, reader.render(source, state, pages, 80, 24, (10, 20), DARK, True)
            )

    def test_document_navigation_is_left_and_collapses(self):
        # Stub thumbnail decoding to isolate layout from Poppler availability.
        media = Media()
        media.thumbnail = lambda state, bounds: Image.new("RGB", (30, 40), "white")
        source = Image.new("RGB", (600, 800), "white")
        state = dict(path="/tmp/document.pdf", page=2, zoom=1, pan=[0, 0])
        reader = Reader(media)
        frame = reader.render(source, state, 10, 80, 24, (10, 20), DARK, True)
        self.assertGreater(frame.main_x, 0)
        self.assertEqual(frame.main_rows, 23)
        self.assertTrue(all(x == 0 for x, _, _, _, index in frame.hits if index >= 0))
        self.assertEqual(len([h for h in frame.hits if h[-1] >= 0]), 4)
        folded = reader.render(
            source, dict(state, thumbnails=False), 10, 80, 24, (10, 20), DARK, True
        )
        self.assertEqual(folded.main_x, 0)
        self.assertEqual(folded.main_cols, 80)
        self.assertFalse(any(index >= 0 for *_, index in folded.hits))

    def test_image_navigation_collapse_gives_height_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            Image.new("RGB", (600, 400), "blue").save(path)
            media = Media()
            reader = Reader(media)
            state = dict(path=str(path), page=1, zoom=1, pan=[0, 0])
            source, pages, _ = media.load(state)
            expanded = reader.render(source, state, pages, 80, 24, (10, 20), DARK, True)
            folded = reader.render(
                source,
                dict(state, thumbnails=False),
                pages,
                80,
                24,
                (10, 20),
                DARK,
                True,
            )
            self.assertEqual(folded.main_rows - expanded.main_rows, 5)
            self.assertEqual(expanded.main_x, 0)

    def test_pan_clamps_and_fit_centers_on_both_axes(self):
        source = Image.new("RGB", (1200, 800), "red")
        media = Media()
        scale, pan = media.geometry(
            source, dict(zoom=1, pan=[100000, -100000]), 600, 400
        )
        self.assertEqual(scale, 0.5)
        self.assertEqual(pan, (0, 0))
        scale, pan = media.geometry(
            source, dict(zoom=2, pan=[100000, -100000]), 600, 400
        )
        self.assertEqual(pan, (300, -200))
        self.assertEqual(
            media.viewport(
                source, dict(zoom=2, pan=[100000, -100000]), 600, 400, "#14161e"
            ).getpixel((300, 200)),
            (255, 0, 0),
        )

    def test_tiny_panes_do_not_allocate_filmstrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tiny.png"
            Image.new("RGB", (10, 10), "blue").save(path)
            state = dict(path=str(path), page=1, zoom=1, pan=[0, 0])
            media = Media()
            source, pages, _ = media.load(state)
            frame = Reader(media).render(
                source, state, pages, 10, 2, (8, 16), DARK, False
            )
            self.assertEqual(frame.main_rows, 2)
            self.assertEqual(len(frame.lines), 2)
            self.assertFalse(frame.hits)


if __name__ == "__main__":
    unittest.main()
