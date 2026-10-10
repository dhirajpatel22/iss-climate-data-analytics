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
WEEK7_OUTPUT_DIR = Path("iss_week7_outputs")
UNUSUAL_YEAR_Z_THRESHOLD = 1.5

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


def build_annual_impact_summary(event_df, country_year_df):
    """Summarize yearly event counts and reported human impacts."""
    events = (
        event_df.groupby("year")
        .agg(
            recorded_events=("recorded_event_count", "sum"),
            countries_affected=("country", "nunique"),
            records_with_death_data=("deaths_known", "sum"),
            records_with_affected_data=("affected_known", "sum"),
        )
        .reset_index()
    )

    impacts = (
        country_year_df.groupby("year")
        .agg(
            reported_deaths=("deaths_reported_sum", lambda s: s.sum(min_count=1)),
            reported_affected=("affected_people_reported_sum", lambda s: s.sum(min_count=1)),
        )
        .reset_index()
    )

    annual = events.merge(impacts, on="year", how="left")
    annual = annual.sort_values("year").reset_index(drop=True)

    annual["events_3yr_avg"] = annual["recorded_events"].rolling(window=3, min_periods=2).mean()

    mean_events = annual["recorded_events"].mean()
    std_events = annual["recorded_events"].std(ddof=0)

    if pd.notna(std_events) and std_events > 0:
        annual["event_count_zscore"] = (annual["recorded_events"] - mean_events) / std_events
    else:
        annual["event_count_zscore"] = 0.0

    annual["unusual_event_year"] = (
        annual["event_count_zscore"].abs() >= UNUSUAL_YEAR_Z_THRESHOLD
    )
    return annual


def build_disaster_severity_summary(event_df, min_records=10):
    """Compare reported human impacts by disaster type."""
    df = event_df.copy()

    summary = (
        df.groupby("disaster_type_clean")
        .agg(
            recorded_events=("recorded_event_count", "sum"),
            records_with_death_data=("deaths_reported", "count"),
            records_with_affected_data=("people_affected_reported", "count"),
            total_reported_deaths=("deaths_reported", lambda s: s.sum(min_count=1)),
            total_reported_affected=("people_affected_reported", lambda s: s.sum(min_count=1)),
            mean_deaths_per_record=("deaths_reported", "mean"),
            median_deaths_per_record=("deaths_reported", "median"),
            mean_affected_per_record=("people_affected_reported", "mean"),
            median_affected_per_record=("people_affected_reported", "median"),
        )
        .reset_index()
    )

    summary["death_reporting_share"] = summary["records_with_death_data"] / summary["recorded_events"]
    summary["affected_reporting_share"] = summary["records_with_affected_data"] / summary["recorded_events"]
    summary["enough_death_data"] = summary["records_with_death_data"] >= min_records
    summary["enough_affected_data"] = summary["records_with_affected_data"] >= min_records

    return summary.sort_values("recorded_events", ascending=False).reset_index(drop=True)


def build_country_impact_summary(country_year_df, min_years=5):
    """Compare countries using reported impacts and population-adjusted rates."""
    df = country_year_df.copy()

    required = {"country", "year", "deaths_reported_sum", "affected_people_reported_sum", POPULATION_INDICATOR}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    df["population"] = pd.to_numeric(df[POPULATION_INDICATOR], errors="coerce")
    df["deaths_per_100k"] = df["deaths_reported_sum"] / df["population"] * 100_000
    df["affected_per_100k"] = df["affected_people_reported_sum"] / df["population"] * 100_000
    df["valid_impact_year"] = (
        df["population"].notna()
        & (
            df["deaths_reported_sum"].notna()
            | df["affected_people_reported_sum"].notna()
        )
    )

    summary = (
        df.groupby("country")
        .agg(
            years_with_data=("valid_impact_year", "sum"),
            total_reported_deaths=("deaths_reported_sum", lambda s: s.sum(min_count=1)),
            total_reported_affected=("affected_people_reported_sum", lambda s: s.sum(min_count=1)),
            mean_annual_deaths_per_100k=("deaths_per_100k", "mean"),
            mean_annual_affected_per_100k=("affected_per_100k", "mean"),
            mean_population=("population", "mean"),
        )
        .reset_index()
    )

    return (
        summary[summary["years_with_data"] >= min_years]
        .sort_values("mean_annual_deaths_per_100k", ascending=False)
        .reset_index(drop=True)
    )


def save_week7_charts(annual, severity, countries, output_dir):
    """Create additional charts for the Week 7 presentation."""
    chart_paths = []

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(annual["year"], annual["recorded_events"], marker="o", alpha=0.65, label="Annual records")
    ax.plot(annual["year"], annual["events_3yr_avg"], linewidth=2.5, label="3-year rolling average")
    ax.set_title("Recorded Climate-Related Disaster Trends")
    ax.set_xlabel("Year")
    ax.set_ylabel("Recorded disaster-country records")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = output_dir / "week7_annual_disaster_trends.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    chart_paths.append(path)

    severity_plot = severity[
        severity["enough_death_data"] & severity["mean_deaths_per_record"].notna()
    ].sort_values("mean_deaths_per_record").tail(10)

    if not severity_plot.empty:
        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax.barh(severity_plot["disaster_type_clean"], severity_plot["mean_deaths_per_record"])
        ax.set_title("Average Reported Deaths per Record by Disaster Type")
        ax.set_xlabel("Mean reported deaths per record")
        ax.set_ylabel("Disaster type")
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        path = output_dir / "week7_disaster_severity.png"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        chart_paths.append(path)

    country_plot = countries.dropna(subset=["mean_annual_deaths_per_100k"]).head(10).sort_values("mean_annual_deaths_per_100k")

    if not country_plot.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(country_plot["country"], country_plot["mean_annual_deaths_per_100k"])
        ax.set_title("Countries with Highest Average Reported Disaster Mortality")
        ax.set_xlabel("Mean annual reported deaths per 100,000 people")
        ax.set_ylabel("Country")
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        path = output_dir / "week7_country_mortality_comparison.png"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        chart_paths.append(path)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = ["#d95f02" if unusual else "#7570b3" for unusual in annual["unusual_event_year"]]
    ax.bar(annual["year"], annual["recorded_events"], color=colors)
    ax.set_title("Annual Disaster Records and Unusual Years")
    ax.set_xlabel("Year")
    ax.set_ylabel("Recorded disaster-country records")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = output_dir / "week7_unusual_years.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    chart_paths.append(path)

    return chart_paths


# ============================================================
# ISS WEEK 9 — FINAL PRESENTATION AND SYNTHESIS
# ============================================================

WEEK9_OUTPUT_DIR = Path("iss_week9_outputs")


def save_heatmap(pivot_df, title, xlabel, ylabel, output_path,
                 colorbar_label="Recorded disaster-country records"):
    """Save a readable heatmap and its underlying matrix."""
    if pivot_df.empty or pivot_df.size == 0:
        print(f"Skipping empty heatmap: {title}")
        return None

    # Prevent a chart from being generated when every cell is missing.
    values = pivot_df.to_numpy(dtype=float)
    if not np.isfinite(values).any():
        print(f"Skipping heatmap without numeric data: {title}")
        return None

    fig_width = max(10, min(18, pivot_df.shape[1] * 0.55 + 4))
    fig_height = max(5.5, min(16, pivot_df.shape[0] * 0.32 + 2.5))

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    image = ax.imshow(values, aspect="auto", cmap="YlOrRd",
                      interpolation="nearest")

    ax.set_title(title, fontsize=14, pad=14)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)

    ax.set_xticks(np.arange(len(pivot_df.columns)))
    ax.set_xticklabels(
        [str(x) for x in pivot_df.columns],
        rotation=45, ha="right", fontsize=8
    )
    ax.set_yticks(np.arange(len(pivot_df.index)))
    ax.set_yticklabels(
        [str(y) for y in pivot_df.index],
        fontsize=8
    )

    colorbar = fig.colorbar(image, ax=ax, shrink=0.85)
    colorbar.set_label(colorbar_label)

    fig.tight_layout()
    fig.savefig(output_path, dpi=250, bbox_inches="tight")
    plt.close(fig)
    return output_path


def create_week9_visualizations(event_df, country_year_df, output_dir):
    """Create final presentation-ready visualizations and heatmap data."""
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_paths = []

    # 1. Heatmap: disaster type by year.
    # Each cell is the number of recorded disaster-country rows.
    year_type = pd.crosstab(
        event_df["disaster_type_clean"].str.title(),
        event_df["year"]
    ).sort_index()

    year_type_csv = output_dir / "week9_heatmap_disaster_type_by_year.csv"
    year_type.to_csv(year_type_csv)

    path = save_heatmap(
        year_type,
        "Recorded Disaster Records by Hazard and Year (2000–2024)",
        "Year",
        "Disaster type",
        output_dir / "week9_heatmap_disaster_type_by_year.png"
    )
    if path:
        chart_paths.append(path)

    # 2. Heatmap: countries with the most records by hazard type.
    # This is a descriptive comparison, not a ranking of true disaster risk.
    country_type = pd.crosstab(
        event_df["country"],
        event_df["disaster_type_clean"].str.title()
    )

    top_country_names = (
        event_df["country"].value_counts().head(15).index
    )
    country_type = country_type.reindex(top_country_names).fillna(0)
    country_type = country_type.reindex(
        sorted(country_type.columns), axis=1
    )

    country_type_csv = (
        output_dir / "week9_heatmap_top_countries_by_hazard.csv"
    )
    country_type.to_csv(country_type_csv)

    path = save_heatmap(
        country_type,
        "Disaster Records by Hazard: 15 Countries with Most Records",
        "Disaster type",
        "Country",
        output_dir / "week9_heatmap_top_countries_by_hazard.png"
    )
    if path:
        chart_paths.append(path)

    # 3. Annual trend with a three-year rolling average.
    annual = (
        event_df.groupby("year")
        .size()
        .rename("recorded_records")
        .reset_index()
        .sort_values("year")
    )
    annual["three_year_average"] = (
        annual["recorded_records"].rolling(3, min_periods=1).mean()
    )
    annual.to_csv(
        output_dir / "week9_annual_trend_data.csv", index=False
    )

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.bar(
        annual["year"], annual["recorded_records"],
        alpha=0.65, label="Annual records"
    )
    ax.plot(
        annual["year"], annual["three_year_average"],
        linewidth=2.5, marker="o", markersize=3,
        label="Three-year rolling average"
    )
    ax.set_title("Recorded Climate-Related Disaster Records Over Time")
    ax.set_xlabel("Year")
    ax.set_ylabel("Recorded disaster-country records")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()

    path = output_dir / "week9_final_annual_trend.png"
    fig.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)
    chart_paths.append(path)

    # 4. Disaster type share.
    type_counts = (
        event_df["disaster_type_clean"]
        .value_counts()
        .rename_axis("disaster_type")
        .reset_index(name="records")
    )
    type_counts["share_percent"] = (
        type_counts["records"] / type_counts["records"].sum() * 100
    )
    type_counts.to_csv(
        output_dir / "week9_disaster_type_shares.csv", index=False
    )

    type_plot = type_counts.sort_values("records")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.barh(type_plot["disaster_type"], type_plot["records"])
    ax.set_title("Recorded Disaster Records by Hazard Type")
    ax.set_xlabel("Number of records")
    ax.set_ylabel("Disaster type")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()

    path = output_dir / "week9_final_hazard_comparison.png"
    fig.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)
    chart_paths.append(path)

    # 5. Impact reporting coverage.
    impact_coverage = pd.DataFrame({
        "impact_measure": ["Deaths", "People affected"],
        "records_with_reported_values": [
            event_df["deaths_reported"].notna().sum(),
            event_df["people_affected_reported"].notna().sum()
        ],
    })
    impact_coverage["total_records"] = len(event_df)
    impact_coverage["reporting_percent"] = (
        impact_coverage["records_with_reported_values"]
        / max(len(event_df), 1) * 100
    )
    impact_coverage.to_csv(
        output_dir / "week9_impact_reporting_coverage.csv", index=False
    )

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(
        impact_coverage["impact_measure"],
        impact_coverage["reporting_percent"]
    )
    ax.bar_label(bars, fmt="%.1f%%", padding=3)
    ax.set_ylim(0, 110)
    ax.set_title("Share of Records with Reported Human Impacts")
    ax.set_ylabel("Records with reported values (%)")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()

    path = output_dir / "week9_impact_reporting_coverage.png"
    fig.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)
    chart_paths.append(path)

    return chart_paths


def create_week9_synthesis(
    event_df,
    country_year_df,
    annual_impact,
    severity_summary,
    disaster_type_summary,
    source_path,
    output_dir,
):
    """Generate evidence-based findings, recommendations, limitations,
    sources, and a slide-by-slide presentation outline."""
    output_dir.mkdir(parents=True, exist_ok=True)

    total_records = len(event_df)
    countries_count = event_df["country"].nunique()
    years_count = event_df["year"].nunique()

    type_counts = event_df["disaster_type_clean"].value_counts()
    dominant_type = type_counts.index[0]
    dominant_share = type_counts.iloc[0] / max(total_records, 1) * 100

    highest_year = (
        annual_impact.loc[annual_impact["recorded_events"].idxmax()]
        if not annual_impact.empty else None
    )
    lowest_year = (
        annual_impact.loc[annual_impact["recorded_events"].idxmin()]
        if not annual_impact.empty else None
    )

    death_coverage = (
        event_df["deaths_reported"].notna().mean() * 100
        if total_records else 0
    )
    affected_coverage = (
        event_df["people_affected_reported"].notna().mean() * 100
        if total_records else 0
    )

    findings = [
        (
            f"The filtered dataset contains {total_records:,} recorded "
            f"disaster-country records across {countries_count:,} countries "
            f"and {years_count:,} represented years ({START_YEAR}–{END_YEAR})."
        ),
        (
            f"{dominant_type.title()} is the most frequently recorded "
            f"hazard, accounting for {dominant_share:.1f}% of records. "
            "This describes the dataset, not necessarily the true global "
            "frequency of each hazard."
        ),
        (
            f"The highest-recorded year is {int(highest_year['year'])} "
            f"({int(highest_year['recorded_events']):,} records)."
            if highest_year is not None
            else "Annual peak could not be calculated."
        ),
        (
            f"The lowest-recorded year is {int(lowest_year['year'])} "
            f"({int(lowest_year['recorded_events']):,} records)."
            if lowest_year is not None
            else "Annual minimum could not be calculated."
        ),
        (
            f"Reported deaths are available for {death_coverage:.1f}% "
            f"of event records, while reported affected-person values "
            f"are available for {affected_coverage:.1f}%. "
            "Missing impact values limit comparisons of disaster severity."
        ),
    ]

    recommendations = [
        (
            "Prioritize local hazard preparedness using regional risk "
            "assessments, infrastructure exposure, and community input; "
            "do not allocate resources based on raw counts alone."
        ),
        (
            "Improve consistent reporting of deaths, affected populations, "
            "event dates, locations, and uncertainty so impacts can be "
            "compared more reliably across countries and years."
        ),
        (
            "Use hazard-specific early-warning systems, evacuation plans, "
            "and resilient infrastructure appropriate to local conditions."
        ),
        (
            "Combine disaster records with climate observations, exposure, "
            "vulnerability, and longer-term trend analyses before making "
            "claims about climate change attribution or causal effects."
        ),
    ]

    limitations = [
        "EM-DAT records represent reported disaster-country records; a row "
        "should not automatically be interpreted as a unique global event.",
        "Recorded counts depend on database inclusion rules, reporting "
        "capacity, event classification, and changes in data coverage.",
        "Blank death and affected-person fields represent missing or "
        "unreported information, not confirmed zero impact.",
        "Population-adjusted counts do not account for differences in "
        "exposure, vulnerability, preparedness, or reporting quality.",
        "Country and hazard rankings may be distorted by differences in "
        "coverage and reporting practices.",
        "World Bank population and GDP indicators may be missing for some "
        "countries or years; GDP per capita is not a direct measure of "
        "preparedness or resilience.",
        "This observational analysis cannot establish that climate change "
        "caused individual disasters or explain trends on its own.",
        "The selected hazards and 2000–2024 period do not cover every "
        "disaster category or historical period.",
    ]

    sources = [
        "EM-DAT, The International Disaster Database, Centre for Research "
        "on the Epidemiology of Disasters (CRED): "
        "https://public.emdat.be/data",
        "World Bank Indicators API — Population (SP.POP.TOTL): "
        "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL",
        "World Bank Indicators API — GDP per capita, current US$ "
        "(NY.GDP.PCAP.CD): "
        "https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD",
        "Python libraries used: pandas, NumPy, Matplotlib, requests, "
        "and openpyxl. These are analysis tools, not independent data sources.",
    ]

    report_lines = [
        "ISS WEEK 9 — FINAL PRESENTATION SYNTHESIS",
        f"Study period: {START_YEAR}–{END_YEAR}",
        f"Input file: {source_path.name}",
        "",
        "KEY FINDINGS",
    ]
    report_lines.extend(
        f"{i}. {finding}" for i, finding in enumerate(findings, 1)
    )
    report_lines.extend(["", "RECOMMENDATIONS"])
    report_lines.extend(
        f"{i}. {item}" for i, item in enumerate(recommendations, 1)
    )
    report_lines.extend(["", "LIMITATIONS"])
    report_lines.extend(f"- {item}" for item in limitations)
    report_lines.extend(["", "SOURCES"])
    report_lines.extend(f"- {item}" for item in sources)

    (output_dir / "week9_final_synthesis_report.txt").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )

    # A compact outline mapped to the required presentation structure.
    slides = [
        ("Slide 1 — Title",
         "Climate Change and Disaster Resilience: Recorded climate-related "
         "disaster patterns, 2000–2024."),
        ("Slide 2 — Research Journey",
         "Presentation 1: initial dataset, research question, and cleaning. "
         "Presentation 2: annual trends, hazard comparisons, and data quality. "
         "Presentation 3: heatmaps, synthesized findings, recommendations, "
         "and limitations. Edit this summary to match your actual first "
         "two presentations."),
        ("Slides 3–6 — Final Visualizations",
         "Use week9_final_annual_trend.png, "
         "week9_final_hazard_comparison.png, "
         "week9_heatmap_disaster_type_by_year.png, "
         "week9_heatmap_top_countries_by_hazard.png, and "
         "week9_impact_reporting_coverage.png. Choose the clearest four "
         "and explain what each chart can and cannot show."),
        ("Slide 7 — Key Findings",
         "\n".join(f"- {x}" for x in findings[:5])),
        ("Slide 8 — Recommendations",
         "\n".join(f"- {x}" for x in recommendations)),
        ("Slide 9 — Limitations",
         "\n".join(f"- {x}" for x in limitations)),
        ("Slide 10 — Sources",
         "\n".join(f"- {x}" for x in sources)),
    ]

    slide_lines = ["ISS WEEK 9 — PRESENTATION OUTLINE"]
    for title, body in slides:
        slide_lines.extend(["", title, body])

    (output_dir / "week9_slide_outline.txt").write_text(
        "\n".join(slide_lines), encoding="utf-8"
    )

    findings_df = pd.DataFrame({
        "finding_number": range(1, len(findings) + 1),
        "finding": findings,
    })
    findings_df.to_csv(
        output_dir / "week9_key_findings.csv", index=False
    )
    pd.DataFrame({
        "recommendation_number": range(1, len(recommendations) + 1),
        "recommendation": recommendations,
    }).to_csv(
        output_dir / "week9_recommendations.csv", index=False
    )
    pd.DataFrame({
        "limitation_number": range(1, len(limitations) + 1),
        "limitation": limitations,
    }).to_csv(
        output_dir / "week9_limitations.csv", index=False
    )
    pd.DataFrame({
        "source_number": range(1, len(sources) + 1),
        "source": sources,
    }).to_csv(
        output_dir / "week9_sources.csv", index=False
    )



def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WEEK7_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
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

    print("Running Week 7 deeper analysis...")
    annual_impact = build_annual_impact_summary(df, grouped)
    severity_summary = build_disaster_severity_summary(df)
    country_impact = build_country_impact_summary(grouped)

    annual_impact.to_csv(WEEK7_OUTPUT_DIR / "week7_annual_impact_trends.csv", index=False)
    severity_summary.to_csv(WEEK7_OUTPUT_DIR / "week7_disaster_severity_summary.csv", index=False)
    country_impact.to_csv(WEEK7_OUTPUT_DIR / "week7_country_impact_comparison.csv", index=False)

    week7_charts = save_week7_charts(annual_impact, severity_summary, country_impact, WEEK7_OUTPUT_DIR)

    unusual_years = annual_impact[annual_impact["unusual_event_year"]].sort_values("event_count_zscore", ascending=False)
    highest_event_year = annual_impact.loc[annual_impact["recorded_events"].idxmax()]
    lowest_event_year = annual_impact.loc[annual_impact["recorded_events"].idxmin()]
    top_severity = severity_summary[
        severity_summary["enough_death_data"] & severity_summary["mean_deaths_per_record"].notna()
    ].sort_values("mean_deaths_per_record", ascending=False)
    top_mortality_countries = country_impact.dropna(subset=["mean_annual_deaths_per_100k"]).head(5)

    week7_report = [
        "ISS Week 7 — Deeper Analysis",
        f"Study period: {START_YEAR}–{END_YEAR}",
        f"Disaster categories: {', '.join(sorted(CLIMATE_DISASTER_TYPES))}",
        "",
        "1. Annual trends",
        f"Highest recorded event count: {int(highest_event_year['year'])} ({int(highest_event_year['recorded_events']):,} records).",
        f"Lowest recorded event count: {int(lowest_event_year['year'])} ({int(lowest_event_year['recorded_events']):,} records).",
        "These are counts of recorded disaster-country records, not necessarily unique global disasters.",
        "",
        "2. Unusual years",
    ]

    if unusual_years.empty:
        week7_report.append(
            "No years crossed the absolute "
            f"{UNUSUAL_YEAR_Z_THRESHOLD:g}-standard-deviation threshold for annual recorded event counts."
        )
    else:
        for _, row in unusual_years.iterrows():
            week7_report.append(f"- {int(row['year'])}: {int(row['recorded_events']):,} records; z-score {row['event_count_zscore']:.2f}.")

    week7_report.extend(["", "3. Disaster severity"])

    if top_severity.empty:
        week7_report.append("Insufficient reported death data to rank disaster types using the minimum reporting threshold.")
    else:
        row = top_severity.iloc[0]
        week7_report.append(
            f"Highest mean reported deaths per record among types with at least 10 reported-death records: "
            f"{row['disaster_type_clean']} ({row['mean_deaths_per_record']:.2f})."
        )

    week7_report.extend(["", "4. Country comparison"])

    if top_mortality_countries.empty:
        week7_report.append("No country comparisons could be produced with the available data.")
    else:
        for _, row in top_mortality_countries.iterrows():
            week7_report.append(
                f"- {row['country']}: {row['mean_annual_deaths_per_100k']:.4f} mean annual reported deaths per 100,000 people."
            )

    week7_report.extend([
        "",
        "5. Interpretation and limitations",
        "- Unusual years are statistical flags, not proof of a real-world cause.",
        "- Missing impact reports can bias averages and country comparisons.",
        "- A disaster-country record may not represent a unique global event.",
        "- Country comparisons require caution because reporting practices differ.",
        "- The five-year country coverage threshold does not guarantee complete data.",
        "- GDP per capita is an exploratory socioeconomic indicator, not proof of causation.",
        "- Disaster trends alone cannot establish that climate change caused these events.",
        "- Population-adjusted reported deaths are not a complete measure of disaster risk.",
        "- Review all exported charts and source data before presenting findings.",
    ])

    (WEEK7_OUTPUT_DIR / "week7_deeper_analysis_report.txt").write_text("\n".join(week7_report), encoding="utf-8")


    # ---------- WEEK 9: FINAL PRESENTATION OUTPUTS ----------
    print("\nRunning Week 9 final presentation analysis...")

    WEEK9_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    week9_charts = create_week9_visualizations(
        event_df=df,
        country_year_df=grouped,
        output_dir=WEEK9_OUTPUT_DIR,
    )

    create_week9_synthesis(
        event_df=df,
        country_year_df=grouped,
        annual_impact=annual_impact,
        severity_summary=severity_summary,
        disaster_type_summary=disaster_type_summary,
        source_path=source_path,
        output_dir=WEEK9_OUTPUT_DIR,
    )

    print("\nWeek 9 outputs saved in:", WEEK9_OUTPUT_DIR.resolve())
    for output_path in week9_charts:
        print("-", output_path)

    print("- Week 9 synthesis report")
    print("- Week 9 slide outline")
    print("- Week 9 key findings, recommendations, limitations, and sources")

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
    print("Week 7 outputs saved in:", WEEK7_OUTPUT_DIR.resolve())
    for output_path in week7_charts:
        print("-", output_path)
    print("-", WEEK7_OUTPUT_DIR / "week7_annual_impact_trends.csv")
    print("-", WEEK7_OUTPUT_DIR / "week7_disaster_severity_summary.csv")
    print("-", WEEK7_OUTPUT_DIR / "week7_country_impact_comparison.csv")
    print("-", WEEK7_OUTPUT_DIR / "week7_deeper_analysis_report.txt")
    print("\nQuick data overview:")
    print(f"- Filtered event-country records: {len(df):,}")
    print(f"- Countries: {df['country'].nunique():,}")
    print(f"- Years: {df['year'].min()}–{df['year'].max()}")
    if not disaster_type_summary.empty:
        print(f"- Most common hazard: {disaster_type_summary.iloc[0]['disaster_type_clean'].title()} ({disaster_type_summary.iloc[0]['share_of_records'] * 100:.1f}% of records)")
    print("\nDo not present results until you have reviewed the output charts and data-quality notes.")


if __name__ == "__main__":
    main()
