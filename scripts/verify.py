"""Verify data/wealth.json against the raw sources.

Part A (code): every number is re-derived from the raw files and compared exactly.
Part B (Jev):  every claim the page makes about what a series *means* (definition,
               population, units) is checked against that source's own documentation.
               Arithmetic stays in code; Jev only judges meaning.

Writes data/verification.json and data/verification.js (read by index.html).
Jev calls need TYPESAFE_API_KEY; responses are cached in data/jev_cache.json.
"""
import csv, hashlib, json, os, pathlib, statistics, urllib.error, urllib.request
from collections import defaultdict

from build_scf import SCALE, age_part  # the age slider's rule, shared with the page's copy in index.html

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
AUTO_ACCEPT = 0.8  # below this confidence a verdict is shown as "needs review"

# Claims the page makes, grouped by the source whose documentation should back them.
# `expect` is the verdict a correct checker should give; the two "contradicts" rows are
# deliberately wrong controls, so a passing run shows the check can actually catch errors.
CLAIMS = {
    "WID_shwealj992": [
        ("wid_definition", "supports",
         "Each value is the share of total US net personal wealth (assets minus debts) held by one percentile group."),
        # Narrower pieces of wid_definition, so a flag on it shows which part the documentation disputes.
        ("wid_wealth_not_population", "supports",
         "For a percentile range such as p42p43, the value is the share of total wealth held by that group, not the share of the population in it."),
        ("wid_net_of_debt", "supports", "Wealth is measured as assets minus debts."),
        ("wid_country", "supports", "The data covers the United States."),
        ("wid_population", "supports",
         "The ranked population is adults aged 20 and over, with wealth split equally between members of a couple."),
        ("wid_pre1980", "supports",
         "Values before 1980 are constructed from trends in income-tax (fiscal income) data rather than measured directly."),
        ("control_wid_households", "contradicts",
         "Percentiles rank US households, with each household counted as one unit."),
    ],
    "WID_sptincj992": [
        ("wid_income_definition", "supports",
         "Pre-tax national income counts income from both labor and capital before taxes and transfers, with pensions counted when they are paid out."),
        # The combined claim above, split into literal parts (TypeSafe's advice for compound claims).
        ("wid_income_factors", "supports", "Pre-tax national income includes income flowing to the owners of both labor and capital."),
        ("wid_income_pretax", "supports", "Pre-tax national income is measured before the tax and transfer system is taken into account."),
        ("wid_income_pensions", "supports", "Pre-tax national income counts pensions on a distribution basis."),
        ("control_wid_income_wages", "contradicts", "Pre-tax national income counts only wages and salaries."),
    ],
    "WID_ahwealj992": [
        ("wid_avg_per_adult", "supports",
         "The values are average net personal wealth per adult aged 20 and over, with wealth split equally between members of a couple."),
        ("control_wid_avg_household", "contradicts", "The values are average net worth per household, with each household counted once."),
    ],
    "SCF_codebook": [
        # Tests the source fact the page's "Couples" label rests on; the label itself is the page's wording.
        ("scf_couples", "supports",
         "The survey records whether the reference person is married or living with a partner, or neither."),
        ("scf_race", "supports",
         "Race groups are White non-Hispanic, Black non-Hispanic, Hispanic or Latino, and Other or multiple races."),
        ("scf_networth", "supports", "A household's net worth is its total assets minus its total debt."),
        ("control_scf_race_two", "contradicts", "Race is recorded in only two groups: white and non-white."),
        ("scf_occupation", "supports",
         "Occupation groups are managerial or professional; technical, sales or services; other work such as production, labor or farming; and not working."),
        ("scf_work_status", "supports",
         "Work status groups are: working for someone else; self-employed or in a partnership; retired or disabled, plus anyone else not working who is 65 or older; and other people not working, mainly under 65."),
        # The page's women/men split rests on this: only one partner's sex is recorded, so couples count as one of each.
        ("scf_sex", "supports", "The sex recorded for a household is the sex of its reference person."),
        ("control_scf_sex_both", "contradicts", "The sex recorded for a household is the sex of every adult in it."),
        ("scf_age", "supports", "The age recorded for a household is the age of its reference person."),
        # The page regroups AGE into the Fed DFA's ranges, which needs AGE to be a plain number, not a class code.
        ("scf_age_numeric", "supports", "AGE holds the age itself as a number; the survey's age classes are then cut from it at 35, 45, 55, 65 and 75."),
        ("control_scf_age_oldest", "contradicts", "The age recorded for a household is the age of its oldest member."),
    ],
    "TNWBSHNO": [
        ("z1_networth", "supports",
         "Total net worth of US households and nonprofit organizations, measured in millions of US dollars."),
        ("control_z1_billions", "contradicts",
         "Total net worth of US households and nonprofit organizations, measured in billions of US dollars."),
    ],
    "BOGZ1FL192090005Q": [("z1_households_only", "supports",
                           "Net worth of US households alone (the household sector, not combined with nonprofits), measured in millions of US dollars.")],
    # The page's "Where sources disagree" section summarizes these papers; each summary is checked here.
    "SmithZidarZwick_2023": [
        ("szz_top1_lower", "supports",
         "Smith, Zidar and Zwick estimate the top 1% share of US wealth in 2016 at 33.7%, lower than the 36.6% in the series of Piketty, Saez and Zucman."),
        ("szz_top1_rising", "supports", "Smith, Zidar and Zwick also find that the top 1% share of wealth rose between 1989 and 2016."),
        ("control_szz_top1_fell", "contradicts", "Smith, Zidar and Zwick find that the top 1% share of wealth fell between 1989 and 2016."),
    ],
    # The Trends tab plots their data; these check its unit and coverage against their own files.
    "SmithZidarZwick_2023_data": [
        ("szz_unit", "supports",
         "The series ranks individuals, with a tax unit's wealth split equally between its members, rather than households."),
        ("szz_columns", "supports",
         "The baseline series gives shares of total wealth for the bottom 90%, top 10%, top 1%, top 0.1% and top 0.01%."),
        ("szz_years", "supports", "The baseline series is annual, from 1966 to 2016."),
        ("control_szz_household", "contradicts", "The series ranks households, the same unit as the Survey of Consumer Finances."),
    ],
    "Census_SIPP_wealth": [
        ("sipp_networth", "supports", "Household net worth is the value of assets owned minus debts owed, so it can be negative."),
        ("sipp_household", "supports",
         "The unit is the household: the people living together in one housing unit, with group quarters left out."),
        ("sipp_mean_bottom99", "supports", "The mean values in Table 5 are estimated only over households whose net worth is below the 99th percentile."),
        ("sipp_median_2024", "supports", "Median household net worth in 2024 was $204,900."),
        ("control_sipp_mean_all", "contradicts", "The published mean net worth includes every household, the wealthiest 1% among them."),
        ("control_sipp_furnishings", "contradicts", "Net worth includes the value of home furnishings."),
    ],
    "CBO_household_income": [
        ("cbo_ranking", "supports", "Households are ranked by their income before transfers and taxes, adjusted for household size."),
        ("cbo_people", "supports", "Each income quintile contains about the same number of people, not the same number of households."),
        ("cbo_federal_taxes", "supports",
         "The taxes counted are federal: individual income taxes, payroll taxes, corporate income taxes and excise taxes."),
        ("cbo_transfers", "supports",
         "Means-tested transfers include Medicaid and CHIP, SNAP and Supplemental Security Income."),
        ("cbo_pce", "supports", "Dollar amounts are adjusted for inflation with the price index for personal consumption expenditures."),
        ("cbo_capital_gains", "supports", "Market income includes realized capital gains."),
        ("control_cbo_households", "contradicts", "Each income quintile contains exactly the same number of households."),
        ("control_cbo_cpi", "contradicts", "Dollar amounts are adjusted for inflation with the consumer price index for urban consumers (CPI-U)."),
    ],
    "AutenSplinter_2024": [
        ("as_lower", "supports",
         "Auten and Splinter estimate top pre-tax income shares that are lower, and have risen less since 1980, than other studies using tax data."),
        ("control_as_aftertax_rise", "contradicts", "Auten and Splinter find that top after-tax income shares have risen sharply."),
    ],
    "PikettySaezZucman_2024_comment": [
        ("psz_reply", "supports",
         "Piketty, Saez and Zucman argue that, once some of Auten and Splinter's assumptions are corrected, their estimates become similar in level and trend to Piketty, Saez and Zucman's own."),
    ],
    "IselinReck_2024_comment": [
        ("ir_reply", "supports",
         "Iselin and Reck argue that the evidence threatens Auten and Splinter's assumption about who holds unreported income, especially pass-through business income."),
    ],
    "TTLHH": [("households", "supports", "The number of US households, measured in thousands.")],
    "CPIAUCNS": [("cpi_u", "supports",
                  "CPI-U: the consumer price index for all urban consumers, all items, US city average, not seasonally adjusted.")],
    "DPCERG3A086NBEA": [("pce_price_annual", "supports",
                         "An annual chain-type price index for personal consumption expenditures, indexed to 2017=100.")],
    "PCEPI": [("pce_price_monthly", "supports",
               "A monthly chain-type price index for personal consumption expenditures, indexed to 2017=100.")],
    "PCECA": [("pce_annual", "supports",
               "Annual US consumer spending (personal consumption expenditures) in billions of dollars.")],
    "PCE": [("pce_monthly", "supports",
             "Monthly US consumer spending (personal consumption expenditures) in billions of dollars at a seasonally adjusted annual rate.")],
    "DFA_networth_shares": [("dfa_groups", "supports",
                             "Quarterly shares of US household net worth held by the top 0.1%, next 0.9%, next 9%, next 40% and bottom 50% of the wealth distribution.")],
}

# Claims Jev disputes because of the source's wording, where the data settles the question.
# A disputed row becomes "explained" only when its evidence check passes in code.
SOURCE_WORDING = {
    "wid_wealth_not_population": (
        "WID's metadata says pXpY values store \"the share of the population between thresholds pX and pY\", "
        "which read literally means population share. The data shows wealth shares: {evidence}"),
}
SOURCE_WORDING["wid_definition"] = SOURCE_WORDING["wid_wealth_not_population"]

# Combined claims whose literal parts are checked separately. A disputed combined claim becomes
# "explained" only when every part passes on its own.
SPLIT_CLAIMS = {"wid_income_definition": ["wid_income_factors", "wid_income_pretax", "wid_income_pensions"]}


def wealth_share_evidence(w):
    """If WID values were population shares, every 1% bin would be exactly 1%. Returns (ok, text)."""
    share, years = w["measures"]["share"], w["years"]
    wid = [j for j, y in enumerate(years) if w["tier"][str(y)] != "extended_dfa"]
    top = [share[99][j] for j in wid]
    totals = [sum(share[i][j] for i in range(100)) for j in wid]
    ok = min(top) > 5 and all(abs(t - 100) < 0.5 for t in totals)
    return ok, (f"the top 1% bin holds {min(top):.1f}%–{max(top):.1f}% (not 1%) in every year "
                f"{years[wid[0]]}–{years[wid[-1]]}, and each year's 100 bins sum to 100%.")


VERDICTS = {
    "supports": "The documentation states or directly implies the claim, including its units and population.",
    "contradicts": "The documentation states something incompatible with the claim, such as different units, a different population, or a different definition.",
    "not_addressed": "The documentation neither confirms nor rules out the claim.",
}


# ---------------------------------------------------------------- Part A: code checks
def fred(series_id):
    with open(RAW / f"{series_id}.csv") as f:
        return {r["observation_date"]: float(r[series_id]) for r in csv.DictReader(f) if r[series_id] not in ("", ".")}


def code_checks(w):
    checks = []

    def record(name, ok, detail, info=False):
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "info": info})

    years, bins = w["years"], w["bins"]
    share = w["measures"]["share"]
    wid, agg = defaultdict(dict), defaultdict(dict)
    with open(RAW / "WID_data_US.csv") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["variable"] == "shwealj992" and int(r["year"]) >= years[0]:
                (wid if r["percentile"] in bins else agg)[int(r["year"])][r["percentile"]] = float(r["value"])
    wid_years = [y for y in years if w["tier"][str(y)] != "extended_dfa"]

    # 1. every published WID cell copied exactly; every estimate replaces a published 0
    #    and still rounds back to it (WID rounds shares to 0.0001 of total = 0.01 pp)
    est = w["estimated"]
    mismatches, bad_est, n_est = [], [], 0
    for y in wid_years:
        j = years.index(y)
        for i, b in enumerate(bins):
            if est[i][j]:
                n_est += 1
                if wid[y][b] != 0 or round(share[i][j] / 100, 4) != 0:
                    bad_est.append((b, y))
            elif abs(share[i][j] - round(wid[y][b] * 100, 4)) > 1e-9:
                mismatches.append((b, y))
    n = len(wid_years) * 100
    record("WID shares copied exactly", not mismatches,
           f"{n - n_est - len(mismatches)}/{n - n_est} published cells match WID_data_US.csv"
           + (f"; first mismatch {mismatches[0]}" if mismatches else ""))
    record("Grey estimates are consistent with WID", not bad_est,
           f"{n_est} cells WID rounded to 0 are estimated; "
           + (f"{len(bad_est)} would not round back to 0, first {bad_est[0]}" if bad_est else "all still round to 0"))

    # 2. 100 bins add to ~100% (WID publishes shares rounded to 0.01 pp, so allow drift)
    worst = max(abs(sum(share[i][j] for i in range(100)) - 100) for j in range(len(years)))
    record("Each year's 100 bins sum to 100%", worst < 0.5, f"largest deviation {worst:.3f} percentage points")

    # 3. our bin sums agree with WID's own published group aggregates
    gaps = []
    for y in wid_years:
        j = years.index(y)
        for p, (lo, hi) in {"p0p50": (0, 50), "p50p90": (50, 90), "p90p100": (90, 100)}.items():
            if p in agg[y]:
                gaps.append(abs(sum(share[i][j] for i in range(lo, hi)) - agg[y][p] * 100))
    record("Bin sums match WID's bottom-50 / middle-40 / top-10 aggregates", max(gaps) < 0.5,
           f"{len(gaps)} comparisons, largest gap {max(gaps):.3f} pp")

    # 4. extended years move each group exactly with its DFA group (up to one common renormalization)
    dfa = defaultdict(lambda: defaultdict(float))
    with open(RAW / "dfa" / "dfa-networth-shares.csv") as f:
        for r in csv.DictReader(f):
            g = "RemainingTop1" if r["Category"] == "TopPt1" else r["Category"]
            dfa[r["Date"]][g] += float(r["Net worth"])
    groups = {"Bottom50": (0, 50), "Next40": (50, 90), "Next9": (90, 99), "RemainingTop1": (99, 100)}
    last_wid = wid_years[-1]
    base_q = max(q for q in dfa if q.startswith(f"{last_wid}:"))
    spreads = []
    for y, q in w["dfa_quarter_used"].items():
        j, j0 = years.index(int(y)), years.index(last_wid)
        k = [sum(share[i][j0] for i in range(lo, hi)) for lo, hi in groups.values()]
        ratios = [sum(share[i][j] for i in range(lo, hi)) / kk / (dfa[q][g] / dfa[base_q][g])
                  for (g, (lo, hi)), kk in zip(groups.items(), k)]
        spreads.append(max(ratios) - min(ratios))
    record("Post-WID years track Fed DFA group changes", all(s < 1e-3 for s in spreads),
           f"years {', '.join(w['dfa_quarter_used'])}; scale factors agree within {max(spreads, default=0):.2e}")

    # 5. macro inputs match FRED raw files
    z1, z1_hh, hh = fred("TNWBSHNO"), fred("BOGZ1FL192090005Q"), {int(d[:4]): v for d, v in fred("TTLHH").items()}
    first_hh = min(z1_hh)
    hh_part = z1_hh[first_hh] / z1[first_hh]  # households' part of households + nonprofits, first quarter both exist
    n_scaled = 0
    cpi = defaultdict(list)
    for d, v in fred("CPIAUCNS").items():
        cpi[int(d[:4])].append(v)
    bad = []
    for y in years:
        m = w["macro"][str(y)]
        qy, qn = m["net_worth_quarter"].split(":Q")
        month = f"{qy}-{(int(qn) - 1) * 3 + 1:02d}-01"
        expect_nw = z1_hh[month] if month in z1_hh else z1[month] * hh_part  # households only; earlier years scaled
        n_scaled += month not in z1_hh
        if abs(m["net_worth_total"] - expect_nw * 1e6) > 1: bad.append((y, "net worth"))
        if y in hh and abs(m["households"] - hh[y] * 1e3) > 1: bad.append((y, "households"))
        if abs(m["cpi_u"] - statistics.mean(cpi[y])) > 1e-9: bad.append((y, "cpi"))
    record("Macro inputs match FRED files", not bad,
           f"{len(years)} years x 3 series; household net worth is households only (BOGZ1FL192090005Q) from {first_hh[:4]}, "
           f"and for the {n_scaled} earlier years the households-and-nonprofits total (TNWBSHNO) x {hh_part:.1%}"
           + (f"; bad {bad[:3]}" if bad else ""))

    # 6. dollar cells are per ADULT: WID's own average (constant 2025 $) x WID's price index,
    #    re-read from the raw file for every WID year; 2025-26 are estimates and are checked for
    #    consistency with the extended shares instead
    wavg, wpx = defaultdict(dict), {}
    with open(RAW / "WID_data_US.csv") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["variable"] in ("ahwealj992", "aptincj992") and r["percentile"] in bins:
                wavg[(r["variable"], int(r["year"]))][r["percentile"]] = float(r["value"])
            elif r["variable"] == "inyixxi999" and r["percentile"] == "p0p100":
                wpx[int(r["year"])] = float(r["value"])
    worst, n_cells = 0.0, 0
    for j, y in enumerate(wid_years):
        jj = years.index(y)
        for i, b in enumerate(bins):
            expect = wavg[("ahwealj992", y)][b] * wpx[y]
            worst = max(worst, abs(w["measures"]["nominal"][i][jj] - expect)); n_cells += 1
    ext = [y for y in years if w["tier"][str(y)] == "extended_dfa"]
    ratio_spread = 0.0
    for y in ext:  # within an extended year, dollars are proportional to the extended shares
        jj = years.index(y)
        rs = [w["measures"]["nominal"][i][jj] / share[i][jj] for i in range(100) if abs(share[i][jj]) > 0.05]
        ratio_spread = max(ratio_spread, (max(rs) - min(rs)) / statistics.mean(rs))
    record("Dollar values = WID's average per adult x WID's price index", worst <= 0.5 and ratio_spread < 0.01,
           f"{n_cells} cells {wid_years[0]}-{wid_years[-1]} match ahwealj992 x inyixxi999 within ${worst:.2f}; "
           f"{', '.join(map(str, ext))} (estimates) stay proportional to the extended shares")

    # informational: how far WID's top-1% share sits from the Fed's top-1% (different units and methods)
    diffs = []
    for y in range(1989, last_wid + 1):
        q = max((q for q in dfa if q.startswith(f"{y}:")), default=None)
        if q:
            diffs.append((y, share[99][years.index(y)] - dfa[q]["RemainingTop1"]))
    avg = statistics.mean(d for _, d in diffs)
    # 7. SCF bins (breakdowns), ranked by wealth and by income
    scf = json.loads((ROOT / "data" / "scf.json").read_text())
    worst_bin, worst_cat, worst_hold, worst_part = 0.0, 0.0, 0.0, 0.0
    hh_gap = []
    for ranking, F in scf["rankings"].items():
        for si, year in enumerate(scf["surveys"]):
            total = sum(F["w"][si])
            worst_bin = max(worst_bin, max(abs(wb / total * 100 - 1) for wb in F["w"][si]))
            for b in range(100):
                wb = F["w"][si][b]
                for group in ("race", "occupation", "work"):
                    worst_cat = max(worst_cat, abs(sum(F[k][si][b] for k, _ in scf["categories"][group]) - wb) / wb)
                # gender counts adults: every household once, plus the second partner in a couple
                couples = F["women_couple"][si][b]
                worst_cat = max(worst_cat, abs(sum(F[k][si][b] for k, _ in scf["categories"]["gender"]) - F["adults"][si][b]) / wb,
                                abs(F["adults"][si][b] - wb - couples) / wb, abs(F["men_couple"][si][b] - couples) / wb)
                bin_sum = F["networth" if ranking == "wealth" else "income"][si][b]
                worst_part = max(worst_part, abs(F["part_women"][si][b] + F["part_men"][si][b] - bin_sum))
                assets = F["assets"][si][b]
                if assets > 1e6:
                    worst_hold = max(worst_hold, abs(sum(F[k][si][b] for k, _ in scf["categories"]["holdings"]) - assets) / assets)
            if ranking == "wealth":
                hh_gap.append(f"{year} {total / (hh[year] * 1e3) - 1:+.0%}")
    record("SCF: each percentile bin holds 1% of households", worst_bin < 0.25,
           f"{len(scf['surveys'])} surveys x 2 rankings (wealth, income); largest bin is off by {worst_bin:.2f} percentage points of households")
    record("SCF: household groups add up to each bin", worst_cat < 1e-5 and worst_part <= 2,  # sums are stored rounded to whole units
           f"race, occupation and work status add up to households; women and men add up to adults (households plus the second "
           f"partner in each couple), and their net worth or income to the bin's; largest relative gap {worst_cat:.1e}, "
           f"largest dollar gap ${worst_part:.0f} (stored sums are rounded to whole units)")
    record("SCF: the seven holding types add up to total assets", worst_hold < 1e-6,
           f"largest relative gap {worst_hold:.1e} (bins with over $1M of weighted assets)")
    record("SCF households vs Census count", True, "SCF weighted households vs FRED TTLHH: " + ", ".join(hh_gap), info=True)
    checks.extend(age_checks(w, scf))

    # 8. pre-tax income (WID sptincj992): same exactness checks as wealth
    inc = w["income"]
    ishare, iest = inc["measures"]["share"], inc["estimated"]
    iw, iagg = defaultdict(dict), defaultdict(dict)
    with open(RAW / "WID_data_US.csv") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["variable"] == "sptincj992" and int(r["year"]) >= years[0]:
                (iw if r["percentile"] in bins else iagg)[int(r["year"])][r["percentile"]] = float(r["value"])
    bad, bad_est, n_est, worst_sum, worst_agg = [], [], 0, 0.0, 0.0
    for y in inc["years"]:
        j = years.index(y)
        for i, b in enumerate(bins):
            if iest[i][j]:
                n_est += 1
                if iw[y][b] != 0 or round(ishare[i][j] / 100, 4) != 0:
                    bad_est.append((b, y))
            elif abs(ishare[i][j] - round(iw[y][b] * 100, 4)) > 1e-9:
                bad.append((b, y))
        worst_sum = max(worst_sum, abs(sum(ishare[i][j] for i in range(100)) - 100))
        for pc, (lo, hi) in {"p0p50": (0, 50), "p50p90": (50, 90), "p90p100": (90, 100)}.items():
            if pc in iagg[y]:
                worst_agg = max(worst_agg, abs(sum(ishare[i][j] for i in range(lo, hi)) - iagg[y][pc] * 100))
    n = len(inc["years"]) * 100
    record("Income: WID shares copied exactly", not bad and not bad_est,
           f"{n - n_est - len(bad)}/{n - n_est} published cells match; {n_est} cells WID rounded to 0 are estimated and still round to 0"
           + (f"; first mismatch {(bad + bad_est)[0]}" if bad or bad_est else ""))
    record("Income: bins sum to 100% and match WID's group totals", worst_sum < 0.5 and worst_agg < 0.5,
           f"{inc['years'][0]}-{inc['years'][-1]}; largest deviation {worst_sum:.3f} pp from 100%, {worst_agg:.3f} pp from WID's bottom-50 / middle-40 / top-10")
    worst_d = 0.0
    for y in inc["years"]:
        j = years.index(y)
        for i, b in enumerate(bins):
            worst_d = max(worst_d, abs(inc["measures"]["nominal"][i][j] - wavg[("aptincj992", y)][b] * wpx[y]))
    record("Income: dollar values = WID's average per adult x WID's price index", worst_d <= 0.5,
           f"{len(inc['years']) * 100} cells {inc['years'][0]}-{inc['years'][-1]} match aptincj992 x inyixxi999 within ${worst_d:.2f}")

    # 9. top 0.1% and top 0.01% (Trends lines): copied exactly, and nested inside the top 1%
    td = w["top_detail"]
    raw_top = defaultdict(dict)
    with open(RAW / "WID_data_US.csv") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["variable"] in ("shwealj992", "sptincj992") and r["percentile"] in ("p99.9p100", "p99.99p100"):
                raw_top[(r["variable"], r["percentile"])][int(r["year"])] = float(r["value"])
    bad, nest, n_cells = [], [], 0
    for m, var, top1 in (("wealth", "shwealj992", w["measures"]["share"][99]), ("income", "sptincj992", w["income"]["measures"]["share"][99])):
        for key, pc in (("top01", "p99.9p100"), ("top001", "p99.99p100")):
            for j, y in enumerate(years):
                v = td[m][key]["share"][j]
                if v is None:
                    continue
                n_cells += 1
                if abs(v - round(raw_top[(var, pc)][y] * 100, 4)) > 1e-9:
                    bad.append((m, key, y))
        for j, y in enumerate(years):
            a, b, c = td[m]["top001"]["share"][j], td[m]["top01"]["share"][j], top1[j]
            if None not in (a, b, c) and not (0 <= a <= b <= c):
                nest.append((m, y))
    record("Top 0.1% and 0.01% copied exactly from WID", not bad,
           f"{n_cells - len(bad)}/{n_cells} values match WID (p99.9p100, p99.99p100)" + (f"; first mismatch {bad[0]}" if bad else ""))
    record("Top 0.01% <= top 0.1% <= top 1% every year", not nest,
           "wealth and income, every year WID publishes" + (f"; first break {nest[0]}" if nest else ""))

    # 10. the Fed's own numbers for the Trends source switch: shares from its levels match its
    #     published (one-decimal) shares, add up to 100%, and the top 0.1% sits inside the top 1%
    fd = w["fed_detail"]
    pub = defaultdict(dict)
    with open(RAW / "dfa" / "dfa-networth-shares.csv") as f:
        for r in csv.DictReader(f):
            pub[r["Date"]][r["Category"]] = float(r["Net worth"])
    worst_pub, worst_sum, bad_nest, n_yrs = 0.0, 0.0, [], 0
    for ys_, q in fd["quarter"].items():
        j = years.index(int(ys_)); n_yrs += 1
        G = {k: fd["groups"][k]["share"][j] for k in fd["groups"]}
        P = pub[q]
        for mine, theirs in ((G["bottom50"], P["Bottom50"]), (G["middle40"], P["Next40"]), (G["next9"], P["Next9"]),
                             (G["top01"], P["TopPt1"]), (G["top1"], P["TopPt1"] + P["RemainingTop1"])):
            worst_pub = max(worst_pub, abs(mine - theirs))
        worst_sum = max(worst_sum, abs(G["bottom50"] + G["middle40"] + G["next9"] + G["top1"] - 100))
        if not (0 <= G["top01"] <= G["top1"]):
            bad_nest.append(ys_)
    record("Fed DFA series match the Fed's published shares", worst_pub <= 0.11 and worst_sum < 0.01 and not bad_nest,
           f"{n_yrs} year-end quarters; shares from the Fed's dollar levels differ from its one-decimal published shares by at most "
           f"{worst_pub:.2f} pp (rounding, two groups rounded for the top 1%); groups sum to 100% within {worst_sum:.3f} pp; top 0.1% inside top 1%")

    record("Cross-source: WID vs Fed top-1% share", True,
           f"WID is on average {avg:+.1f} pp vs Fed DFA over {diffs[0][0]}-{diffs[-1][0]} (adults vs households; expected)", info=True)
    checks += other_source_checks(w)
    return checks


# The Fed's published 2022 SCF figures (Changes in U.S. Family Finances from 2019 to 2022, Federal Reserve
# Bulletin, October 2023, Table 2), in 2022 dollars.
SCF_2022_PUBLISHED = {"median": 192_900, "mean": 1_063_700}


def other_source_checks(w):
    """Smith-Zidar-Zwick shares, Census SIPP net worth, and the SCF medians and means, re-read from the raw files."""
    from xlsx import read_xlsx
    checks = []

    def record(name, ok, detail, info=False):
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "info": info})

    years = w["years"]
    # Smith-Zidar-Zwick: every value copied exactly, and the groups nest.
    rows = read_xlsx(RAW / "szz" / "Supplemental Data" / "TotalWealthShare.xlsx")["Baseline"]
    cols = {"B": "bottom90", "C": "top10", "D": "top1", "E": "top01", "F": "top001"}
    raw = {int(c["A"]): {k: float(c[col]) for col, k in cols.items()} for _, c in rows[2:] if c.get("B") not in (None, "")}
    worst, bad = 0.0, []
    for y, v in raw.items():
        j = years.index(y)
        worst = max(worst, *(abs(w["szz"][k][j] - v[k]) for k in cols.values()))
        if not (v["top001"] <= v["top01"] <= v["top1"] <= v["top10"] and abs(v["bottom90"] + v["top10"] - 100) < 0.01):
            bad.append(y)
    extra = [years[j] for j in range(len(years)) if w["szz"]["top1"][j] is not None and years[j] not in raw]
    record("Smith–Zidar–Zwick shares copied exactly", worst == 0 and not bad and not extra,
           f"{len(raw)} years {min(raw)}–{max(raw)} from TotalWealthShare.xlsx (Baseline); largest difference {worst:g} pp; "
           f"top 0.01% ≤ 0.1% ≤ 1% ≤ 10% and bottom 90% + top 10% = 100% every year" + (f"; problems in {bad}" if bad else ""))

    # Census SIPP: medians and means copied, medians below means, households near the Census count used elsewhere.
    sp = w["sipp"]
    worst, n_hh = 0.0, []
    for i, y in enumerate(sp["years"]):
        sh = read_xlsx(RAW / "sipp" / f"wealth_tables_dy{y}.xlsx")
        t1, t5, t4 = (dict(sh[f"Table {n}"]) for n in (1, 5, 4))
        worst = max(worst, abs(float(t1[5]["B"]) - sp["median"][i]), abs(float(t5[5]["B"]) - sp["mean"][i]))
        n_hh.append(sp["households"][i] / w["macro"][str(y)]["households"] - 1)
    order_ok = all(m < a for m, a in zip(sp["median"], sp["mean"]))
    record("Census SIPP net worth copied exactly", worst == 0 and order_ok and max(map(abs, n_hh)) < 0.04,
           f"{len(sp['years'])} years {sp['years'][0]}–{sp['years'][-1]} (Tables 1 and 5, Total row); largest difference ${worst:g}; "
           f"median below the bottom-99% mean every year; SIPP's household count is within {max(map(abs, n_hh)):.1%} of the Census count (FRED TTLHH)")

    # SCF medians and means: 2022 against the Fed's published figures.
    scf = json.loads((ROOT / "data" / "scf.json").read_text())
    t = scf["typical"]
    k = scf["surveys"].index(2022)
    gaps = {m: t[m][k] / SCF_2022_PUBLISHED[m] - 1 for m in SCF_2022_PUBLISHED}
    record("SCF 2022 median and mean match the Fed's published figures", all(abs(g) < 0.01 for g in gaps.values()),
           f"median ${t['median'][k]:,} vs ${SCF_2022_PUBLISHED['median']:,} published ({gaps['median']:+.2%}); mean ${t['mean'][k]:,} vs "
           f"${SCF_2022_PUBLISHED['mean']:,} ({gaps['mean']:+.2%}). The Fed averages its five imputed copies one at a time; this pools them.")

    # CBO: the research CSVs match CBO's workbook, and each table adds up.
    cbo = w["cbo"]
    sh = read_xlsx(RAW / "cbo" / "62761-supp-data.xlsx")
    names = {"All quintiles": "all_quintiles", "Lowest quintile": "lowest_quintile", "Second quintile": "second_quintile",
             "Middle quintile": "middle_quintile", "Fourth quintile": "fourth_quintile", "Highest quintile": "highest_quintile",
             "81st to 90th percentiles": "percentiles_81_90", "91st to 95th percentiles": "percentiles_91_95",
             "96th to 99th percentiles": "percentiles_96_99", "Top 1 percent": "top_1_percent"}
    sheets = {"3. Avg HH Income": ["market_inc", "social_insurance_benefits", "inc_before_transfers_taxes", "means_tested_transfers",
                                   "federal_taxes", "inc_after_transfers_taxes"],
              "10. Household Income Shares": ["share_market", "share_before", "share_after"]}
    n_cells, worst, unknown = 0, 0.0, set()
    for sheet, fields in sheets.items():
        for _, c in sh[sheet]:
            label = str(c.get("A") or "").strip()
            if not str(c.get("B") or "").isdigit():
                continue
            g = names.get(label)
            if g is None:
                unknown.add(label); continue
            i = cbo["years"].index(int(c["B"]))
            for col, f in zip("CDEFGH", fields):
                worst = max(worst, abs(float(c[col]) - cbo["groups"][g][f][i])); n_cells += 1
    G = cbo["groups"]
    split = max(abs(sum(G[k][f][i] for k in ("percentiles_81_90", "percentiles_91_95", "percentiles_96_99", "top_1_percent")) - G["highest_quintile"][f][i])
                for f in ("share_before", "share_after") for i in range(len(cbo["years"])))
    ident = max(abs(G[g]["inc_before_transfers_taxes"][i] + G[g]["means_tested_transfers"][i] - G[g]["federal_taxes"][i] - G[g]["inc_after_transfers_taxes"][i])
                for g in G for i in range(len(cbo["years"])))
    record("CBO data match CBO's workbook and add up", worst < 1e-9 and not unknown and split <= 0.25 and ident <= 200,
           f"{n_cells:,} values in the research CSVs equal the supplemental workbook (Tables 3 and 10), {cbo['years'][0]}–{cbo['years'][-1]}; "
           f"81st–90th + 91st–95th + 96th–99th + top 1% = highest quintile within {split:.2f} pp (rounding); "
           f"before + transfers − taxes = after within ${ident:,.0f} for every group and year (CBO rounds to $100)"
           + (f"; unrecognised groups {sorted(unknown)}" if unknown else ""))
    wj = [(y, years.index(y)) for y in cbo["years"] if y in w["income"]["years"]]
    gaps = [sum(w["income"]["measures"]["share"][i][j] for i in range(99, 100)) - G["top_1_percent"]["share_before"][cbo["years"].index(y)] for y, j in wj]
    record("Cross-source: WID vs CBO top-1% income share", True,
           f"WID's pre-tax national income share of the top 1% is on average {sum(gaps) / len(gaps):+.1f} pp vs CBO's income before transfers and taxes "
           f"over {wj[0][0]}–{wj[-1][0]} (range {min(gaps):+.1f} to {max(gaps):+.1f}): WID ranks adults and counts all national income, "
           f"CBO ranks people by household income adjusted for size, and counts household income rather than all national income", info=True)

    # Information: the two surveys in the one year both cover (SCF dollars are 2022 dollars).
    i = sp["years"].index(2022)
    record("Cross-source: SIPP vs SCF, 2022", True,
           f"median ${sp['median'][i]:,.0f} (SIPP) vs ${t['median'][k]:,} (SCF), {sp['median'][i] / t['median'][k] - 1:+.0%}; "
           f"mean below the 99th percentile ${sp['mean'][i]:,.0f} vs ${t['mean_below_p99'][k]:,}, {sp['mean'][i] / t['mean_below_p99'][k] - 1:+.0%}. "
           f"The SCF oversamples wealthy households; SIPP isn't built to measure wealth at the top.", info=True)
    return checks


# The Fed DFA's age groups, as inclusive ranges of the household head's age (the SCF records 18-95).
GROUP_AGES = {"age_u40": (0, 39), "age_40_54": (40, 54), "age_55_69": (55, 69), "age_70p": (70, 999)}


def age_checks(w, scf):
    """The age selector: age groups re-derived from the raw SCF files, and the trim fractions the page applies."""
    checks = []

    def record(name, ok, detail, info=False):
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "info": info})

    ages = [a for a, _ in scf["categories"]["age"]]
    assert list(GROUP_AGES) == ages, "age groups changed; update GROUP_AGES"
    bounds = {a: (lo, hi + 1) for a, (lo, hi) in GROUP_AGES.items()}

    # 1. each age group's sums add up to the bin's; households by age add up to the bin's households
    worst = 0.0
    for F in scf["rankings"].values():
        for si in range(len(scf["surveys"])):
            for b in range(100):
                for k in ("w", "n", "networth", "income", "assets", "debt"):
                    worst = max(worst, abs(sum(F["by_age"][a][k][si][b] for a in ages) - F[k][si][b]))
                worst = max(worst, abs(sum(F[a][si][b] for a in ages) - F["w"][si][b]))
    record("SCF: age groups add up to each bin", worst <= 3,  # each stored sum is rounded to a whole unit
           f"households, net worth, income, assets and debt, both rankings; largest gap {worst:.0f} (stored sums are rounded to whole units)")

    # 2. the age groups, re-derived from the raw files (AGE of the reference person), match the stored sums
    worst_rel = 0.0
    for si, year in enumerate(scf["surveys"]):
        with open(RAW / "scf" / f"SCFP{year}.csv", newline="") as f:
            rows = csv.reader(f)
            head = next(rows)
            ia, iw, inw = head.index("AGE"), head.index("WGT"), head.index("NETWORTH")
            hh_age, nw_age = defaultdict(float), defaultdict(float)
            for r in rows:
                age = int(r[ia])
                a = next(g for g, (lo, hi) in bounds.items() if lo <= age < hi)
                hh_age[a] += float(r[iw])
                nw_age[a] += float(r[iw]) * float(r[inw])
        F = scf["rankings"]["wealth"]
        for a in ages:
            worst_rel = max(worst_rel, abs(sum(F[a][si]) - hh_age[a]) / hh_age[a],
                            abs(sum(F["by_age"][a]["networth"][si]) - nw_age[a]) / abs(nw_age[a]))
    record("SCF: age groups match the raw survey files", worst_rel < 1e-6,
           f"{len(scf['surveys'])} surveys, households and net worth for under 40, 40-54, 55-69 and 70+ recomputed from AGE; "
           f"largest relative gap {worst_rel:.1e}")

    # 3. per-age shares (age_cells, used by the page's age slider) add up to each bin, and to each age group's sums
    worst_sum, worst_grp, n_mixed, seen = 0.0, 0.0, 0, set()
    for name, key in (("wealth", "networth"), ("income", "income")):
        F = scf["rankings"][name]
        for si, bins in enumerate(scf["age_cells"][name]):
            for b, cell in enumerate(bins):
                n_mixed += len(cell) == 3
                seen.update(cell[0])
                total = F[key][si][b]
                # net worth / income shares (all 0 in a bin that sums to exactly 0), then household shares if stored
                for shares in cell[1:] if total else cell[2:]:
                    worst_sum = max(worst_sum, abs(sum(shares) / SCALE - 1))
                for a in ages:
                    lo, hi = GROUP_AGES[a]
                    got = sum(v for x, v in zip(cell[0], cell[1]) if lo <= x <= hi) / SCALE
                    expect = F["by_age"][a][key][si][b] / total if total else 0
                    worst_grp = max(worst_grp, abs(got - expect) / max(1, abs(expect)))
    record("SCF: per-age shares add up to each bin and each age group", worst_sum < 1e-3 and worst_grp < 1e-3,
           f"2 rankings x {len(scf['surveys'])} surveys x 100 bins, ages {min(seen)}-{max(seen)}; "
           f"each bin's ages add to 100% within {worst_sum:.1e}, and to each age group's sums within {worst_grp:.1e}; "
           f"{n_mixed} bins where ages differ in sign also carry household shares")

    # informational: the page's age-group share of all wealth vs the Fed DFA's (both from the SCF, different ranking and totals)
    dfa = defaultdict(lambda: defaultdict(list))
    with open(RAW / "dfa" / "dfa-age-shares.csv") as f:
        for r in csv.DictReader(f):
            dfa[int(r["Date"][:4])][r["Category"]].append(float(r["Net worth"]))
    dfa_key = {"age_u40": "ageunder40", "age_40_54": "age40to54", "age_55_69": "age55to69", "age_70p": "age70plus"}
    share, years = w["measures"]["share"], w["years"]
    gaps = defaultdict(list)
    for si, year in enumerate(scf["surveys"]):
        j = years.index(year)
        for a in ages:
            page = sum(share[b][j] * age_part(scf["age_cells"]["wealth"][si][b], *GROUP_AGES[a]) for b in range(100))
            gaps[a].append(page - statistics.mean(dfa[year][dfa_key[a]]))
    labels = dict(scf["categories"]["age"])
    record("Cross-source: age groups' share of wealth vs Fed DFA", True,
           "page minus DFA, average over the " + str(len(scf["surveys"])) + " survey years: "
           + ", ".join(f"{labels[a]} {statistics.mean(g):+.1f} pp (range {min(g):+.1f} to {max(g):+.1f})" for a, g in gaps.items())
           + ". The page splits WID's adult-based bins by the survey's age mix; DFA uses household totals", info=True)
    return checks


# ---------------------------------------------------------------- Part B: Jev meaning checks
class JevUnavailable(Exception):
    """Jev can't be reached for an uncached request; the reason is shown on the page."""


def ask_jev(state, questions, cache):
    body = {"state": state, "model": MODEL, "questions": questions}
    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    if key in cache:
        return cache[key]
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise JevUnavailable("TYPESAFE_API_KEY is not set")
    req = urllib.request.Request(
        TYPESAFE_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        cache[key] = json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise JevUnavailable(f"TypeSafe rejected TYPESAFE_API_KEY (HTTP {e.code}); check the key") from None
        raise JevUnavailable(f"TypeSafe API error HTTP {e.code}: {e.read().decode(errors='replace')[:200]}") from None
    except urllib.error.URLError as e:
        raise JevUnavailable(f"could not reach TypeSafe API ({e.reason})") from None
    return cache[key]


def jev_checks(docs, w):
    cache_path = ROOT / "data" / "jev_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    results, pending, model, reason = [], [], None, None
    try:
        for source, claims in CLAIMS.items():
            questions = {
                cid: {
                    "type": "choice",
                    "instructions": {
                        "page_claim": claim,
                        "question": "Judged only by the source documentation in the state, how does it relate to "
                                    "`page_claim`? Compare units, population and definition literally.",
                    },
                    "criteria": VERDICTS,
                }
                for cid, _, claim in claims
            }
            try:
                resp = ask_jev({"source_documentation": docs[source]}, questions, cache)
            except JevUnavailable as e:
                reason = str(e)
                pending += [{"id": cid, "source": source, "claim": claim, "expect": expect, "status": "pending",
                             "control": cid.startswith("control_")} for cid, expect, claim in claims]
                continue
            model = resp.get("model", model)
            for cid, expect, claim in claims:
                a = resp["answers"][cid]
                results.append({
                    "id": cid, "source": source, "claim": claim, "expect": expect,
                    "verdict": a["choice"], "confidence": round(a["confidence"], 3),
                    "probabilities": a["probabilities"],
                    "status": ("pass" if a["choice"] == expect else "fail") if a["confidence"] >= AUTO_ACCEPT else "review",
                    "control": cid.startswith("control_"),
                })
    finally:
        if cache:  # keep answers already paid for; never leave an empty cache behind
            cache_path.write_text(json.dumps(cache, indent=1))
    if not results:
        return {"status": "not_run", "reason": reason, "results": []}
    by_id = {r["id"]: r for r in results}
    for cid, parts in SPLIT_CLAIMS.items():
        r = by_id.get(cid)
        if r and r["status"] in ("fail", "review") and all(by_id.get(pid, {}).get("status") == "pass" for pid in parts):
            r["status"] = "explained"
            r["note"] = ("Jev was unsure about this combined claim (it has to link \"when they are paid out\" to WID's "
                         "\"distribution basis\"), but each part passes on its own: "
                         + "; ".join(f"{by_id[pid]['claim']} ({by_id[pid]['confidence']:.2f})" for pid in parts))
    ok, evidence = wealth_share_evidence(w)
    for r in results:
        if r["id"] in SOURCE_WORDING and r["status"] in ("fail", "review") and ok:
            r["status"] = "explained"
            r["note"] = SOURCE_WORDING[r["id"]].format(evidence=evidence)
    # Cached answers still count; claims whose request couldn't run are listed as pending.
    return {"status": "partial" if pending else "run", "reason": reason, "model": model,
            "auto_accept": AUTO_ACCEPT, "results": results + pending}


def main():
    w = json.loads((ROOT / "data" / "wealth.json").read_text())
    docs = json.loads((RAW / "source_docs.json").read_text())
    out = {"code_checks": code_checks(w), "jev": jev_checks(docs, w)}
    (ROOT / "data" / "verification.json").write_text(json.dumps(out, indent=1))
    (ROOT / "data" / "verification.js").write_text("window.VERIFICATION = " + json.dumps(out) + ";\n")
    import stamp_versions  # data files just changed: point index.html at the new versions
    stamp_versions.main()

    for c in out["code_checks"]:
        print(f"[{'info' if c['info'] else 'ok' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}")
    j = out["jev"]
    if j["status"] != "run":
        print(f"[skip] Jev meaning checks{' (some)' if j['results'] else ''}: {j['reason']}")
    for r in j["results"]:
        if r["status"] == "pending":
            print(f"[pending] {r['id']}: not yet checked")
        else:
            print(f"[{r['status']}] {r['id']}: {r['verdict']} (conf {r['confidence']}, expected {r['expect']})")
            if r.get("note"):
                print(f"           {r['note']}")


if __name__ == "__main__":
    main()
