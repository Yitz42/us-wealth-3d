# US wealth distribution, 1950–now (3-D)

`index.html` has three tabs. **3-D map** (the default) shows US net worth (1950–2026) or pre-tax income
(1950–2024, WID `sptincj992`) for each 1-percentile group, as 3-D pillars or a surface
(year × percentile × value), with five views: share of wealth, nominal dollars per
household, real dollars (CPI-U), real dollars (PCE price index), and years of consumer spending.
Two-handle sliders for "Years shown" and "Percentiles shown" trim the 3-D chart. The cross-section panel sits beside the 3-D chart on wide screens
(below it, with a jump link, on narrow ones); clicking any pillar slices there. It cuts the chart by year (all percentiles in one year) or by percentile (one group across
all years), shows that slice as a flat bar chart with a summary table, and can hide everything past it.
Under the slicer, "Show" switches the flat chart between Wealth and three breakdowns from the Fed's
Survey of Consumer Finances (1989–2022, every three years): Gender (women and men as a share of adults,
with married or partnered people in lighter shades; each couple counts as one woman and one man, since the
survey records only one partner's sex),
Race, Location of money (what assets are held in), Work sector (occupation or work status), and Age of the
household head. With the Income measure selected, these rank households by income instead of net worth.
"Age of household head" is a two-handle slider (any range of ages, 17–95). It trims the 3-D chart, the slice and its table to the part of
each 1% group held by households whose head is in that age range, 1989 onward. The Show breakdowns follow the
range when it starts and ends on the DFA groups' edges (40, 55, 70) and cover all ages otherwise. Percentiles
still rank all ages. Clicking a bar opens a panel for that year and
percentile, with options to average over neighbouring years and percentiles. Sources, the method notes and
"Where sources disagree" are on this tab too.

Measure, View, Height scale and the age slider sit above both chart tabs and apply to both; Chart type and
the year/percentile sliders apply to the 3-D map only.

**Trends** (`#trends`) is a line chart of each group over time (bottom 50%, middle 40%, next 9%, top 1%), in
any view. Estimated years (WID's 1950–61 and preliminary years, and 2025–26 carried forward with Fed data) are
shaded and drawn in a greyed version of each line's colour; with an age range set, the years between surveys are
greyed too, with dots at the survey years. Dashed lines add WID's top 0.1% and top 0.01% (part of the top 1%;
through 2024): on the Share view and the Log scale they're drawn, and on linear dollar views, where they would
dwarf the chart, their values go in the summary instead. A **Source** switch picks WID, the Fed's
Distributional Financial Accounts (households, year-end, 1989 on; wealth only; it publishes a top 0.1% but no top
0.01%), WID + Fed (WID solid, the Fed dotted, in every view), or WID + SZZ (Smith, Zidar and Zwick's top wealth
shares dotted over WID's, 1966–2016; Share view only, since they publish shares; the next 9% is their top 10%
minus their top 1%, and the summary compares their bottom 90% with WID's). The Fed's shares are computed from its dollar
levels; `verify.py` checks them against its published shares. Clicking a year shows it in the cross-section below (the page stays on Trends). That cross-section gives the same
breakdowns as the 3-D map's (Gender, Race, Location of money, Work sector, Age, or the groups' own values) for
the four groups instead of single percentiles, by year or for one group over time, with a table; its values
follow the Source switch (in WID + Fed, the Fed's bars are striped beside WID's). Below it, a chart of **a household's
net worth** puts the Census Bureau's SIPP (median, and mean for households below the 99th percentile, yearly 2014–2024)
beside the SCF's median and means (computed from the survey files; the 2022 figures are checked against the Fed's
published ones) and the Fed's national-accounts average (household net worth ÷ households), with a table for 2022.
With the Income measure that chart is replaced by the Congressional Budget Office's **before and after taxes and
transfers**: four groups (lowest fifth, middle three fifths, 81st–99th, top 1%), solid before and dotted after means-tested
transfers and federal taxes, 1979–2023, as shares or average dollars per household, with a table for the year picked on the
chart above (income, transfers, taxes, tax rate and shares for CBO's nine groups).
**Checks** (`#checks`) holds the verification results.

`favicon.svg` is the tab icon: the bottom 50%, middle 40% and next 9% stay low while the top 1% towers over them.

## Run

```bash
python3 -m http.server 8765
```

Then open http://localhost:8765. Opening `index.html` directly also works; it only needs internet access for Plotly and the font.

## Rebuild the data

```bash
python3 scripts/fetch_data.py    # WID US file, Fed DFA, FRED series, SCF, Smith-Zidar-Zwick, Census SIPP + their documentation -> data/raw/
# CBO blocks scripted downloads: save 62761-supp-data.xlsx and the "additional data for researchers" CSVs
# from https://www.cbo.gov/publication/62761 into data/raw/cbo/ by hand, before build_data.py.
python3 scripts/build_data.py    # -> data/wealth.json, data/wealth.js (and data/gender_wid.json, not shown on the page)
python3 scripts/build_scf.py     # -> data/scf.json, data/scf.js
python3 scripts/verify.py        # -> data/verification.json, data/verification.js
```

Python 3.9+ standard library only. `fetch_data.py` pulls just the US files out of WID's 880 MB bulk zip using HTTP range requests.

## Sources

| Input | Source | Years |
|---|---|---|
| Wealth share per 1% bin | WID.world `shwealj992` (Saez–Zucman DINA) | 1950–2024 |
| Group shares used to extend and cross-check | Fed Distributional Financial Accounts | 1989–2026 Q2 |
| Total household net worth | Fed Z.1 via FRED `BOGZ1FL192090005Q` (households only); before 1987, `TNWBSHNO` (households and nonprofits) scaled to households | 1987– / 1945– |
| Income share per 1% bin | WID.world `sptincj992` (pre-tax national income) | 1950–2024 |
| Average wealth and income per adult, adult count, price index | WID.world `ahwealj992`, `aptincj992`, `npopuli992`, `inyixxi999` | 1950–2024 |
| Households | Census via FRED `TTLHH` | 1940– |
| CPI-U | BLS via FRED `CPIAUCNS` | 1913– |
| PCE price index | BEA via FRED `DPCERG3A086NBEA`, `PCEPI` | 1929– |
| Consumer spending | BEA via FRED `PCECA`, `PCE` | 1929– |
| Gender, race, holdings by percentile | Fed Survey of Consumer Finances, summary extract | 1989–2022, triennial |
| Top wealth shares (comparison) | Smith, Zidar & Zwick (2023), [supplemental data](https://www.ericzwick.com/wealth/Supplemental_data.zip), `TotalWealthShare.xlsx` Baseline | 1966–2016 |
| Household income before and after transfers and taxes | CBO, [The Distribution of Household Income, 2023](https://www.cbo.gov/publication/62761): supplemental data and additional data for researchers (households ranked by income before transfers and taxes) | 1979–2023 |
| Median and mean household net worth (comparison) | Census SIPP, [detailed wealth tables](https://www.census.gov/topics/income-poverty/wealth/data/tables.html) 1 and 5 (mean excludes the top 1%) | 2014–2024 |

## Verification and Jev

`verify.py` has two parts:

1. **Code checks.** Every number is re-derived from the raw files: all 7,500 WID cells, bin sums against WID's own aggregates, the Fed DFA extension, FRED inputs, and the dollar formula for every cell.
2. **Meaning checks by Jev (TypeSafe).** For each series, Jev reads the source's own documentation and says whether it *supports*, *contradicts* or *does not address* the claim the page makes: definition, population and units. Two control claims are deliberately wrong (households instead of adults; billions instead of millions), so a passing run shows the checker catches that kind of mistake. Arithmetic stays in code, as TypeSafe's docs recommend.

The Jev checks need an API key:

```bash
export TYPESAFE_API_KEY=...
python3 scripts/verify.py
```

Responses are cached in `data/jev_cache.json`. The page shows the results on its Checks tab.

## Where sources disagree

The page has a section comparing WID's shares with the Fed's Distributional Financial Accounts, the
Survey of Consumer Finances and published research: WID's top 1% wealth share is about 5 points above
the Fed's, WID puts the bottom half's wealth below zero in 2007–2017 while the Fed and the survey don't,
and the top 1% income share is disputed (Auten and Splinter 2024; replies by Piketty, Saez and Zucman
and by Iselin and Reck). It also compares the Census SIPP with the SCF: in 2022 the SIPP's median is 8% lower and
its bottom-99% mean 22% lower. The year table flags groups 2 or more points from the Fed's or the survey's
figures. `verify.py` has Jev check each summary of a paper against a passage from the paper, kept in
`scripts/fetch_data.py`.

## Caveats

- WID ranks **adults** aged 20+, with each couple's wealth split equally, not households. Its shares are applied to household totals, because it is the only 1-percentile source back to 1950. The Fed's household-based data puts the top 1% about 5 points lower.
- 1950–1961 are WID estimates built from income-tax trends. 2023–2024 are WID preliminary estimates (nowcasts). 2025–2026 are extended here from Fed DFA group changes. 2026 is a partial year.
- 2025 CPI-U averages 11 months, because BLS published no October 2025 CPI.
- The age split comes from the SCF: each single year of age's share of every 1% group's net worth (or income),
  interpolated between surveys, held at 2022 after that, and unavailable before 1989. It is applied to
  WID's adult-based bins, so an age group's total can differ from the Fed DFA's figure by a few points
  (see the Checks tab). Bins where age groups' net worth has mixed signs are split by
  household share instead. Single pillars are noisy: each age group has only a few surveyed households per bin.
- WID rounds each share to 0.01% of total wealth, so 350 of the 7,700 cells come out as exactly 0.00%. Those are estimated by interpolating between the nearest published neighbours (or, at the very bottom, extending the next 20 bins' trend). They're capped at ±0.0045% so they still round to WID's 0, and are drawn **grey** on the page. The same applies to income (45 cells), except that income estimates are kept at or above zero, because WID never publishes a negative income share. `verify.py` checks that every estimate replaces a published 0 and still rounds back to it.
