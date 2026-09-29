"""Download every raw input into data/raw/, plus each source's own documentation
(data/raw/source_docs.json) for the Jev meaning check in verify.py."""
import csv, html, io, json, pathlib, re, subprocess, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
FRED_SERIES = ["CPIAUCNS", "DPCERG3A086NBEA", "PCEPI", "PCECA", "PCE", "TTLHH", "TNWBSHNO", "BOGZ1FL192090005Q"]
DFA_ZIP = "https://www.federalreserve.gov/releases/z1/dataviz/download/zips/dfa.zip"
SCF_SURVEYS = [1989, 1992, 1995, 1998, 2001, 2004, 2007, 2010, 2013, 2016, 2019, 2022]
SCF_FILES = "https://www.federalreserve.gov/econres/files"
SZZ_ZIP = "https://www.ericzwick.com/wealth/Supplemental_data.zip"
# Census SIPP detailed wealth tables: data year -> file (names and folders vary by year).
SIPP_TABLES = "https://www2.census.gov/programs-surveys/demo/tables/wealth"
SIPP_FILES = {
    **{y: f"{y}/wealth-asset-ownership/wealth_tables_cy{y}.xlsx" for y in (2014, 2015, 2016, 2017)},
    **{y: f"{y}/wealth-asset-ownership/Wealth_tables_dy{y}.xlsx" for y in (2018, 2019, 2020, 2021)},
    2022: "2022/wealth-asset-ownership/wealth_tables_dy2022.xlsx",
    2023: "2023/wealth-asset-ownership/wealth_tables_dy2023.xlsx",
    2024: "2023/wealth-asset-ownership/wealth_tables_dy2024.xlsx",
}


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
        "age": around("AGE=X14;", before=2, after=1),
        "total_assets": around("ASSET=FIN+NFIN", before=1, after=0),
        "net_worth": around("NETWORTH=ASSET-DEBT", before=1, after=0),
    }


def sipp_doc():
    """Census's own notes from the latest SIPP wealth tables, plus the definitions in its report."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from xlsx import read_xlsx
    year = max(SIPP_FILES)
    sh = read_xlsx(RAW / "sipp" / f"wealth_tables_dy{year}.xlsx")
    def notes(table):
        rows = [str(c.get("A") or "") for _, c in sh[table]]
        return {"title": rows[1], "note": next(r for r in rows if r.startswith("NOTE"))[:900],
                "source": next(r for r in rows if r.startswith("Source"))}
    return {
        "url": "https://www.census.gov/topics/income-poverty/wealth/data/tables.html",
        "title": f"Census Bureau, Wealth, Asset Ownership, & Debt of Households Detailed Tables: {year} (Survey of Income and Program Participation)",
        "table_1": notes("Table 1"),
        "table_5": notes("Table 5"),
        # From the report on the same data (Wealth of Households: 2024, P70BR-218); the PDF isn't
        # machine-readable here, so the passage is kept in the code.
        "report_definitions": "A household consists of a group of people occupying a housing unit together (group quarters such as "
                              "dormitories, institutions, or nursing homes are excluded from this analysis). The householder is a person "
                              "who owns or rents the housing unit. Wealth is the value of assets owned minus the debts owed. Therefore, "
                              "wealth can be negative. The major assets not covered in this measure are equity in pension plans and the "
                              "value of home furnishings. The median household wealth in 2024 was $204,900.",
        "report_url": "https://www2.census.gov/library/publications/2026/demo/p70br-218.pdf",
    }


# Research that disputes the page's main sources. The page summarizes each in its "Where sources
# disagree" section; verify.py has Jev check those summaries against these passages, copied from
# the papers (the PDFs aren't machine-readable here, so the passages are kept in the code).
LITERATURE = {
    "SmithZidarZwick_2023": {
        "url": "https://academic.oup.com/qje/article/138/1/515/6678447",
        "title": "Smith, Zidar and Zwick (2023), Top Wealth in America: New Estimates under Heterogeneous Returns, Quarterly Journal of Economics 138(1)",
        "definitions": "PSZ refers to Piketty, Saez, and Zucman (2018), the series behind WID.world's US wealth shares.",
        "passage": "From 1989 to 2016, the top 1%, 0.1%, 0.01%, and 0.001% wealth shares in our baseline series increased by "
                   "6.6, 4.6, 2.9, and 1.7 percentage points, respectively, to 33.7%, 15.7%, 7.1%, and 3.2%. In the PSZ "
                   "series, wealth shares increased by 10.0, 7.9, 5.4, and 3.1 percentage points to 36.6%, 18.6%, 9.5%, and 4.6%. "
                   "Across all approaches, top wealth shares have steadily risen since the 1980s.",
    },
    # Their data files, which the Trends tab plots (TotalWealthShare.xlsx, Baseline sheet).
    "SmithZidarZwick_2023_data": {
        "url": "https://www.ericzwick.com/wealth/Supplemental_data.zip",
        "title": "Smith, Zidar and Zwick (2023), Top Wealth in America, replication package: TotalWealthShare.xlsx",
        "readme": "TotalWealthShare.xlsx contains estimates for the total wealth share of top wealth groups over time for the "
                  "baseline and each supplemental series.",
        "baseline_columns": "Year, Bottom 90%, Top 10%, Top 1%, Top 0.1%, Top 0.01%; annual, 1966 to 2016.",
        "unit_passage": "First, our approach defines the relevant observation at the individual level based on equal splits in "
                        "tax units, whereas the SCF unit of observation is the household.",
    },
    "AutenSplinter_2024": {
        "url": "https://www.journals.uchicago.edu/doi/10.1086/728741",
        "title": "Auten and Splinter (2024), Income Inequality in the United States: Using Tax Data to Measure Long-Term Trends, Journal of Political Economy 132(7)",
        "abstract": "Concerns about income inequality emphasize the importance of accurate income measures. Estimates of top "
                    "income shares based only on individual tax returns are biased by tax-base changes, social changes, and "
                    "missing income sources. This paper addresses these shortcomings and presents new estimates of the "
                    "distribution of national income since 1960. The analysis of pretax income shows that top income shares "
                    "are lower and have increased less since 1980 than other studies using tax data. In addition, increasing "
                    "government transfers and tax progressivity have resulted in rising real incomes for all income groups "
                    "and little change in aftertax top income shares.",
    },
    "PikettySaezZucman_2024_comment": {
        "url": "https://eml.berkeley.edu/~saez/PSZ2024.pdf",
        "title": "Piketty, Saez and Zucman (2024), Income Inequality in the United States: A Comment",
        "abstract_excerpt": "Auten and Splinter (2024) provide estimates of income inequality in the United States, starting with "
                            "income observed in tax returns and making adjustments to account for untaxed income. We uncover an "
                            "empirical issue in the allocation of untaxed income. [...] This creates a bias in the level and rise "
                            "of the top 1% income share. [...] After clarifying these assumptions and confronting them to existing "
                            "evidence, the Auten and Splinter (2024) estimates become similar in level and trend to those of "
                            "Piketty, Saez and Zucman (2018).",
    },
    "IselinReck_2024_comment": {
        "url": "https://www.danreck.com/s/CommentAutenSplinter-h75z.pdf",
        "title": "Iselin and Reck (2024), Comment on Auten and Splinter",
        "abstract_excerpt": "We assess Auten and Splinter's estimates of the top 1% share of income, focusing on tax non-compliance. "
                            "They assume the concentration of misreporting follows the 1/3 of total misreporting detected in "
                            "random audits. [...] Empirical data threaten this assumption. Most importantly, pass-through business "
                            "income is unexamined in random audits and grew dramatically after 1986. [...] Conceptual "
                            "disagreements explain 60% of the divergence between studies; a re-ranking issue explains the rest.",
    },
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

    zipfile.ZipFile(io.BytesIO(get(SZZ_ZIP))).extractall(RAW / "szz")
    print("szz")

    (RAW / "sipp").mkdir(exist_ok=True)
    for year, path in SIPP_FILES.items():
        (RAW / "sipp" / f"wealth_tables_dy{year}.xlsx").write_bytes(get(f"{SIPP_TABLES}/{path}"))
    print("sipp")

    docs = {sid: fred_doc(sid) for sid in FRED_SERIES}
    docs["WID_shwealj992"] = wid_doc()
    docs["WID_shwealf992"] = wid_doc("shwealf992")
    docs["WID_sptincj992"] = wid_doc("sptincj992")
    docs["WID_ahwealj992"] = wid_doc("ahwealj992")
    docs["SCF_codebook"] = scf_doc()
    docs["DFA_networth_shares"] = {
        "url": "https://www.federalreserve.gov/releases/z1/dataviz/dfa/",
        "title": "Distributional Financial Accounts: net worth shares by wealth percentile group",
        "definitions": (RAW / "dfa" / "dfa-data-definitions.txt").read_text(errors="replace")[:2500],
    }
    docs["Census_SIPP_wealth"] = sipp_doc()
    docs.update(LITERATURE)
    (RAW / "source_docs.json").write_text(json.dumps(docs, indent=2))
    print("source_docs.json")


if __name__ == "__main__":
    main()
