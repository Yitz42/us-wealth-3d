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
  - households by age of the reference person (AGE), in the Fed DFA's four age groups,
  - dollars held in each kind of asset, debt, net worth and income.
The same sums are also kept for each age group on its own (by_age), so the page can show any
breakdown for one age group, or several adjacent ones. Households are still ranked against all ages.

age_cells holds, per survey and bin, every age present (whole years, 18-95) with its share of the
bin's net worth (wealth ranking) or income (income ranking), in units of 1/100,000. Bins where some
ages' sums have a different sign from the bin's total also carry each age's share of the bin's
households, in the same units.
The page's age slider adds these up over the chosen age range and multiplies the 3-D chart's values
by the result (see age_part). In bins near zero, where some ages have positive net worth and others
negative, the range's share of the total can fall outside 0..1; those bins use the range's share of
the bin's households instead.
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
RANKED_SUM = {"wealth": "networth", "income": "income"}  # what an age group's part of a bin is measured in
AGES = [("age_u40", "Under 40"), ("age_40_54", "40–54"), ("age_55_69", "55–69"), ("age_70p", "70 and over")]  # DFA's groups
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


def age_group(row):
    age = int(row["AGE"])
    return "age_u40" if age < 40 else "age_40_54" if age < 55 else "age_55_69" if age < 70 else "age_70p"


def build_survey(year, rank_by):
    rows = []
    with open(SCF / f"SCFP{year}.csv", newline="") as f:
        for r in csv.DictReader(f):
            rows.append((float(r[rank_by]), float(r["WGT"]), r))
    rows.sort(key=lambda t: t[0])
    total_w = sum(w for _, w, _ in rows)

    def blank():
        return {"n": 0, "w": 0.0, "networth": 0.0, "income": 0.0, "debt": 0.0, "assets": 0.0,
                **{k: 0.0 for k, _ in GENDER + RACE + OCCUPATION + WORK + AGES}, **{k: 0.0 for k, _, _ in HOLDINGS}}

    bins = [blank() for _ in range(100)]
    by_age = {a: [blank() for _ in range(100)] for a, _ in AGES}
    cells = [{} for _ in range(100)]  # per bin: age -> [households, net worth, income]
    cum = 0.0
    for nw, w, r in rows:
        mid = (cum + w / 2) / total_w  # rank by the middle of this row's weight
        cum += w
        b_i = min(99, int(mid * 100))
        a = age_group(r)
        add(bins[b_i], w, r, a)
        add(by_age[a][b_i], w, r, a)
        c = cells[b_i].setdefault(int(r["AGE"]), [0.0, 0.0, 0.0])
        c[0] += w
        c[1] += w * float(r["NETWORTH"])
        c[2] += w * float(r["INCOME"])
    return bins, by_age, cells, total_w, len(rows)


def add(b, w, r, a):
    """Add one row (weight w, age group a) to bin b."""
    b["n"] += 1
    b["w"] += w
    b["networth"] += w * float(r["NETWORTH"])
    b["income"] += w * float(r["INCOME"])
    b[a] += w
    b["debt"] += w * float(r["DEBT"])
    b["assets"] += w * float(r["ASSET"])
    b[household_type(r)] += w
    b[RACE_CODE[r["RACECL4"]]] += w
    b[OCC_CODE[r["OCCAT2"]]] += w
    b[WORK_CODE[r["OCCAT1"]]] += w
    for key, _, cols in HOLDINGS:
        b[key] += w * sum(float(r[c]) for c in cols)


SCALE = 100_000  # age_cells shares are stored as whole numbers of 1/100,000


def age_part(cell, lo, hi):
    """Part of one bin held by ages lo..hi, from its age_cells entry [ages, sum shares(, household shares)].
    The page does the same (agePart in index.html); verify.py uses this function too."""
    ages, f = cell[0], cell[1]
    fr = sum(v for a, v in zip(ages, f) if lo <= a <= hi) / SCALE
    if len(cell) == 2 or -1e-3 <= fr <= 1 + 1e-3:  # the range and the rest share the bin's sign (rounding aside)
        return min(1.0, max(0.0, fr))
    return sum(v for a, v in zip(ages, cell[2]) if lo <= a <= hi) / SCALE


def main():
    out = {
        "surveys": SURVEYS,
        "categories": {
            "gender": [list(c) for c in GENDER],
            "race": [list(c) for c in RACE],
            "holdings": [[k, label] for k, label, _ in HOLDINGS],
            "occupation": [list(c) for c in OCCUPATION],
            "work": [list(c) for c in WORK],
            "age": [list(c) for c in AGES],
        },
        "implicates": 5,
        # rankings[wealth|income][f][survey index][bin] = weighted sum; "n" is rows (5 per household)
        # rankings[wealth|income]["by_age"][age][f][survey index][bin]: the same sums for one age group
        "rankings": {},
        "households": {},
        # age_cells[wealth|income][survey index][bin] = [ages, share of the bin's sum, share of its households]
        "age_cells": {},
    }
    keys = ["n", "w", "networth", "income", "debt", "assets"] + [k for k, _ in GENDER + RACE + OCCUPATION + WORK + AGES] + [k for k, _, _ in HOLDINGS]
    assert len(keys) == len(set(keys)), "category keys must be unique across groups"
    age_keys = [a for a, _ in AGES]
    for name, var in RANKINGS.items():
        fields = out["rankings"][name] = {k: [] for k in keys}
        age_fields = fields["by_age"] = {a: {k: [] for k in keys if k not in age_keys} for a in age_keys}
        age_cells = out["age_cells"][name] = []
        for year in SURVEYS:
            bins, by_age, cells, total_w, n_rows = build_survey(year, var)
            out["households"][str(year)] = round(total_w)
            for k in keys:
                fields[k].append([round(b[k]) if k != "n" else b[k] for b in bins])
            for a in age_keys:
                for k in age_fields[a]:
                    age_fields[a][k].append([round(b[k]) if k != "n" else b[k] for b in by_age[a]])
            col = 1 if name == "wealth" else 2
            survey_cells = []
            n_mixed = 0
            for b, cell in zip(bins, cells):
                ages = sorted(cell)
                total = b[RANKED_SUM[name]]
                entry = [ages, [round(cell[a][col] / total * SCALE) if total else 0 for a in ages]]
                if not total or any(cell[a][col] and (cell[a][col] > 0) != (total > 0) for a in ages):
                    entry.append([round(cell[a][0] / b["w"] * SCALE) for a in ages])
                    n_mixed += 1
                survey_cells.append(entry)
            age_cells.append(survey_cells)
            top = bins[99]
            print(f"{name} {year}: {n_rows // 5:,} households surveyed, {total_w / 1e6:.1f}M weighted; "
                  f"top 1%: {top['white'] / top['w']:.0%} White, {top['couple'] / top['w']:.0%} couples, "
                  f"{top['occ_prof'] / top['w']:.0%} managers/professionals, {top['work_self'] / top['w']:.0%} self-employed, "
                  f"{top['age_u40'] / top['w']:.0%} under 40; {n_mixed} bins with mixed-sign ages")
    js = json.dumps(out, separators=(",", ":"))
    (ROOT / "data" / "scf.json").write_text(js)
    (ROOT / "data" / "scf.js").write_text("window.SCF = " + js + ";\n")


if __name__ == "__main__":
    main()
