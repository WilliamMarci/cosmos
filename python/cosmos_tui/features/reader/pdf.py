"""PDF metadata, embedded outlines and whitespace-aware text matches."""

import re
from bisect import bisect_left, bisect_right
import unicodedata
import xml.etree.ElementTree as ET
from pypdf import PdfReader
from pypdf.errors import PdfReadError


def metadata(path):
    with open(path, "rb") as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("Password-protected PDF is not supported")
        pages = len(reader.pages)
        outline = []

        def walk(items, depth=0):
            if depth > 32:
                return
            for item in items:
                if len(outline) >= 10000:
                    return
                if isinstance(item, list):
                    walk(item, depth + 1)
                else:
                    page = reader.get_destination_page_number(item)
                    if page is not None:
                        outline.append(
                            dict(title=str(item.title), page=page + 1, depth=depth)
                        )

        try:
            walk(reader.outline)
        except (KeyError, TypeError, ValueError, PdfReadError):
            pass
        reader.close()
        return pages, outline


def parse_words(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("PDF text layer could not be decoded") from error
    result = []
    for page in root.iter():
        if page.tag.rsplit("}", 1)[-1] != "page":
            continue
        words = []
        for word in page.iter():
            if word.tag.rsplit("}", 1)[-1] == "word":
                words.append(
                    (
                        word.text or "",
                        tuple(
                            float(word.attrib[n])
                            for n in ("xMin", "yMin", "xMax", "yMax")
                        ),
                    )
                )
        result.append(
            dict(
                extent=(float(page.attrib["width"]), float(page.attrib["height"])),
                words=words,
            )
        )
    return result


def normalized(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def cjk(character):
    return bool(
        character
        and ("\u3400" <= character <= "\u9fff" or "\u3040" <= character <= "\u30ff")
    )


def matches(page, query):
    query = normalized(query)
    if not query:
        return []
    text, spans = "", []
    for index, (word, _) in enumerate(page["words"]):
        word = normalized(word)
        if not word:
            continue
        if text and not (cjk(text[-1]) and cjk(word[0])):
            text += " "
        start = len(text)
        text += word
        spans.append((start, len(text), index))
    starts = [left for left, _, _ in spans]
    ends = [right for _, right, _ in spans]
    results, start = [], 0
    while len(results) < 10000:
        found = text.find(query, start)
        if found < 0:
            break
        end = found + len(query)
        first, last = bisect_right(ends, found), bisect_left(starts, end)
        boxes = [page["words"][spans[i][2]][1] for i in range(first, last)]
        if boxes:
            results.append(boxes)
        start = found + max(1, len(query))
    return results
