"""
ISS Week 4 — Climate Change and Disaster Resilience
Research-foundation analysis

What this script does:
1. Reads an EM-DAT spreadsheet that you download manually after registering.
2. Filters to selected weather/climate-related disaster types.
3. Cleans country/year/impact fields and creates a country-year summary.
4. Downloads World Bank population and GDP-per-capita indicators via its public API.
5. Exports cleaned data and creates two presentation-ready charts.

Before running:
- Download the EM-DAT Public Data spreadsheet from https://public.emdat.be/data
  (registration and acceptance of terms may be required).
- Put the file in the same folder as this script, or update EM_DAT_FILE below.
- Install packages: pip install pandas requests matplotlib openpyxl
- Run: python iss_week4_climate_disaster_analysis.py

Important:
- This is exploratory analysis, not proof that climate change caused each disaster.
- Check the EM-DAT spreadsheet's column names and disaster classifications.
- Blank impact values may mean unknown/unreported, not necessarily zero.
"""

from pathlib import Path
import re
import sys
import requests
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# ---------- SETTINGS YOU CAN CHANGE ----------
EM_DAT_FILE = "data/emdat_public.xlsx"  # Change this to your downloaded EM-DAT filename
SHEET_NAME = 0                     # Usually the first worksheet
START_YEAR = 2000
END_YEAR = 2024
OUTPUT_DIR = Path("iss_week4_outputs")

# Selected EM-DAT disaster types. Verify spelling against your downloaded file.
CLIMATE_DISASTER_TYPES = {
    "flood", "storm", "drought", "extreme temperature", "wildfire"
}

# World Bank indicators
POPULATION_INDICATOR = "SP.POP.TOTL"
GDP_PER_CAPITA_INDICATOR = "NY.GDP.PCAP.CD"


def normalize_column_name(name):
    """Normalize a column heading for matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(name).strip().lower()).strip()


def find_column(df, candidates, required=True):
    """Find a source column from a list of possible heading names."""
    normalized = {normalize_column_name(c): c for c in df.columns}
    for candidate in candidates:
        key = normalize_column_name(candidate)
        if key in normalized:
            return normalized[key]
    # Fallback: allow common headings to include extra words.
    for candidate in candidates:
        key = normalize_column_name(candidate)
        for normalized_name, original_name in normalized.items():
            if key and (normalized_name.startswith(key) or key in normalized_name):
                return original_name
    if required:
        raise ValueError(
            f"Could not find a column matching {candidates}.\n"
            f"Columns found: {list(df.columns)}\n"
            "Update the candidate names in find_column() calls to match your file."
        )
    return None


def to_numeric(series):
    """Convert values to numeric; unknown or blank values remain missing."""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).replace(
            {"": pd.NA, "nan": pd.NA, "None": pd.NA, "NA": pd.NA, "nan ": pd.NA}
        ),
        errors="coerce",
    )


def download_world_bank_indicator(indicator_code, start_year, end_year):
    """Download all country observations for one indicator from World Bank API v2."""
    url = (
        f"https://api.worldbank.org/v2/country/all/indicator/{indicator_code}"
        f"?format=json&per_page=20000&date={start_year}:{end_year}"
    )
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        raise RuntimeError(f"Unexpected World Bank API response for {indicator_code}")
    records = []
    for item in payload[1]:
        if not item:
            continue
        country = item.get("country", {}).get("value")
        iso3 = item.get("countryiso3code")
        year = item.get("date")
        value = item.get("value")
        if iso3 and country and year:
            records.append({
                "iso3": iso3,
                "country_wb": country,
                "year": int(year),
                indicator_code: value,
            })
    return pd.DataFrame(records)


def build_country_risk_summary(country_year_df, min_years=3, min_population=1_000_000):
    """Return a reporting-aware country ranking that reduces raw-count bias.

    We compare countries using average annual disaster events per 100k population and
    exclude tiny or lightly covered countries, because raw counts are dominated by
    reporting volume and population size rather than true risk exposure.
    """
    df = country_year_df.copy()
    if df.empty:
        return pd.DataFrame(columns=[
            "country",
            "total_events",
            "years_with_records",
            "avg_population",
            "avg_annual_events_per_100k",
            "median_annual_events_per_100k",
        ])

    df["population"] = pd.to_numeric(df.get("SP.POP.TOTL", pd.Series(index=df.index, dtype="float64")), errors="coerce")
    df["avg_annual_events_per_100k"] = (
        df["recorded_disaster_events"] / df["population"] * 100_000
    )

    summary = (
        df.groupby("country", dropna=False)
        .agg(
            total_events=("recorded_disaster_events", "sum"),
            years_with_records=("year", "nunique"),
            avg_population=("population", "mean"),
            avg_annual_events_per_100k=("avg_annual_events_per_100k", "mean"),
            median_annual_events_per_100k=("avg_annual_events_per_100k", "median"),
        )
        .reset_index()
    )

    summary = summary[
        (summary["years_with_records"] >= min_years)
        & (summary["avg_population"] >= min_population)
    ].copy()

    return summary.sort_values("avg_annual_events_per_100k", ascending=False).reset_index(drop=True)


def build_disaster_type_summary(event_df):
    """Summarize the hazard mix so the report highlights the dominant disaster types."""
    df = event_df.copy()
    if df.empty:
        return pd.DataFrame(columns=["disaster_type_clean", "recorded_events", "share_of_records"])
    type_col = "disaster_type_clean" if "disaster_type_clean" in df.columns else "disaster_type"
    summary = (
        df[type_col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.casefold()
        .value_counts()
        .rename_axis("disaster_type_clean")
        .reset_index(name="recorded_events")
    )
    summary["share_of_records"] = summary["recorded_events"] / summary["recorded_events"].sum()
    return summary.sort_values("recorded_events", ascending=False).reset_index(drop=True)


def build_gdp_vs_mortality_summary(country_year_df, min_years=4):
    """Build a country-level comparison for GDP per capita versus average disaster mortality."""
    df = country_year_df.copy()
    if df.empty:
        return pd.DataFrame(columns=["country", "avg_gdp_per_capita", "avg_deaths_per_100k", "years_with_data"])

    required = {"country", "year", "deaths_per_100k_population", "NY.GDP.PCAP.CD"}
    missing = required - set(df.columns)
    if missing:
        return pd.DataFrame(columns=["country", "avg_gdp_per_capita", "avg_deaths_per_100k", "years_with_data"])

    summary = (
        df.dropna(subset=["country", "deaths_per_100k_population", "NY.GDP.PCAP.CD"])
        .groupby("country", dropna=False)
        .agg(
            avg_gdp_per_capita=("NY.GDP.PCAP.CD", "mean"),
            avg_deaths_per_100k=("deaths_per_100k_population", "mean"),
            years_with_data=("year", "nunique"),
        )
        .reset_index()
    )
    return summary[summary["years_with_data"] >= min_years].sort_values("avg_deaths_per_100k", ascending=False).reset_index(drop=True)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_path = Path(EM_DAT_FILE)
    if not source_path.exists():
        print(f"\nEM-DAT file not found: {source_path.resolve()}")
        print("Download the EM-DAT Public Data spreadsheet and set EM_DAT_FILE at the top.")
        sys.exit(1)

    print("Reading EM-DAT spreadsheet...")
    raw = pd.read_excel(source_path, sheet_name=SHEET_NAME)
    raw.columns = [str(c).strip() for c in raw.columns]

    country_col = find_column(raw, ["Country"])
    type_col = find_column(raw, ["Disaster Type", "Disaster type"])
    year_col = find_column(raw, ["Start Year", "Year", "Start year"])
    iso_col = find_column(raw, ["ISO", "ISO3", "ISO code", "Country ISO"], required=False)

    # Impact fields can differ by EM-DAT version. Missing columns are left blank.
    deaths_col = find_column(raw, ["Total Deaths", "Total deaths", "Deaths"], required=False)
    affected_col = find_column(
        raw, ["Total Affected", "Total affected", "No Affected", "Affected"], required=False
    )
    injured_col = find_column(raw, ["No Injured", "Injured"], required=False)
    homeless_col = find_column(raw, ["No Homeless", "Homeless"], required=False)

    df = pd.DataFrame({
        "country": raw[country_col].astype("string").str.strip(),
        "disaster_type": raw[type_col].astype("string").str.strip(),
        "year": pd.to_numeric(raw[year_col], errors="coerce"),
        "iso3": raw[iso_col].astype("string").str.strip().str.upper() if iso_col else pd.NA,
    })
    df["deaths_reported"] = to_numeric(raw[deaths_col]) if deaths_col else pd.NA

    # EM-DAT may provide total affected or separate affected/injured/homeless fields.
    if affected_col:
        df["people_affected_reported"] = to_numeric(raw[affected_col])
    else:
        components = []
        for col in [injured_col, homeless_col]:
            if col:
                components.append(to_numeric(raw[col]))
        if components:
            df["people_affected_reported"] = pd.concat(components, axis=1).sum(
                axis=1, min_count=1
            )
        else:
            df["people_affected_reported"] = pd.NA

    df = df.dropna(subset=["country", "year", "disaster_type"]).copy()
    df["year"] = df["year"].astype(int)
    df = df[df["year"].between(START_YEAR, END_YEAR)].copy()
    df["disaster_type_clean"] = df["disaster_type"].str.strip().str.casefold()
    df = df[df["disaster_type_clean"].isin(CLIMATE_DISASTER_TYPES)].copy()

    if df.empty:
        raise ValueError(
            "No records remain after filtering. Check the year range and exact disaster-type "
            f"labels in your file. Available types: {sorted(raw[type_col].dropna().astype(str).unique())}"
        )

    # Each row is a disaster-country record. Preserve missing impact values as missing.
    df["recorded_event_count"] = 1
    df["deaths_known"] = df["deaths_reported"].notna().astype(int)
    df["affected_known"] = df["people_affected_reported"].notna().astype(int)

    # Export event-level cleaned data.
    event_output = OUTPUT_DIR / "cleaned_climate_disaster_events.csv"
    df.drop(columns=["disaster_type_clean"]).to_csv(event_output, index=False)

    # Aggregate by country and year.
    grouped = df.groupby(["country", "iso3", "year"], dropna=False).agg(
        recorded_disaster_events=("recorded_event_count", "sum"),
        deaths_reported_sum=("deaths_reported", lambda s: s.sum(min_count=1)),
        affected_people_reported_sum=("people_affected_reported", lambda s: s.sum(min_count=1)),
        records_with_death_data=("deaths_known", "sum"),
        records_with_affected_data=("affected_known", "sum"),
    ).reset_index()

    print("Downloading World Bank population and GDP-per-capita data...")
    try:
        population = download_world_bank_indicator(
            POPULATION_INDICATOR, START_YEAR, END_YEAR
        )
        gdp = download_world_bank_indicator(
            GDP_PER_CAPITA_INDICATOR, START_YEAR, END_YEAR
        )
        wb = population.merge(
            gdp[["iso3", "year", GDP_PER_CAPITA_INDICATOR]],
            on=["iso3", "year"],
            how="outer",
        )
        grouped = grouped.merge(
            wb[["iso3", "year", POPULATION_INDICATOR, GDP_PER_CAPITA_INDICATOR]],
            on=["iso3", "year"],
            how="left",
        )
    except Exception as exc:
        print(f"Warning: World Bank data could not be downloaded: {exc}")
        print("Continuing without World Bank indicators.")
        grouped[POPULATION_INDICATOR] = pd.NA
        grouped[GDP_PER_CAPITA_INDICATOR] = pd.NA

    grouped["deaths_per_100k_population"] = (
        grouped["deaths_reported_sum"] / grouped[POPULATION_INDICATOR] * 100_000
    )
    grouped["affected_per_100k_population"] = (
        grouped["affected_people_reported_sum"] / grouped[POPULATION_INDICATOR] * 100_000
    )

    country_year_output = OUTPUT_DIR / "country_year_climate_disaster_summary.csv"
    grouped.to_csv(country_year_output, index=False)

    disaster_type_summary = build_disaster_type_summary(df)
    disaster_type_output = OUTPUT_DIR / "disaster_type_summary.csv"
    disaster_type_summary.to_csv(disaster_type_output, index=False)

    gdp_vs_mortality = build_gdp_vs_mortality_summary(grouped)

    # ---------- CHART 1: Global recorded disaster events by year ----------
    annual = df.groupby("year").size().rename("recorded_disaster_events").reset_index()
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(annual["year"], annual["recorded_disaster_events"], marker="o", linewidth=2)
    ax.set_title(
        f"Recorded Climate-Related Disaster Events ({START_YEAR}–{END_YEAR})",
        fontsize=14,
    )
    ax.set_xlabel("Year")
    ax.set_ylabel("Recorded disaster-country records")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    chart1 = OUTPUT_DIR / "week4_disaster_events_over_time.png"
    fig.savefig(chart1, dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---------- CHART 2: Countries with the highest population-adjusted disaster rates ----------
    country_risk = build_country_risk_summary(grouped)
    # Use a reporting-aware comparison to avoid overstating countries with more complete data collection.
    top_countries = country_risk.head(12).sort_values("avg_annual_events_per_100k")

    fig, ax = plt.subplots(figsize=(10, 6))
    top_countries.plot(
        kind="barh",
        x="country",
        y="avg_annual_events_per_100k",
        ax=ax,
        color="#d95f02",
    )
    ax.set_title(
        f"Countries with the Highest Average Annual Climate Disaster Rate ({START_YEAR}–{END_YEAR})",
        fontsize=13,
    )
    ax.set_xlabel("Average annual reported events per 100,000 people")
    ax.set_ylabel("Country")
    ax.grid(axis="x", alpha=0.3)
    ax.set_xlim(0, max(top_countries["avg_annual_events_per_100k"].max() * 1.25, 0.01))
    fig.tight_layout()
    chart2 = OUTPUT_DIR / "week4_top_countries_by_events.png"
    fig.savefig(chart2, dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---------- CHART 3: Disaster type mix ----------
    type_top = disaster_type_summary.head(5).sort_values("share_of_records")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    type_top.plot(kind="barh", x="disaster_type_clean", y="share_of_records", ax=ax, color="#1b9e77")
    ax.set_title("Most Common Climate-Related Disaster Types in the Dataset")
    ax.set_xlabel("Share of all recorded climate-disaster records")
    ax.set_ylabel("Disaster type")
    ax.set_xlim(0, max(type_top["share_of_records"].max() * 1.2, 0.05))
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    chart3 = OUTPUT_DIR / "week4_disaster_type_mix.png"
    fig.savefig(chart3, dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---------- CHART 4: GDP per capita versus disaster mortality ----------
    if not gdp_vs_mortality.empty:
        fig, ax = plt.subplots(figsize=(9, 6))
        x = gdp_vs_mortality["avg_gdp_per_capita"]
        y = gdp_vs_mortality["avg_deaths_per_100k"]
        slope, intercept = np.polyfit(x, y, 1)
        ax.scatter(x, y, alpha=0.7, s=50, color="#7b2cbf")
        ax.plot(x.sort_values(), (slope * x.sort_values() + intercept), color="#444", linewidth=1.5, alpha=0.8)
        corr = x.corr(y)
        ax.set_title("Average GDP per Capita vs. Average Disaster Deaths per 100k")
        ax.set_xlabel("Average GDP per capita (current USD)")
        ax.set_ylabel("Average deaths per 100,000 people")
        ax.grid(alpha=0.25)
        ax.text(
            0.02,
            0.97,
            f"Correlation: {corr:.2f}",
            transform=ax.transAxes,
            fontsize=10,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
        )
        fig.tight_layout()
        chart4 = OUTPUT_DIR / "week4_gdp_vs_deaths.png"
        fig.savefig(chart4, dpi=200, bbox_inches="tight")
        plt.close(fig)
    else:
        chart4 = None

    # Basic quality/coverage report to prevent overclaiming.
    report = [
        "ISS Week 4 — Data Quality and Coverage Summary",
        f"Input file: {source_path.name}",
        f"Selected years: {START_YEAR}–{END_YEAR}",
        f"Selected disaster types: {', '.join(sorted(CLIMATE_DISASTER_TYPES))}",
        f"Event-country records after filters: {len(df):,}",
        f"Countries represented: {df['country'].nunique():,}",
        f"Years represented: {df['year'].nunique():,}",
        f"Rows with reported deaths: {df['deaths_reported'].notna().sum():,}",
        f"Rows with reported affected population: {df['people_affected_reported'].notna().sum():,}",
        "",
        "Key findings:",
        f"- {disaster_type_summary.iloc[0]['disaster_type_clean'].title()} is the most common disaster type, accounting for {disaster_type_summary.iloc[0]['share_of_records'] * 100:.1f}% of all records.",
        f"- The top two disaster types account for {disaster_type_summary.head(2)['share_of_records'].sum() * 100:.1f}% of all recorded climate-disaster records.",
        f"- The country-level comparison is population-adjusted to reduce the effect of reporting intensity differences across countries.",
        "",
        "Interpretation cautions:",
        "- These are recorded disaster-country records, not necessarily unique global events.",
        "- Missing impact values are not treated as zero.",
        "- Disaster counts can be affected by reporting and database coverage changes.",
        "- Raw event totals are not a fair cross-country comparison because reporting intensity differs by country.",
        "- Country rankings in this project are population-adjusted and filtered for poor coverage to reduce reporting bias.",
        "- Disaster records alone do not prove climate change caused an individual event.",
        "- Population-adjusted totals can still be incomplete if impact reporting is missing.",
    ]
    (OUTPUT_DIR / "week4_data_quality_notes.txt").write_text("\n".join(report), encoding="utf-8")

    print("\nFinished. Outputs saved in:", OUTPUT_DIR.resolve())
    print("1.", event_output)
    print("2.", country_year_output)
    print("3.", chart1)
    print("4.", chart2)
    print("5.", chart3)
    if chart4 is not None:
        print("6.", chart4)
    print("7.", OUTPUT_DIR / "week4_data_quality_notes.txt")
    print("\nQuick data overview:")
    print(f"- Filtered event-country records: {len(df):,}")
    print(f"- Countries: {df['country'].nunique():,}")
    print(f"- Years: {df['year'].min()}–{df['year'].max()}")
    if not disaster_type_summary.empty:
        print(f"- Most common hazard: {disaster_type_summary.iloc[0]['disaster_type_clean'].title()} ({disaster_type_summary.iloc[0]['share_of_records'] * 100:.1f}% of records)")
    print("\nDo not present results until you have reviewed the output charts and data-quality notes.")


if __name__ == "__main__":
    main()
