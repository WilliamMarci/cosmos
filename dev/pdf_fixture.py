"""Small deterministic PDF with searchable phrases and nested bookmarks."""

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def make_pdf(path):
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    texts = [
        "Introduction to Cosmos",
        "Needle hello world",
        "",
        "Chapter four",
        "Another needle hello world",
    ]
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 18 Tf 72 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    root = writer.add_outline_item("Introduction", 0)
    writer.add_outline_item("Search chapter", 1, parent=root)
    writer.add_outline_item("Last chapter", 4)
    with open(path, "wb") as output:
        writer.write(output)
