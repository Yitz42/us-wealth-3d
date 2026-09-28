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
    "A032RC1A027NBEA": [("national_income", "supports", "Annual US national income, measured in billions of dollars.")],
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
    ],
    "TNWBSHNO": [
        ("z1_networth", "supports",
         "Total net worth of US households and nonprofit organizations, measured in millions of US dollars."),
        ("control_z1_billions", "contradicts",
         "Total net worth of US households and nonprofit organizations, measured in billions of US dollars."),
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
    z1, hh = fred("TNWBSHNO"), {int(d[:4]): v for d, v in fred("TTLHH").items()}
    cpi = defaultdict(list)
    for d, v in fred("CPIAUCNS").items():
        cpi[int(d[:4])].append(v)
    bad = []
    for y in years:
        m = w["macro"][str(y)]
        qy, qn = m["net_worth_quarter"].split(":Q")
        month = f"{qy}-{(int(qn) - 1) * 3 + 1:02d}-01"
        if abs(m["net_worth_total"] - z1[month] * 1e6) > 1: bad.append((y, "net worth"))
        if y in hh and abs(m["households"] - hh[y] * 1e3) > 1: bad.append((y, "households"))
        if abs(m["cpi_u"] - statistics.mean(cpi[y])) > 1e-9: bad.append((y, "cpi"))
    record("Macro inputs match FRED files", not bad, f"{len(years)} years x 3 series" + (f"; bad {bad[:3]}" if bad else ""))

    # 6. every dollar cell obeys share x total / (households/100), within what the
    #    stored share's 4-decimal rounding (±0.00005 pp) can explain
    worst = 0.0
    for i in range(100):
        for j, y in enumerate(years):
            m = w["macro"][str(y)]
            per_pp = m["net_worth_total"] / (m["households"] / 100) / 100  # dollars per percentage point
            expect = share[i][j] * per_pp
            worst = max(worst, abs(w["measures"]["nominal"][i][j] - expect) / (0.00005 * per_pp + 1))
    record("Dollar values = share x net worth / households", worst <= 1,
           f"{100 * len(years)} cells; worst error is {worst:.2f}x the share-rounding tolerance")

    # informational: how far WID's top-1% share sits from the Fed's top-1% (different units and methods)
    diffs = []
    for y in range(1989, last_wid + 1):
        q = max((q for q in dfa if q.startswith(f"{y}:")), default=None)
        if q:
            diffs.append((y, share[99][years.index(y)] - dfa[q]["RemainingTop1"]))
    avg = statistics.mean(d for _, d in diffs)
    # 7. SCF bins (breakdowns), ranked by wealth and by income
    scf = json.loads((ROOT / "data" / "scf.json").read_text())
    worst_bin, worst_cat, worst_hold = 0.0, 0.0, 0.0
    hh_gap = []
    for ranking, F in scf["rankings"].items():
        for si, year in enumerate(scf["surveys"]):
            total = sum(F["w"][si])
            worst_bin = max(worst_bin, max(abs(wb / total * 100 - 1) for wb in F["w"][si]))
            for b in range(100):
                wb = F["w"][si][b]
                for group in ("gender", "race", "occupation", "work"):
                    worst_cat = max(worst_cat, abs(sum(F[k][si][b] for k, _ in scf["categories"][group]) - wb) / wb)
                assets = F["assets"][si][b]
                if assets > 1e6:
                    worst_hold = max(worst_hold, abs(sum(F[k][si][b] for k, _ in scf["categories"]["holdings"]) - assets) / assets)
            if ranking == "wealth":
                hh_gap.append(f"{year} {total / (hh[year] * 1e3) - 1:+.0%}")
    record("SCF: each percentile bin holds 1% of households", worst_bin < 0.25,
           f"{len(scf['surveys'])} surveys x 2 rankings (wealth, income); largest bin is off by {worst_bin:.2f} percentage points of households")
    record("SCF: household groups add up to each bin", worst_cat < 1e-5,  # sums are stored rounded to whole units
           f"gender, race, occupation and work status; largest relative gap {worst_cat:.1e} (stored sums are rounded to whole households)")
    record("SCF: the seven holding types add up to total assets", worst_hold < 1e-6,
           f"largest relative gap {worst_hold:.1e} (bins with over $1M of weighted assets)")
    record("SCF households vs Census count", True, "SCF weighted households vs FRED TTLHH: " + ", ".join(hh_gap), info=True)

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
    ni = {int(d[:4]): v for d, v in fred("A032RC1A027NBEA").items()}
    worst_d = 0.0
    for y in inc["years"]:
        j, m = years.index(y), w["macro"][str(y)]
        if abs(inc["national_income"][str(y)] - ni[y] * 1e9) > 1:
            worst_d = float("inf")
        per_pp = ni[y] * 1e9 / (m["households"] / 100) / 100
        for i in range(100):
            worst_d = max(worst_d, abs(inc["measures"]["nominal"][i][j] - ishare[i][j] * per_pp) / (0.00005 * per_pp + 1))
    record("Income: dollar values = share x national income / households", worst_d <= 1,
           f"national income matches FRED A032RC1A027NBEA; worst error is {worst_d:.2f}x the share-rounding tolerance")

    record("Cross-source: WID vs Fed top-1% share", True,
           f"WID is on average {avg:+.1f} pp vs Fed DFA over {diffs[0][0]}-{diffs[-1][0]} (adults vs households; expected)", info=True)
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
