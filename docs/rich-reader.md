# EPUB, Markdown and HTML readers

The integrated Reader accepts `.epub`, `.md`, `.markdown`, `.html` and `.htm` through the same `open FILE` / `cosmos open FILE` entry as images/PDF. They use `features/reader/documents.py`, not a second terminal application or browser process.

HTML parsing, semantic code coloring, tables and equation conversion are adapted from William Marci's ZhihuViewer (`richparse/htmlparse.py` and `mathtex.py`). The source origin and MIT license are retained alongside the parser. The original ZhihuViewer project does not have to remain installed. Markdown is converted to HTML by markdown-it-py, then follows the same parser. Dependencies are listed in python/requirements.txt.

## Presentation and navigation

Text is laid out in terminal cells, with an optional left outline generated from headings. Logical pages reflow with pane width and height. EPUB follows the OPF spine order, rather than ZIP/manifest file order; its chapter headings populate the same outline. This is a reflow reader, not fixed-layout EPUB rendering.

- `c` cycles Auto / one / two / three columns; Auto uses the pane width and caps at three columns. Manual counts fall back when a column would be narrower than 24 cells. The reader footer exposes the same clickable selector.
- `v` switches paged / continuous-row scrolling. In scroll mode Up/Down (and k/j) move one row; Left/Right (h/l), PageUp/PageDown, `,` / `.` and `[` / `]` move a viewport. Columns are read top-to-bottom, then left-to-right. The mouse wheel follows the active mode.
- Tab / Shift+Tab select the next / previous paragraph or content block, bring it into view, and highlight it. Enter expands the selected image/table; `f` toggles a selected image's fold state and `y` copies a selected block.
- `t` / `o` folds the outline sidebar. Click a heading to jump; headings have immediate hover feedback and the current section is highlighted. Navigation follows the current content position; the wheel over the outline scrolls its list independently.
- `/` searches in the source reader's bottom area. Enter submits, F3/Shift+F3 and n/N cycle matches. Matching is case-insensitive over reflowed text rows; cross-row phrase matching is not provided. Results are capped at 10000 matches.
- `g` opens the pane-local page prompt. Home/End go to the start/end. `q` / Escape closes reading, or returns from an expanded asset first.

These defaults use the shared viewer keybinding registry and can be changed in Settings. Reader state (column policy, reading mode, position and folded images) is retained in the Tmux pane. Reflow on width changes recalculates logical pages.

Inline images fit within **eight rows** without upscaling. Smaller images retain their natural pixel dimensions. Images whose original width and height are both at most **64px** are treated as icons and receive no operation buttons. Other images have compact borderless single-line controls (fold/show, expand, copy) inspired by ZhihuViewer, using Cosmos theme roles and immediate hover; they start expanded (folding is Off). Expanded images reuse the existing image Reader viewport, geometry and rendering cache, occupy the source reader pane, support +/- zoom, arrows/hjkl pan and Space fit, and return without losing the text position. Inline and expanded images use the same graphics output owner as the text.

Tables use ZhihuViewer's cell-width-aware box renderer. Tables wider than the column appear as an Open table entry, rather than wrapping away their column alignment; other tables render inline. The expanded table supports horizontal/vertical navigation and a copy button. Both image and table controls have immediate hover feedback. Table/image views stay inside the source reader pane.

Copy uses an optional host clipboard adapter: wl-copy on Wayland or xclip on X11, with image/png for images and UTF-8 text for tables/text. Missing display/tools, SSH sessions without a configured clipboard transport, and failures report a notification rather than claiming success. This does not implement remote clipboard synchronization.

EPUB images are read inside the archive without extracting files. HTML/Markdown image references stay within the source directory. Remote and data URLs are not fetched; failed images show an inline reason. Character-only terminals retain text and image captions. The reader footer owns document controls and page information; the global status bar remains independent.

## Input and resource boundaries

HTML scripts, styles, frames, media and JavaScript are not executed. This is a content reader, not a CSS/JavaScript browser. Links retain styling but are not browser-style navigation controls. Original HTML equation-image metadata uses the reused formula converter; optional utftex output falls back to the built-in Unicode converter.

Text files and EPUB text members are limited to 16 MiB; reflow is capped at 200000 rows. Expanded books are limited to 128 MiB / 10000 entries. EPUB image members use the configured single-image byte limit and the existing 16-million-pixel limit. Archive references are normalized and cannot escape the book container. DRM/fixed-layout EPUBs are not supported.

Parsed blocks and local decoded resources use the bounded persistent Reader cache described in viewer.md. Wrapped text/layout caches remain in memory. Cache keys include source identity and parser version; the disk entries contain JSON and PNG, never pickle or executable serialized objects.
