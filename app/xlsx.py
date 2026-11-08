"""A small Excel (.xlsx) writer with no outside library (kohal, 2026-11-05: monthly reports in Excel format).

PythonAnywhere does not install new packages when the site deploys (see app/deploy.py), so rather than depend on
openpyxl this writes the handful of XML parts a workbook needs straight into a zip. It does only what the reports use:
several sheets, a bold header row, text / number / date cells, column widths and a frozen header - and, for a printed-style
table like the salary payment sheet (kohal, 2026-11-08), merged cells, a big title row, wrapped centred headers and boxed cells.

    build_workbook([
        {"name": "Leads", "rows": [["Company", "Value"], ["Acme", 1200.5]], "bold_rows": {0}, "freeze": 1, "filter": True},
    ]) -> bytes

Optional, per sheet: "merges" (["A1:T1", ...]), "row_styles" ({row index: "title" | "header" | "box" | "box_bold"} - a boxed
row is outlined across "box_cols" columns, blanks included) and "widths" ({column index: width}, overriding the automatic ones).

A cell value is a str, an int / float / Decimal (a number), a date or datetime (shown as a date), a bool, or None
(empty). Anything else is written as text."""

import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_SHEET_CHARS = re.compile(r"[\\/*?:\[\]]")
_EPOCH = datetime(1899, 12, 30)

# cellXfs in styles.xml, by index: 0 plain, 1 bold, 2 date, 3 number (2 decimals), 4 whole-number, 5 date and time;
# then the boxed table styles - 6 title, 7 header (bold, centred, wrapped), 8 text, 9 whole number, 10 2 decimals, 11 date,
# and 12-15 the same four in bold (a totals row).
_PLAIN, _BOLD, _DATE, _MONEY, _INT, _STAMP = 0, 1, 2, 3, 4, 5
_TITLE, _HEAD = 6, 7
_BOXED = {False: {"text": 8, "int": 9, "money": 10, "date": 11}, True: {"text": 12, "int": 13, "money": 14, "date": 15}}


def _col(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _clean(text: str) -> str:
    return escape(_ILLEGAL.sub("", text))


def _sheet_name(name: str, taken: set) -> str:
    base = _BAD_SHEET_CHARS.sub("-", str(name)).strip("'") or "Sheet"
    base = base[:31]
    candidate, n = base, 2
    while candidate.lower() in taken:
        suffix = f" {n}"
        candidate = base[:31 - len(suffix)] + suffix
        n += 1
    taken.add(candidate.lower())
    return candidate


def _serial(value) -> float:
    if isinstance(value, datetime):
        delta = value.replace(tzinfo=None) - _EPOCH          # Excel has no time zones - the wall-clock time is written
        return delta.days + delta.seconds / 86400
    return (datetime(value.year, value.month, value.day) - _EPOCH).days


def _boxed_cell(ref: str, value, style: str):
    """A cell of a boxed table row (see row_styles in the module docstring), and its width (a title row's is not counted)."""
    if style in ("title", "header"):
        s = _TITLE if style == "title" else _HEAD
        if value is None or value == "":
            return f'<c r="{ref}" s="{s}"/>', 0
        text = str(value)
        return (f'<c r="{ref}" t="inlineStr" s="{s}"><is><t xml:space="preserve">{_clean(text)}</t></is></c>',
                0 if style == "title" else max((len(line) for line in text.splitlines()), default=0))
    styles = _BOXED[style == "box_bold"]
    if value is None or value == "":
        return f'<c r="{ref}" s="{styles["text"]}"/>', 0
    if isinstance(value, (datetime, date)):
        return f'<c r="{ref}" s="{styles["date"]}"><v>{_serial(value)}</v></c>', 11
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = float(value)
        s = styles["int"] if number == int(number) else styles["money"]
        return f'<c r="{ref}" s="{s}"><v>{number!r}</v></c>', len(f"{number:,.2f}")
    text = str(value)
    return f'<c r="{ref}" t="inlineStr" s="{styles["text"]}"><is><t xml:space="preserve">{_clean(text)}</t></is></c>', len(text)


def _cell(ref: str, value, bold: bool):
    """The <c> element for one value, and how many characters wide it is (for the column width)."""
    if value is None or value == "":
        return (f'<c r="{ref}" s="{_BOLD}"/>' if bold else ""), 0
    if isinstance(value, bool):
        return f'<c r="{ref}" t="inlineStr"><is><t>{"Yes" if value else "No"}</t></is></c>', 3
    if isinstance(value, (datetime, date)):
        stamp = isinstance(value, datetime)
        return f'<c r="{ref}" s="{_STAMP if stamp else _DATE}"><v>{_serial(value)}</v></c>', 17 if stamp else 11
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        style = _INT if number == int(number) else _MONEY
        return f'<c r="{ref}" s="{style}"><v>{number!r}</v></c>', len(f"{number:,.2f}")
    text = str(value)
    style = f' s="{_BOLD}"' if bold else ""
    return (f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{_clean(text)}</t></is></c>',
            max((len(line) for line in text.splitlines()), default=0))


def _sheet_xml(rows, bold_rows, freeze, filter_row=False, merges=(), row_styles=None, box_cols=0, fixed_widths=None):
    widths = {}
    body = []
    row_styles = row_styles or {}
    for r, row in enumerate(rows):
        cells = []
        style = row_styles.get(r)
        values = list(row) + [None] * (box_cols - len(row)) if style else row
        for c, value in enumerate(values):
            ref = f"{_col(c)}{r + 1}"
            xml, width = _boxed_cell(ref, value, style) if style else _cell(ref, value, r in bold_rows)
            if xml:
                cells.append(xml)
            widths[c] = max(widths.get(c, 0), width)
        body.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
    widths = {c: min(max(w + 2, 8), 60) for c, w in widths.items()}
    widths.update(fixed_widths or {})
    cols = "".join(f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>'
                   for c, w in sorted(widths.items()))
    merged = (f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + '</mergeCells>') if merges else ""
    flt = (f'<autoFilter ref="A1:{_col(max(widths) if widths else 0)}{len(rows)}"/>' if filter_row and rows and widths else "")
    pane = (f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze}" topLeftCell="A{freeze + 1}" '
            f'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>') if freeze else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'{pane}<cols>{cols}</cols><sheetData>{"".join(body)}</sheetData>{flt}{merged}</worksheet>') if cols else (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'{pane}<sheetData>{"".join(body)}</sheetData></worksheet>')


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="2"><numFmt numFmtId="164" formatCode="dd\\ mmm\\ yyyy"/><numFmt numFmtId="165" formatCode="dd\\ mmm\\ yyyy\\ hh:mm"/></numFmts>'
    '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="14"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="16">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left"/></xf>'
    '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left"/></xf>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>'
    '<xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
    '<xf numFmtId="4" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/>'
    '<xf numFmtId="3" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyNumberFormat="1" applyBorder="1"/>'
    '<xf numFmtId="4" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyNumberFormat="1" applyBorder="1"/>'
    '<xf numFmtId="164" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def build_workbook(sheets) -> bytes:
    """`sheets` is a list of {"name", "rows", optional "bold_rows" (row indexes, 0-based), optional "freeze" (rows),
    optional "filter" (true puts Excel's filter buttons on the first row)}."""
    if not sheets:
        raise ValueError("A workbook needs at least one sheet")
    taken: set = set()
    names = [_sheet_name(s["name"], taken) for s in sheets]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(sheets)))
                   + '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{_clean(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
                   + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                             f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(
                s["rows"], set(s.get("bold_rows", ())), s.get("freeze", 0), s.get("filter", False), s.get("merges", ()),
                s.get("row_styles"), s.get("box_cols", 0), s.get("widths")))
    return buf.getvalue()
