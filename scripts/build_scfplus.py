"""Summarize SCF+ (Kuhn, Schularick and Steins 2020) into household wealth shares by group, 1949-2016.

SCF+ joins the historical Surveys of Consumer Finances (1949-1977) to the modern SCF (1983 on), with
net wealth (ffanw) adjusted by the authors to match the Financial Accounts, in 2016 dollars. Each
surveyed household appears five times (imputation); the post-stratified weights (wgtI95W95, in
thousands) sum to all US households across the five copies, so every row is used with its weight.

Needs pandas (to read the Stata file). Input: data/raw/scfplus/SCF_plus.dta, from the journal's data
archive (https://www.journals.uchicago.edu/doi/suppl/10.1086/708815, "Data Archive", saved by hand).
Output: data/raw/scfplus/scfplus_groups.json, which build_data.py reads.
"""
import json, pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "raw" / "scfplus"
GROUPS = {"bottom50": (0.0, 0.5), "middle40": (0.5, 0.9), "next9": (0.9, 0.99), "top1": (0.99, 1.0)}


def main():
    df = pd.read_stata(DIR / "SCF_plus.dta", columns=["year", "ffanw", "wgtI95W95", "CPI"], convert_categoricals=False)
    out = {"source": "SCF+ (Kuhn, Schularick and Steins 2020), data version September 2019", "dollars_of": 2016,
           "years": [], "households": [], "surveyed": [], "cpi": [], "share": {g: [] for g in GROUPS}, "mean": {g: [] for g in GROUPS},
           "mean_all": [], "median": []}
    missing = df["ffanw"].isna() | df["wgtI95W95"].isna()
    out["rows_dropped"] = {str(int(y)): int(n) for y, n in df[missing].groupby("year").size().items()}
    df = df[~missing]
    for year, d in df.groupby("year"):
        d = d.sort_values("ffanw")
        w = d["wgtI95W95"].to_numpy()
        nw = d["ffanw"].to_numpy()
        total_w, total_nw = w.sum(), (w * nw).sum()
        # Each row's rank is the middle of its weight; a group takes the rows whose rank falls inside it.
        rank = (w.cumsum() - w / 2) / total_w
        out["years"].append(int(year))
        out["households"].append(round(total_w * 1000))
        out["surveyed"].append(len(d) // 5)
        out["cpi"].append(round(float(d["CPI"].mean()), 6))
        for g, (lo, hi) in GROUPS.items():
            m = (rank >= lo) & (rank < hi)
            out["share"][g].append(round(float((w[m] * nw[m]).sum() / total_nw * 100), 3))
            out["mean"][g].append(round(float((w[m] * nw[m]).sum() / w[m].sum())))
        out["mean_all"].append(round(float(total_nw / total_w)))
        out["median"].append(round(float(nw[rank.searchsorted(0.5)])))
    (DIR / "scfplus_groups.json").write_text(json.dumps(out, indent=1))
    print("rows without net wealth or weight, left out:", out["rows_dropped"] or "none")
    for i, y in enumerate(out["years"]):
        print(y, {g: out["share"][g][i] for g in GROUPS}, f"median ${out['median'][i]:,}", f"{out['surveyed'][i]:,} households surveyed")


if __name__ == "__main__":
    main()
