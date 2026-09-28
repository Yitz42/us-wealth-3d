"""Build data/wealth.json: US net-worth distribution by 1-percentile bin, 1950-now.

Share of wealth per bin comes from WID.world (shwealj992, p0p1 .. p99p100).
Years after WID's last year are extended with the Fed's Distributional
Financial Accounts (DFA): each WID bin is scaled by how much its DFA group's
share changed since WID's last year, then shares are renormalized to 100%.

Dollar views convert shares with Fed Z.1 household net worth (FRED TNWBSHNO)
and Census household counts (FRED TTLHH), then deflate with CPI-U or the PCE
price index, or divide by consumer spending per household (PCE).
"""
import calendar, csv, json, pathlib, statistics
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
START_YEAR = 1950
BASE_YEAR = 2025  # real-dollar views are in BASE_YEAR dollars
BINS = [f"p{i}p{i + 1}" for i in range(100)]

# DFA groups, expressed as percentile ranges of the 0-100 axis.
DFA_GROUPS = {
    "Bottom50": (0, 50),
    "Next40": (50, 90),
    "Next9": (90, 99),
    "RemainingTop1": (99, 100),  # combined with TopPt1 below
}


def fred(series_id):
    """{date string: float} from a FRED CSV, skipping missing '.' values."""
    out = {}
    with open(RAW / f"{series_id}.csv") as f:
        for row in csv.DictReader(f):
            val = row[series_id]
            if val not in ("", "."):
                out[row["observation_date"]] = float(val)
    return out


def annual_mean(monthly):
    """{year: (mean, months_used)} from a monthly FRED series."""
    by_year = defaultdict(list)
    for date, v in monthly.items():
        by_year[int(date[:4])].append(v)
    return {y: (statistics.mean(vs), len(vs)) for y, vs in by_year.items()}


def annual(series):
    return {int(d[:4]): v for d, v in series.items()}


def load_wid(variable="shwealj992"):
    """{year: {bin: share}} and {year: data_quality} for a WID share series
    (shwealj992 = net personal wealth, sptincj992 = pre-tax national income)."""
    shares, quality = defaultdict(dict), {}
    wanted = set(BINS)
    with open(RAW / "WID_data_US.csv") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["variable"] != variable or row["percentile"] not in wanted:
                continue
            year = int(row["year"])
            if year < START_YEAR:
                continue
            shares[year][row["percentile"]] = float(row["value"])
            if row["data_quality"]:
                quality[year] = row["data_quality"]
    return dict(shares), quality


def load_dfa():
    """{(year, quarter): {group: net-worth share %}} with TopPt1 folded into RemainingTop1."""
    out = defaultdict(dict)
    with open(RAW / "dfa" / "dfa-networth-shares.csv") as f:
        for row in csv.DictReader(f):
            y, q = row["Date"].split(":Q")
            key = (int(y), int(q))
            group = "RemainingTop1" if row["Category"] == "TopPt1" else row["Category"]
            out[key][group] = out[key].get(group, 0.0) + float(row["Net worth"])
    return dict(out)


# --- Women and men ------------------------------------------------------------------
# WID's sex-specific series (shwealf992 / shwealm992) rank women among women and men among
# men, 1962-2019, but only for broad groups. The 1% axis needs four of them.
GENDER_GROUPS = [("bottom50", 0, 50), ("next40", 50, 90), ("next9", 90, 99), ("top1", 99, 100)]
SEXES = {"female": "f", "male": "m"}


def load_gender():
    """{sex: {year: {percentile: share}}}, average wealth {sex: {year}} and adults {sex: {year}}."""
    shares = {s: defaultdict(dict) for s in SEXES}
    avg = {s: {} for s in SEXES}
    pop = {s: {} for s in SEXES}
    codes = {code: sex for sex, code in SEXES.items()}
    with open(RAW / "WID_data_US.csv") as f:
        for row in csv.DictReader(f, delimiter=";"):
            v, pc, y = row["variable"], row["percentile"], int(row["year"])
            if len(v) != 10 or v[-3:] != "992" or v[-4] not in codes:  # e.g. shwealf992
                continue
            sex = codes[v[-4]]
            if v.startswith("shweal"):
                shares[sex][y][pc] = float(row["value"])
            elif v.startswith("ahweal") and pc == "p0p100":
                avg[sex][y] = float(row["value"])
            elif v.startswith("npopul") and pc == "p0p100":
                pop[sex][y] = float(row["value"])
    return shares, avg, pop


def gender_groups(g):
    """The four groups the 1% axis needs. WID's published p50p90 for women doesn't agree with
    its own p0p90 (the three groups sum to 104-114%), so the middle group is p0p90 - p0p50,
    which does add up to exactly 100% with p90p100."""
    return {"bottom50": g["p0p50"], "next40": g["p0p90"] - g["p0p50"],
            "next9": g["p90p100"] - g["p99p100"], "top1": g["p99p100"]}


def spread_groups(all_bins, targets):
    """Estimate 1% bins for one sex: reshape each group to its WID total using the all-adults
    bins of the same year as the pattern. Scales the pattern when both totals are clearly
    positive; otherwise shifts every bin by the same amount so signs can't flip."""
    out = list(all_bins)
    for name, lo, hi in GENDER_GROUPS:
        base, t = all_bins[lo:hi], targets[name]
        bsum, n = sum(base), hi - lo
        if n == 1:
            out[lo] = t
        elif bsum > 0 and t > 0 and 0.25 <= t / bsum <= 4:
            out[lo:hi] = [v * t / bsum for v in base]
        else:
            out[lo:hi] = [v + (t - bsum) / n for v in base]
    return out


# WID publishes shares as fractions rounded to 4 decimals (0.01 percentage point), so a
# bin near zero wealth often reads exactly 0: its sign and size are lost. We estimate those.
ROUNDING_HALF = 0.000045  # inside ±0.00005 (with room for our own 4-decimal % rounding) so estimates round to WID's 0


def fill_rounded_zeros(values):
    """Estimate bins WID rounded to exactly 0. Returns (filled list, set of estimated indices).

    Bin shares rise with wealth rank, so a run of zeros is interpolated between the
    nearest published neighbours; a run at the very bottom is extrapolated from the
    slope of the next twenty bins. Estimates are clamped to the rounding interval.
    """
    v, guessed, i = list(values), set(), 0
    while i < len(v):
        if v[i] != 0:
            i += 1
            continue
        a = i
        while i < len(v) and v[i] == 0:
            i += 1
        b = i - 1  # zero run is a..b
        right = b + 1
        if a > 0:
            left = a - 1
            est = {k: v[left] + (v[right] - v[left]) * (k - left) / (right - left) for k in range(a, b + 1)}
        else:
            slope = (v[right + 20] - v[right]) / 20
            est = {k: v[right] - slope * (right - k) for k in range(a, b + 1)}
        for k, e in est.items():
            v[k] = max(-ROUNDING_HALF, min(ROUNDING_HALF, e))
            guessed.add(k)
    return v, guessed


def year_end(dfa_or_z1, year):
    """Latest quarter available within `year` (Q4 when the year is complete)."""
    quarters = sorted(k for k in dfa_or_z1 if k[0] == year)
    return quarters[-1] if quarters else None


def main():
    wid, wid_quality = load_wid()
    wid_last = max(y for y, s in wid.items() if len(s) == 100)
    dfa = load_dfa()
    dfa_last_year = max(y for y, _ in dfa)

    tier = {}
    for y in wid:
        tier[y] = {"4": "measured", "3": "wid_imputed", "0": "wid_nowcast"}.get(wid_quality[y], "wid_other")

    # --- Estimate bins WID rounded to 0 (shown grey on the page) --------------------
    guessed = {}
    for y in list(wid):
        filled, g = fill_rounded_zeros([wid[y][b] for b in BINS])
        wid[y] = dict(zip(BINS, filled))
        guessed[y] = g

    # --- Extend shares past WID with DFA group growth -----------------------------
    base_q = year_end(dfa, wid_last)
    dfa_quarter_used = {}
    for y in range(wid_last + 1, dfa_last_year + 1):
        q = year_end(dfa, y)
        dfa_quarter_used[y] = f"{q[0]}:Q{q[1]}"
        scaled = {}
        for group, (lo, hi) in DFA_GROUPS.items():
            ratio = dfa[q][group] / dfa[base_q][group]
            for i in range(lo, hi):
                scaled[BINS[i]] = wid[wid_last][BINS[i]] * ratio
        total = sum(scaled.values())
        wid[y] = {b: v / total for b, v in scaled.items()}
        tier[y] = "extended_dfa"
        guessed[y] = set(guessed[wid_last])  # scaled from an estimate is still an estimate

    years = sorted(y for y in wid if y >= START_YEAR)

    # --- Macro series ---------------------------------------------------------------
    z1 = {(int(d[:4]), (int(d[5:7]) - 1) // 3 + 1): v for d, v in fred("TNWBSHNO").items()}  # $ millions
    households = annual(fred("TTLHH"))  # thousands
    cpi_monthly = fred("CPIAUCNS")
    cpi = annual_mean(cpi_monthly)
    pce_price_a = annual(fred("DPCERG3A086NBEA"))  # 2017=100, annual
    pce_price_m = annual_mean(fred("PCEPI"))  # monthly, for the current partial year
    pce_a = annual(fred("PCECA"))  # $ billions, annual
    pce_m = annual_mean(fred("PCE"))  # $ billions SAAR, monthly

    notes = defaultdict(list)
    macro = {}
    for y in years:
        zq = year_end(z1, y)
        nw = z1[zq] * 1e6
        if zq[1] != 4:
            notes[y].append(f"Household net worth is the {zq[0]}:Q{zq[1]} level (latest available).")

        if y in households:
            hh = households[y] * 1e3
        else:
            last = max(households)
            growth = households[last] / households[last - 1]
            hh = households[last] * 1e3 * growth ** (y - last)
            notes[y].append(f"Household count projected from {last} at the {last - 1}-{last} growth rate.")

        cpi_v, cpi_n = cpi[y]
        if cpi_n < 12:
            missing = [m for m in range(1, 13) if f"{y}-{m:02d}-01" not in cpi_monthly]
            latest = max(d for d in cpi_monthly if d.startswith(str(y)))
            gaps = [calendar.month_name[m] for m in missing if f"{y}-{m:02d}-01" < latest]
            detail = f"no {', '.join(gaps)} release" if gaps else f"data through {calendar.month_name[int(latest[5:7])]}"
            notes[y].append(f"CPI-U is the average of the {cpi_n} months published ({detail}).")

        if y in pce_price_a:
            pce_p = pce_price_a[y]
        else:
            last = max(pce_price_a)
            pce_p = pce_price_a[last] * pce_price_m[y][0] / pce_price_m[last][0]
            notes[y].append(f"PCE price index extended with {pce_price_m[y][1]} months of monthly PCEPI.")

        if y in pce_a:
            pce = pce_a[y] * 1e9
        else:
            pce = pce_m[y][0] * 1e9
            notes[y].append(f"Consumer spending is the {pce_m[y][1]}-month average annual rate (PCE).")

        macro[y] = {
            "net_worth_total": nw,
            "net_worth_quarter": f"{zq[0]}:Q{zq[1]}",
            "households": hh,
            "cpi_u": cpi_v,
            "pce_price_index": pce_p,
            "pce_total": pce,
        }

    cpi_base = macro[BASE_YEAR]["cpi_u"]
    pce_p_base = macro[BASE_YEAR]["pce_price_index"]

    # --- Measures: rows = bins (p0p1..p99p100), cols = years ---------------------
    share, nominal, real_cpi, real_pce, spend_years = [], [], [], [], []
    for b in BINS:
        r_share, r_nom, r_cpi, r_pce, r_sp = [], [], [], [], []
        for y in years:
            m = macro[y]
            s = wid[y][b]
            per_hh = s * m["net_worth_total"] / (m["households"] / 100)
            spend_per_hh = m["pce_total"] / m["households"]
            r_share.append(round(s * 100, 4))
            r_nom.append(round(per_hh))
            r_cpi.append(round(per_hh * cpi_base / m["cpi_u"]))
            r_pce.append(round(per_hh * pce_p_base / m["pce_price_index"]))
            r_sp.append(round(per_hh / spend_per_hh, 3))
        share.append(r_share); nominal.append(r_nom); real_cpi.append(r_cpi)
        real_pce.append(r_pce); spend_years.append(r_sp)

    # --- Pre-tax income (WID sptincj992): same 1% bins, 1950 to WID's last year ---------
    # Dollar views use national income (BEA via FRED A032RC1A027NBEA), the total that
    # WID's pre-tax national income distributes.
    inc, inc_q = load_wid("sptincj992")
    national_income = {y: v * 1e9 for y, v in annual(fred("A032RC1A027NBEA")).items()}
    inc_years = sorted(y for y in years if y in inc and len(inc[y]) == 100 and y in national_income)
    inc_meas = {k: [[None] * len(years) for _ in BINS] for k in ("share", "nominal", "real_cpi", "real_pce", "spend_years")}
    inc_est = [[0] * len(years) for _ in BINS]
    inc_tier = {}
    for y in inc_years:
        j, m = years.index(y), macro[y]
        filled, g = fill_rounded_zeros([inc[y][b] for b in BINS])
        inc_tier[str(y)] = "measured" if inc_q.get(y) == "5" else "wid_imputed"
        for i, s_ in enumerate(filled):
            per_hh = s_ * national_income[y] / (m["households"] / 100)
            inc_meas["share"][i][j] = round(s_ * 100, 4)
            inc_meas["nominal"][i][j] = round(per_hh)
            inc_meas["real_cpi"][i][j] = round(per_hh * cpi_base / m["cpi_u"])
            inc_meas["real_pce"][i][j] = round(per_hh * pce_p_base / m["pce_price_index"])
            inc_meas["spend_years"][i][j] = round(per_hh / (m["pce_total"] / m["households"]), 3)
            inc_est[i][j] = int(i in g)
    income = {"years": inc_years, "tier": inc_tier, "estimated": inc_est, "measures": inc_meas,
              "national_income": {str(y): national_income[y] for y in inc_years}}

    # --- Women and men: estimated 1% bins, 1962-2019 -------------------------------------
    g_shares, g_avg, g_pop = load_gender()
    g_years = sorted(y for y in years if all(y in g_shares[sx] and "p0p90" in g_shares[sx][y] for sx in SEXES)
                     and all(y in g_avg[sx] and y in g_pop[sx] for sx in SEXES))
    gender = {"years": g_years, "groups": [list(g) for g in GENDER_GROUPS]}
    for sex in SEXES:
        other = "male" if sex == "female" else "female"
        meas = {k: [[None] * len(years) for _ in BINS] for k in ("share", "nominal", "real_cpi", "real_pce", "spend_years")}
        groups, gaps = {}, []
        for y in g_years:
            j, m = years.index(y), macro[y]
            tg = gender_groups(g_shares[sex][y])
            groups[str(y)] = tg
            gaps.append((g_shares[sex][y]["p50p90"] - tg["next40"]) * 100)
            bins = spread_groups([wid[y][b] for b in BINS], tg)
            # This sex's slice of total wealth, from WID's own averages x adult counts.
            mine, theirs = g_avg[sex][y] * g_pop[sex][y], g_avg[other][y] * g_pop[other][y]
            sex_total = m["net_worth_total"] * mine / (mine + theirs)
            adults = g_pop[sex][y]
            spend_per_adult = m["pce_total"] / (g_pop["female"][y] + g_pop["male"][y])
            for i, sb in enumerate(bins):
                per_adult = sb * sex_total / (adults / 100)
                meas["share"][i][j] = round(sb * 100, 4)
                meas["nominal"][i][j] = round(per_adult)
                meas["real_cpi"][i][j] = round(per_adult * cpi_base / m["cpi_u"])
                meas["real_pce"][i][j] = round(per_adult * pce_p_base / m["pce_price_index"])
                meas["spend_years"][i][j] = round(per_adult / spend_per_adult, 3)
        gender[sex] = {"measures": meas, "groups": groups,
                       "published_p50p90_gap_pp": [round(min(gaps), 2), round(max(gaps), 2)]}

    out = {
        "generated_from": "scripts/build_data.py",
        "years": years,
        "percentiles": list(range(1, 101)),  # bin i+1 = households from i% to i+1%
        "bins": BINS,
        "base_year": BASE_YEAR,
        "tier": {str(y): tier[y] for y in years},
        # estimated[bin][year] = 1 where WID published exactly 0 and the value is our estimate
        "estimated": [[int(i in guessed[y]) for y in years] for i in range(100)],
        "dfa_quarter_used": dfa_quarter_used,
        "year_notes": {str(y): notes[y] for y in years if notes[y]},
        "macro": {str(y): macro[y] for y in years},
        "measures": {
            "share": share,
            "nominal": nominal,
            "real_cpi": real_cpi,
            "real_pce": real_pce,
            "spend_years": spend_years,
        },
        "income": income,
    }
    # WID's women/men series are kept for reference but not shown on the page.
    (ROOT / "data" / "gender_wid.json").write_text(json.dumps(gender, separators=(",", ":")))
    (ROOT / "data" / "wealth.json").write_text(json.dumps(out, separators=(",", ":")))
    (ROOT / "data" / "wealth.js").write_text("window.WEALTH = " + json.dumps(out, separators=(",", ":")) + ";\n")

    print(f"years {years[0]}-{years[-1]} ({len(years)}), WID through {wid_last}, DFA through {dfa_last_year}")
    for y in (1950, 1962, 1989, wid_last, years[-1]):
        top1 = share[99][years.index(y)]
        bottom50 = sum(share[i][years.index(y)] for i in range(50))
        print(f"  {y} [{tier[y]}]: top 1% {top1:.1f}%, bottom 50% {bottom50:.1f}%, "
              f"top-1% avg ${nominal[99][years.index(y)]/1e6:,.1f}M nominal")
    for sex in SEXES:
        gs = gender[sex]
        j = years.index(g_years[-1])
        print(f"  {sex} {g_years[0]}-{g_years[-1]}: top 1% {gs['measures']['share'][99][j]:.1f}% in {g_years[-1]}; "
              f"WID's published p50p90 is off by {gs['published_p50p90_gap_pp'][0]:+.1f} to {gs['published_p50p90_gap_pp'][1]:+.1f} pp")
    jl = years.index(inc_years[-1])
    print(f"  income {inc_years[0]}-{inc_years[-1]}: top 1% {inc_meas['share'][99][jl]:.1f}%, "
          f"bottom 50% {sum(inc_meas['share'][i][jl] for i in range(50)):.1f}% in {inc_years[-1]}; "
          f"top-1% avg ${inc_meas['nominal'][99][jl] / 1e6:.2f}M per household; "
          f"{sum(map(sum, inc_est))} cells estimated")
    n_est = sum(len(guessed[y]) for y in years)
    print(f"  {n_est} of {100 * len(years)} cells estimated (WID published exactly 0)")
    for y, ns in notes.items():
        for n in ns:
            print(f"  note {y}: {n}")


if __name__ == "__main__":
    main()
