"""Build data/scf.js: who is in each 1% wealth percentile, and what they hold.

Source: the Federal Reserve's Survey of Consumer Finances (SCF) summary extract, one
file per survey (1989-2022, every three years). Each surveyed household appears five
times (multiple imputation); the weights WGT already sum to all US households across
the five copies, so every row is used with its weight.

For each survey, households are ranked twice, by NETWORTH and by INCOME (for the page's
Wealth and Income views), and each ranking is split into 100 bins of equal weighted size. Per bin we keep raw weighted sums (not shares), so the page can average
any window of percentiles or years by adding sums before dividing:
  - households by household type (couple / single woman / single man),
  - households by race (RACECL4),
  - households by occupation (OCCAT2) and by work status (OCCAT1) of the reference person,
  - dollars held in each kind of asset, and debt.
SCF dollars are in the latest survey's dollars; only ratios within a bin are used.
"""
import csv, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCF = ROOT / "data" / "raw" / "scf"
SURVEYS = [1989, 1992, 1995, 1998, 2001, 2004, 2007, 2010, 2013, 2016, 2019, 2022]

GENDER = [("couple", "Couples"), ("single_woman", "Single women"), ("single_man", "Single men")]
RACE = [("white", "White"), ("black", "Black"), ("hispanic", "Hispanic"), ("other", "Other or multiple races")]
OCCUPATION = [("occ_prof", "Managerial or professional"), ("occ_tech", "Technical, sales, services"),
              ("occ_other", "Production, labor, farming"), ("occ_none", "Not working")]
WORK = [("work_employee", "Works for someone else"), ("work_self", "Self-employed or partner"),
        ("work_retired", "Retired, disabled, or not working 65+"), ("work_other", "Not working, mostly under 65")]
OCC_CODE = {"1": "occ_prof", "2": "occ_tech", "3": "occ_other", "4": "occ_none"}
WORK_CODE = {"1": "work_employee", "2": "work_self", "3": "work_retired", "4": "work_other"}
RANKINGS = {"wealth": "NETWORTH", "income": "INCOME"}
HOLDINGS = [  # label, SCF summary variables summed
    ("home", "Own home", ["HOUSES"]),
    ("real_estate", "Other real estate", ["ORESRE", "NNRESRE"]),
    ("business", "Private business", ["BUS"]),
    ("stocks", "Stocks and funds", ["STOCKS", "NMMF"]),
    ("retirement", "Retirement accounts", ["RETQLIQ"]),
    ("cash", "Cash, deposits, bonds", ["LIQ", "CDS", "BOND", "SAVBND"]),
    ("other_assets", "Vehicles and other", ["VEHIC", "CASHLI", "OTHMA", "OTHFIN", "OTHNFIN"]),
]


def household_type(row):
    if row["MARRIED"] == "1":  # married or living with a partner
        return "couple"
    return "single_woman" if row["HHSEX"] == "2" else "single_man"


RACE_CODE = {"1": "white", "2": "black", "3": "hispanic", "4": "other"}


def build_survey(year, rank_by):
    rows = []
    with open(SCF / f"SCFP{year}.csv", newline="") as f:
        for r in csv.DictReader(f):
            rows.append((float(r[rank_by]), float(r["WGT"]), r))
    rows.sort(key=lambda t: t[0])
    total_w = sum(w for _, w, _ in rows)

    def blank():
        return {"n": 0, "w": 0.0, "networth": 0.0, "debt": 0.0, "assets": 0.0,
                **{k: 0.0 for k, _ in GENDER + RACE + OCCUPATION + WORK}, **{k: 0.0 for k, _, _ in HOLDINGS}}

    bins = [blank() for _ in range(100)]
    cum = 0.0
    for nw, w, r in rows:
        mid = (cum + w / 2) / total_w  # rank by the middle of this row's weight
        cum += w
        b = bins[min(99, int(mid * 100))]
        b["n"] += 1
        b["w"] += w
        b["networth"] += w * nw
        b["debt"] += w * float(r["DEBT"])
        b["assets"] += w * float(r["ASSET"])
        b[household_type(r)] += w
        b[RACE_CODE[r["RACECL4"]]] += w
        b[OCC_CODE[r["OCCAT2"]]] += w
        b[WORK_CODE[r["OCCAT1"]]] += w
        for key, _, cols in HOLDINGS:
            b[key] += w * sum(float(r[c]) for c in cols)
    return bins, total_w, len(rows)


def main():
    out = {
        "surveys": SURVEYS,
        "categories": {
            "gender": [list(c) for c in GENDER],
            "race": [list(c) for c in RACE],
            "holdings": [[k, label] for k, label, _ in HOLDINGS],
            "occupation": [list(c) for c in OCCUPATION],
            "work": [list(c) for c in WORK],
        },
        "implicates": 5,
        # rankings[wealth|income][f][survey index][bin] = weighted sum; "n" is rows (5 per household)
        "rankings": {},
        "households": {},
    }
    keys = ["n", "w", "networth", "debt", "assets"] + [k for k, _ in GENDER + RACE + OCCUPATION + WORK] + [k for k, _, _ in HOLDINGS]
    assert len(keys) == len(set(keys)), "category keys must be unique across groups"
    for name, var in RANKINGS.items():
        fields = out["rankings"][name] = {k: [] for k in keys}
        for year in SURVEYS:
            bins, total_w, n_rows = build_survey(year, var)
            out["households"][str(year)] = round(total_w)
            for k in keys:
                fields[k].append([round(b[k]) if k != "n" else b[k] for b in bins])
            top = bins[99]
            print(f"{name} {year}: {n_rows // 5:,} households surveyed, {total_w / 1e6:.1f}M weighted; "
                  f"top 1%: {top['white'] / top['w']:.0%} White, {top['couple'] / top['w']:.0%} couples, "
                  f"{top['occ_prof'] / top['w']:.0%} managers/professionals, {top['work_self'] / top['w']:.0%} self-employed")
    js = json.dumps(out, separators=(",", ":"))
    (ROOT / "data" / "scf.json").write_text(js)
    (ROOT / "data" / "scf.js").write_text("window.SCF = " + js + ";\n")


if __name__ == "__main__":
    main()
