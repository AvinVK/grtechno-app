"""A very small PDF writer, for the salary slip (kohal, 2026-11-10: "have a vertical salary slip ... have them downloadable as well").

No PDF library is installed on the server, so this writes the little a one-page slip needs by hand: text in Helvetica / Helvetica-Bold
(two of the 14 fonts every PDF viewer already has, so nothing is embedded), straight lines and filled boxes. Text is Latin-1 only - a
character outside it prints as "?" - and money is written "Rs." because the rupee sign is not in these fonts.

    page = Page()
    page.rect(0, 770, 595, 72, fill=(0.8, 0.2, 0.1))
    page.text(40, 800, "Salary slip", size=20, bold=True, color=(1, 1, 1))
    pdf_bytes = build_pdf([page], title="Salary slip")
"""

A4 = (595, 842)

# Advance widths (1/1000 em) of the printable ASCII characters 32..126, from the standard Helvetica font metrics.
_REGULAR = (
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + [278, 278, 584, 584, 584, 556, 1015]
    + [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611]
    + [278, 278, 278, 469, 556, 333]
    + [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500]
    + [334, 260, 334, 584]
)
_BOLD = (
    [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + [333, 333, 584, 584, 584, 611, 975]
    + [722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611]
    + [333, 278, 333, 584, 556, 333]
    + [556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500]
    + [389, 280, 389, 584]
)


def string_width(text: str, size: float, bold: bool = False) -> float:
    table = _BOLD if bold else _REGULAR
    return sum(table[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text) * size / 1000


def _latin1(text: str) -> bytes:
    return text.encode("cp1252", "replace")


def _escape(raw: bytes) -> bytes:
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _num(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".") or "0"


class Page:
    """One page's drawing, in points from the bottom-left corner (y counts up)."""

    def __init__(self, size=A4):
        self.width, self.height = size
        self._ops = []

    def text(self, x: float, y: float, text: str, size: float = 10, bold: bool = False, color=(0, 0, 0)) -> None:
        self._ops.append(f"{' '.join(_num(c) for c in color)} rg BT /{'F2' if bold else 'F1'} {_num(size)} Tf {_num(x)} {_num(y)} Td (".encode()
                         + _escape(_latin1(text)) + b") Tj ET")

    def text_right(self, x_right: float, y: float, text: str, size: float = 10, bold: bool = False, color=(0, 0, 0)) -> None:
        self.text(x_right - string_width(text, size, bold), y, text, size, bold, color)

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5, color=(0.8, 0.8, 0.8)) -> None:
        self._ops.append(f"{' '.join(_num(c) for c in color)} RG {_num(width)} w {_num(x1)} {_num(y1)} m {_num(x2)} {_num(y2)} l S".encode())

    def rect(self, x: float, y: float, w: float, h: float, fill=None, stroke=None, stroke_width: float = 0.8) -> None:
        parts = []
        if fill:
            parts.append(f"{' '.join(_num(c) for c in fill)} rg")
        if stroke:
            parts.append(f"{' '.join(_num(c) for c in stroke)} RG {_num(stroke_width)} w")
        op = "B" if fill and stroke else "f" if fill else "S"
        parts.append(f"{_num(x)} {_num(y)} {_num(w)} {_num(h)} re {op}")
        self._ops.append(" ".join(parts).encode())

    def content(self) -> bytes:
        return b"\n".join(self._ops)


def build_pdf(pages, title: str = "") -> bytes:
    """The finished PDF file for these pages."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]            # 1 catalog, 2 pages (filled in below)
    font1 = len(objects) + 1
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for page in pages:
        stream = page.content()
        content_no = len(objects) + 1
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page_no = len(objects) + 1
        kids.append(page_no)
        objects.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_num(page.width)} {_num(page.height)}] "
                        f"/Resources << /Font << /F1 {font1} 0 R /F2 {font1 + 1} 0 R >> >> /Contents {content_no} 0 R >>").encode())
    objects[1] = ("<< /Type /Pages /Kids [" + " ".join(f"{k} 0 R" for k in kids) + f"] /Count {len(kids)} >>").encode()
    info_no = len(objects) + 1
    objects.append(b"<< /Title (" + _escape(_latin1(title)) + b") /Producer (Lead desk) >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_no} 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)
