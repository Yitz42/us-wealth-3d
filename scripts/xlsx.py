"""A small .xlsx reader (standard library only) for the Census and Smith-Zidar-Zwick spreadsheets.

read_xlsx(path) -> {sheet name: [(row number, {column letter: value as text})]}
"""
import re, zipfile, xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def read_xlsx(path):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheets = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
        target = rels[sh.get(REL)].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(target)).iter("{%s}row" % NS["m"]):
            cells = {}
            for c in row.findall("m:c", NS):
                col = re.match(r"[A-Z]+", c.get("r")).group(0)
                v = c.find("m:v", NS)
                if v is None:
                    inline = c.find("m:is", NS)
                    cells[col] = "".join(x.text or "" for x in inline.iter("{%s}t" % NS["m"])) if inline is not None else None
                else:
                    cells[col] = shared[int(v.text)] if c.get("t") == "s" else v.text
            rows.append((int(row.get("r")), cells))
        sheets[sh.get("name")] = rows
    return sheets
