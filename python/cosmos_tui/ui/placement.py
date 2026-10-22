"""Bottom input geometry, optionally anchored to an application pane."""


def bottom_input_rect(app, rows, bounds=None):
    if bounds is None:
        bottom = app.size.height - int(app.query_one("#status").display)
        return 0, max(0, bottom - rows), app.size.width, min(rows, bottom)
    rect = bounds() if callable(bounds) else bounds
    if rect is None:
        return None
    x, y, width, height = rect
    x, y = max(0, x), max(0, y)
    width = max(1, min(width, app.size.width - x))
    height = max(1, min(height, app.size.height - y))
    rows = min(rows, height)
    return x, y + height - rows, width, rows


class PaneInputSurface:
    """Keep terminal graphics out of the source application's input rows."""

    def cover_reader_image(self, image, pane):
        bounds = getattr(self, "bounds", None)
        if bounds is None:
            return image
        rect = bounds() if callable(bounds) else bounds
        if rect != (pane.x, pane.y, pane.width, pane.height):
            return image
        visible = max(0, pane.height - self.input_rows)
        height = round(image.height * visible / max(1, pane.height))
        cached = getattr(self, "_reader_underlay", None)
        if cached and cached[0] is image and cached[1] == height:
            return cached[2]
        cropped = image.crop((0, 0, image.width, max(1, height)))
        self._reader_underlay = image, height, cropped
        return cropped
