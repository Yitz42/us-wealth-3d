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
        "education": around("education of the reference person, and categorical variable", before=0, after=2),
        "homeownership": around("homeownership class: 1=owns", before=0, after=1),
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


CBO_PAGE = "https://www.cbo.gov/publication/62761"
SIPP_STATES = "2023/wealth-asset-ownership/state_wealth_tables_dy2024.xlsx"
# Census CPS Historical Income Tables: H-2 shares and H-3 means of household income by fifth and top 5%.
CENSUS_INCOME = "https://www2.census.gov/programs-surveys/cps/tables/time-series/historical-income-households"
CENSUS_TABLES = ["h02ar.xlsx", "h03ar.xlsx"]
# BLS Consumer Expenditure Survey, by quintile of income before taxes (LB0101 all, LB0102-06 lowest to highest),
# through the BLS public API (bls.gov itself blocks scripted downloads). Version 1 needs no key: 10 years per request.
BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_SERIES = [f"CXU{item}{grp}M" for item in ("TOTALEXP", "INCBEFTX", "INCAFTTX") for grp in ("LB0101", "LB0102", "LB0103", "LB0104", "LB0105", "LB0106")]
BLS_FIRST = 1984


def bls_ce():
    out = {}
    last = int(subprocess.run(["date", "+%Y"], capture_output=True, text=True).stdout) - 1
    for a in range(BLS_FIRST, last + 1, 10):
        body = json.dumps({"seriesid": BLS_SERIES, "startyear": str(a), "endyear": str(min(a + 9, last))})
        r = json.loads(subprocess.run(["curl", "-sSf", "-X", "POST", "-H", "Content-Type: application/json", "-d", body, BLS_API],
                                      check=True, capture_output=True).stdout)
        if r["status"] != "REQUEST_SUCCEEDED":
            raise SystemExit(f"BLS API: {r['status']} {r.get('message')}")
        for series in r["Results"]["series"]:
            for d in series["data"]:
                out.setdefault(series["seriesID"], {})[d["year"]] = d["value"]
    return out


def census_income_doc():
    """Census's own title, universe and notes rows from the top of Table H-2."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from xlsx import read_xlsx
    rows = [str(c.get("A")) for _, c in next(iter(read_xlsx(RAW / "census" / "h02ar.xlsx").values()))[:7] if c.get("A")]
    return {"url": "https://www.census.gov/data/tables/time-series/demo/income-poverty/historical-income-households.html",
            "title": rows[1], "notes": " ".join(rows[2:])}


def cbo_doc():
    """CBO's own notes from its supplemental workbook (Contents and Notes sheet)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from xlsx import read_xlsx
    rows = [v for _, c in read_xlsx(RAW / "cbo" / "62761-supp-data.xlsx")["Contents and Notes"] for v in c.values() if v and v != "None"]
    notes = rows[rows.index("Notes:") + 1:]
    return {"url": CBO_PAGE, "title": rows[0], "notes": " ".join(notes)}


# The Fed's DFA download defines the wealth and asset columns but not the demographic groups; the
# generation birth years are on its table page (kept in the code, like the passages below).
DFA_GROUPS_DOC = {
    "url": "https://www.federalreserve.gov/releases/z1/dataviz/dfa/distribute/table/",
    "title": "Distributional Financial Accounts: Distribution of Household Wealth in the U.S. since 1989",
    "generations": "Silent and Earlier=born before 1946, Baby Boomer=born 1946-1964, Gen X=born 1965-1980, and Millennial=born 1981 or later.",
    "files": "dfa-race-levels-detail.csv, dfa-age-levels-detail.csv, dfa-education-levels-detail.csv, dfa-generation-levels-detail.csv and "
             "dfa-income-levels-detail.csv give quarterly holdings in millions of dollars and a Household count for each category.",
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

    # CBO: cbo.gov blocks scripted downloads (a bot check), so its files are saved by hand.
    if not (RAW / "cbo" / "62761-supp-data.xlsx").exists():
        print(f"cbo: download the supplemental data and the additional data for researchers from {CBO_PAGE} into data/raw/cbo/")

    (RAW / "sipp").mkdir(exist_ok=True)
    for year, path in SIPP_FILES.items():
        (RAW / "sipp" / f"wealth_tables_dy{year}.xlsx").write_bytes(get(f"{SIPP_TABLES}/{path}"))
    (RAW / "sipp" / "state_wealth_tables_dy2024.xlsx").write_bytes(get(f"{SIPP_TABLES}/{SIPP_STATES}"))
    print("sipp")

    (RAW / "census").mkdir(exist_ok=True)
    for name in CENSUS_TABLES:
        (RAW / "census" / name).write_bytes(get(f"{CENSUS_INCOME}/{name}"))
    print("census income")

    (RAW / "bls").mkdir(exist_ok=True)
    (RAW / "bls" / "ce_quintiles.json").write_text(json.dumps(bls_ce(), indent=1))
    print("bls")

    docs = {sid: fred_doc(sid) for sid in FRED_SERIES}
    docs["WID_shwealj992"] = wid_doc()
    docs["WID_shwealf992"] = wid_doc("shwealf992")
    docs["WID_sptincj992"] = wid_doc("sptincj992")
    docs["WID_ahwealj992"] = wid_doc("ahwealj992")
    docs["WID_sdiincj992"] = wid_doc("sdiincj992")
    docs["Census_CPS_income"] = census_income_doc()
    docs["SCF_codebook"] = scf_doc()
    docs["DFA_networth_shares"] = {
        "url": "https://www.federalreserve.gov/releases/z1/dataviz/dfa/",
        "title": "Distributional Financial Accounts: net worth shares by wealth percentile group",
        "definitions": (RAW / "dfa" / "dfa-data-definitions.txt").read_text(errors="replace")[:2500],
    }
    docs["Census_SIPP_wealth"] = sipp_doc()
    docs["DFA_groups"] = DFA_GROUPS_DOC
    if (RAW / "cbo" / "62761-supp-data.xlsx").exists():
        docs["CBO_household_income"] = cbo_doc()
    docs.update(LITERATURE)
    (RAW / "source_docs.json").write_text(json.dumps(docs, indent=2))
    print("source_docs.json")


if __name__ == "__main__":
    main()
