# EPUB, Markdown and HTML readers

The integrated Reader accepts `.epub`, `.md`, `.markdown`, `.html` and `.htm` through the same `open FILE` / `cosmos open FILE` entry as images/PDF. They use `features/reader/documents.py`, not a second terminal application or browser process.

HTML parsing, semantic code coloring, tables and equation conversion are adapted from William Marci's ZhihuViewer (`richparse/htmlparse.py` and `mathtex.py`). The source origin and MIT license are retained alongside the parser. The original ZhihuViewer project does not have to remain installed. Markdown is converted to HTML by markdown-it-py, then follows the same parser. Dependencies are listed in python/requirements.txt.

## Presentation and navigation

Text is laid out in terminal cells, with an optional left outline generated from headings. Logical pages reflow with pane width and height. EPUB follows the OPF spine order, rather than ZIP/manifest file order; its chapter headings populate the same outline. This is a reflow reader, not fixed-layout EPUB rendering.

- `,` / `.` and `[` / `]` select previous/next logical pages.
- Arrow keys and h/j/k/l select adjacent logical pages; Home/End select the first/last page. The wheel changes pages.
- `t` / `o` folds the outline; click a heading to jump. Tab focuses the outline; arrows and Enter select/jump.
- `/` opens search in the source reader's bottom area. Enter submits, F3/Shift+F3 and n/N cycle matches. Matching is case-insensitive over reflowed text rows and highlights the query; cross-row phrase matching is not provided by this reader yet. Results are capped at 10000 matches.
- `g` opens the same pane-local page prompt. `q` / Escape closes reading.

The reader footer owns filename and page information; the global status bar shows DOC and the path. Confirmed reader state is retained in the Tmux pane. Pixel zoom/pan are meaningful for images/PDF; rich-text navigation uses reflow pages.

Local inline images are bounded and fitted into an eight-row text slot, can cross a logical-page boundary, and share the same graphics owner as the text. EPUB images are read inside the archive without extracting files. HTML/Markdown image references stay within the source directory. Remote and data URLs are not fetched; failed images show an inline reason. Character-only terminals retain text and image captions rather than replacing text with halfblocks.

## Input and resource boundaries

HTML scripts, styles, frames, media and JavaScript are not executed. This is a content reader, not a CSS/JavaScript browser. Links retain styling but are not browser-style navigation controls. Original HTML equation-image metadata uses the reused formula converter; optional utftex output falls back to the built-in Unicode converter.

Text files and EPUB text members are limited to 16 MiB; reflow is capped at 200000 rows. Expanded books are limited to 128 MiB / 10000 entries. EPUB image members use the configured single-image byte limit and the existing 16-million-pixel limit. Archive references are normalized and cannot escape the book container. DRM/fixed-layout EPUBs are not supported.

Parsed blocks and local decoded resources use the bounded persistent Reader cache described in viewer.md. Wrapped text/layout caches remain in memory. Cache keys include source identity and parser version; the disk entries contain JSON and PNG, never pickle or executable serialized objects.
