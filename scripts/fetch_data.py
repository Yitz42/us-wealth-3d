"""Download every raw input into data/raw/, plus each source's own documentation
(data/raw/source_docs.json) for the Jev meaning check in verify.py."""
import csv, html, io, json, pathlib, re, subprocess, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
FRED_SERIES = ["CPIAUCNS", "DPCERG3A086NBEA", "PCEPI", "PCECA", "PCE", "TTLHH", "TNWBSHNO", "A032RC1A027NBEA"]
DFA_ZIP = "https://www.federalreserve.gov/releases/z1/dataviz/download/zips/dfa.zip"
SCF_SURVEYS = [1989, 1992, 1995, 1998, 2001, 2004, 2007, 2010, 2013, 2016, 2019, 2022]
SCF_FILES = "https://www.federalreserve.gov/econres/files"


def get(url):
    # curl rather than urllib: FRED stalls urllib's TLS reads but serves curl reliably.
    return subprocess.run(["curl", "-sSfL", "--retry", "3", "--max-time", "120", url],
                          check=True, capture_output=True).stdout


def text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def fred_doc(series_id):
    page = get(f"https://fred.stlouisfed.org/series/{series_id}").decode("utf-8", "replace")
    title = text(re.search(r"<title>(.*?)</title>", page, re.S).group(1)).split(" | ")[0]
    units = re.search(r"<strong>Units:</strong>(.*?)</p>", page, re.S)
    cite = re.search(r'<p class="citation[^>]*>(.*?)</p>', page, re.S)
    freq = re.search(r"series-meta-value-frequency[^>]*>(.*?)<", page, re.S)
    notes = re.search(r"series-notes[^>]*>(.*?)</(?:div|p)>", page, re.S)
    return {
        "url": f"https://fred.stlouisfed.org/series/{series_id}",
        "title": title,
        "units": text(units.group(1)) if units else None,
        "frequency": text(freq.group(1)) if freq else None,
        "notes": text(notes.group(1))[:2500] if notes else None,
        "citation": text(cite.group(1)) if cite else None,
    }


def wid_doc(variable="shwealj992"):
    with open(RAW / "WID_metadata_US.csv", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["variable"] == variable:
                return {
                    "url": "https://wid.world/country/usa/",
                    "title": f"{row['shortname']} ({row['shorttype']})",
                    "country": row["countryname"],
                    "definition": row["simpledes"],
                    "share_convention": row["longtype"],
                    "population": f"{row['shortpop']}: {row['longpop']}",
                    "age_group": f"{row['shortage']}: {row['longage']}",
                    "method": row["method"],
                    "sources": re.sub(r"\[/?URL(_LINK|_TEXT)?\]", " ", row["source"]),
                }
    raise SystemExit(f"{variable} not found in WID metadata")


def scf_doc():
    """The SCF codebook is SAS code; keep the comment + assignment lines that define the
    variables the page uses, so Jev reads definitions rather than 160 KB of code."""
    lines = (RAW / "scf" / "bulletin.macro.txt").read_text(errors="replace").splitlines()
    def around(pattern, before=3, after=1):
        i = next(k for k, l in enumerate(lines) if pattern in l)
        return " ".join(l.strip() for l in lines[max(0, i - before): i + after + 1])
    return {
        "url": "https://www.federalreserve.gov/econres/scfindex.htm",
        "title": "Survey of Consumer Finances, summary extract variable definitions (bulletin.macro.txt)",
        "household_sex": around("HHSEX=X8021", before=1, after=0),
        "married": around("MARRIED=1;", before=3, after=1),
        "race": around("racecl4 1=white", before=0, after=1),
        "work_status": around("work status categories for reference person", before=0, after=4),
        "occupation": around("occupation classification for reference person", before=0, after=3),
        "total_assets": around("ASSET=FIN+NFIN", before=1, after=0),
        "net_worth": around("NETWORTH=ASSET-DEBT", before=1, after=0),
    }


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    for sid in FRED_SERIES:
        (RAW / f"{sid}.csv").write_bytes(get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"))
        print("fred", sid)

    zipfile.ZipFile(io.BytesIO(get(DFA_ZIP))).extractall(RAW / "dfa")
    print("dfa")

    subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_wid_us.py")], check=True)

    (RAW / "scf").mkdir(exist_ok=True)
    for year in SCF_SURVEYS:
        zipfile.ZipFile(io.BytesIO(get(f"{SCF_FILES}/scfp{year}excel.zip"))).extractall(RAW / "scf")
    (RAW / "scf" / "bulletin.macro.txt").write_bytes(get(f"{SCF_FILES}/bulletin.macro.txt"))
    print("scf")

    docs = {sid: fred_doc(sid) for sid in FRED_SERIES}
    docs["WID_shwealj992"] = wid_doc()
    docs["WID_shwealf992"] = wid_doc("shwealf992")
    docs["WID_sptincj992"] = wid_doc("sptincj992")
    docs["SCF_codebook"] = scf_doc()
    docs["DFA_networth_shares"] = {
        "url": "https://www.federalreserve.gov/releases/z1/dataviz/dfa/",
        "title": "Distributional Financial Accounts: net worth shares by wealth percentile group",
        "definitions": (RAW / "dfa" / "dfa-data-definitions.txt").read_text(errors="replace")[:2500],
    }
    (RAW / "source_docs.json").write_text(json.dumps(docs, indent=2))
    print("source_docs.json")


if __name__ == "__main__":
    main()
