from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
WEEK4_DIR = BASE_DIR / "iss_week4_outputs"
WEEK7_DIR = BASE_DIR / "iss_week7_outputs"
WEEK9_DIR = BASE_DIR / "iss_week9_outputs"

st.set_page_config(
    page_title="Climate Disaster Resilience Dashboard",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp { background: #f4f7f5; color: #173f3a; }
    [data-testid="stSidebar"] { background: #173f3a; }
    [data-testid="stSidebar"] * { color: #f2f7f4; }
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: #f2f7f4 !important;
    }
    [data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: #ffffff;
        border-color: #b8cec5;
    }
    [data-testid="stSidebar"] [data-baseweb="select"] *,
    [data-baseweb="popover"] [data-baseweb="menu"] * {
        color: #173f3a !important;
    }
    [data-testid="stSidebar"] input {
        color: #173f3a !important;
    }
    [data-testid="stAppViewContainer"] .stMarkdown,
    [data-testid="stAppViewContainer"] [data-testid="stCaptionContainer"] {
        color: #173f3a;
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        background: #ffffff;
        border-bottom: 1px solid #c8d8d2;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        color: #173f3a !important;
        background: #ffffff;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] p {
        color: #173f3a !important;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        color: #b7473a !important;
        font-weight: 700;
    }
    .hero {
        padding: 1.4rem 1.8rem 1.2rem;
        border-radius: 16px;
        background: linear-gradient(120deg, #173f3a 0%, #236b5d 62%, #d97745 140%);
        color: white;
        margin-bottom: 1.2rem;
    }
    .hero h1 { margin: 0; font-size: 2.35rem; letter-spacing: 0; }
    .hero p { margin: .45rem 0 0; color: #dcebe5; font-size: 1.02rem; }
    .metric-card {
        background: white; border-left: 4px solid #d97745; padding: .8rem 1rem;
        border-radius: 10px; box-shadow: 0 2px 10px rgba(23,63,58,.08);
    }
    .metric-card * { color: #173f3a; }
    .note { color: #4d625d; font-size: .9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_csv(path):
    return pd.read_csv(path)


def require_file(path):
    if not path.exists():
        st.error(f"Missing required output: {path.relative_to(BASE_DIR)}")
        st.info("Run `python3 main.py` first to regenerate the analysis outputs.")
        st.stop()
    return path


def format_number(value):
    if pd.isna(value):
        return "N/A"
    return f"{value:,.0f}"


def format_rate(value):
    if pd.isna(value):
        return "N/A"
    return f"{value:,.2f}"


@st.cache_data(show_spinner=False)
def load_dashboard_data():
    events = load_csv(require_file(WEEK4_DIR / "cleaned_climate_disaster_events.csv"))
    country_year = load_csv(require_file(WEEK4_DIR / "country_year_climate_disaster_summary.csv"))
    severity = load_csv(require_file(WEEK7_DIR / "week7_disaster_severity_summary.csv"))
    annual = load_csv(require_file(WEEK7_DIR / "week7_annual_impact_trends.csv"))
    return events, country_year, severity, annual


def download_button(label, frame, filename):
    st.download_button(
        label,
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        use_container_width=True,
    )


def make_impact_summary(filtered_events, country_year):
    grouped = (
        filtered_events.groupby(["country", "iso3", "year"], dropna=False)
        .agg(
            recorded_events=("recorded_event_count", "sum"),
            reported_deaths=("deaths_reported", lambda values: values.sum(min_count=1)),
            reported_affected=("people_affected_reported", lambda values: values.sum(min_count=1)),
        )
        .reset_index()
    )
    population = country_year[
        ["country", "iso3", "year", "SP.POP.TOTL"]
    ].drop_duplicates(["country", "iso3", "year"])
    grouped = grouped.merge(population, on=["country", "iso3", "year"], how="left")
    grouped["deaths_per_100k"] = grouped["reported_deaths"] / grouped["SP.POP.TOTL"] * 100_000
    grouped["affected_per_100k"] = grouped["reported_affected"] / grouped["SP.POP.TOTL"] * 100_000
    return grouped


try:
    events, country_year, severity, annual = load_dashboard_data()
except Exception as exc:
    st.error(f"The dashboard could not load the generated analysis files: {exc}")
    st.stop()

for column in ("year", "recorded_event_count"):
    events[column] = pd.to_numeric(events[column], errors="coerce")
events = events.dropna(subset=["year"]).copy()
events["year"] = events["year"].astype(int)
hazard_column = "disaster_type_clean" if "disaster_type_clean" in events.columns else "disaster_type"
if hazard_column not in events.columns:
    st.error("The cleaned event data does not contain a disaster type column.")
    st.info("Run `python3 main.py` to regenerate the analysis outputs.")
    st.stop()
events["hazard"] = events[hazard_column].astype("string").str.strip().str.title()

st.sidebar.markdown("## Explore the evidence")
st.sidebar.caption("Filters apply to the event-level views and the impact comparison.")
year_min = int(events["year"].min())
year_max = int(events["year"].max())
year_range = st.sidebar.slider("Study years", year_min, year_max, (year_min, year_max))
hazards = sorted(events["hazard"].dropna().unique())
selected_hazards = st.sidebar.multiselect("Hazard types", hazards, default=hazards)
countries = sorted(events["country"].dropna().unique())
selected_countries = st.sidebar.multiselect(
    "Countries (optional)", countries, default=[], placeholder="All countries"
)

filtered_events = events[events["year"].between(*year_range)].copy()
if selected_hazards:
    filtered_events = filtered_events[filtered_events["hazard"].isin(selected_hazards)]
if selected_countries:
    filtered_events = filtered_events[filtered_events["country"].isin(selected_countries)]

st.markdown(
    """
    <div class="hero">
        <h1>Climate Disaster Resilience</h1>
        <p>Recorded disaster patterns, reported impacts, and the limits of what the data can tell us.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if filtered_events.empty:
    st.warning("No records match these filters. Widen the year, hazard, or country selection.")
    st.stop()

impact = make_impact_summary(filtered_events, country_year)
reported_deaths = filtered_events["deaths_reported"].sum(min_count=1)
reported_affected = filtered_events["people_affected_reported"].sum(min_count=1)
coverage_deaths = filtered_events["deaths_reported"].notna().mean() * 100
coverage_affected = filtered_events["people_affected_reported"].notna().mean() * 100

metric_columns = st.columns(5)
metrics = [
    ("Recorded records", format_number(len(filtered_events))),
    ("Countries represented", format_number(filtered_events["country"].nunique())),
    ("Reported deaths", format_number(reported_deaths)),
    ("Reported affected", format_number(reported_affected)),
    ("Death data coverage", f"{coverage_deaths:.1f}%"),
]
for column, (label, value) in zip(metric_columns, metrics):
    column.markdown(
        f'<div class="metric-card"><div class="note">{label}</div><strong>{value}</strong></div>',
        unsafe_allow_html=True,
    )

st.caption(
    f"Showing {year_range[0]}–{year_range[1]} | "
    f"{', '.join(selected_hazards) if selected_hazards else 'no hazards selected'} | "
    f"{len(filtered_events):,} filtered disaster-country records."
)

tab_overview, tab_impacts, tab_hazards, tab_data = st.tabs(
    ["Overview", "Impacts", "Hazard patterns", "Evidence & downloads"]
)

with tab_overview:
    left, right = st.columns([1.35, 1])
    with left:
        annual_filtered = (
            filtered_events.groupby("year")
            .size()
            .rename("Recorded records")
            .reset_index()
        )
        annual_filtered["Three-year average"] = annual_filtered["Recorded records"].rolling(3, min_periods=1).mean()
        fig = go.Figure()
        fig.add_bar(x=annual_filtered["year"], y=annual_filtered["Recorded records"], name="Recorded records", marker_color="#27796d")
        fig.add_scatter(x=annual_filtered["year"], y=annual_filtered["Three-year average"], name="Three-year average", mode="lines+markers", line=dict(color="#d97745", width=3))
        fig.update_layout(title="Recorded disaster-country records over time", yaxis_title="Records", xaxis_title="Year", hovermode="x unified", height=410)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        hazard_counts = filtered_events["hazard"].value_counts().sort_values()
        fig = px.bar(hazard_counts, x=hazard_counts.values, y=hazard_counts.index, orientation="h", color_discrete_sequence=["#d97745"])
        fig.update_layout(title="Hazard mix", xaxis_title="Recorded records", yaxis_title="", height=410)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### What stands out")
    peak = annual_filtered.loc[annual_filtered["Recorded records"].idxmax()]
    dominant = filtered_events["hazard"].value_counts().idxmax()
    dominant_share = filtered_events["hazard"].value_counts(normalize=True).iloc[0] * 100
    st.info(
        f"The selected view peaks in **{int(peak['year'])}** with **{int(peak['Recorded records']):,}** recorded records. "
        f"**{dominant}** is the largest hazard category at **{dominant_share:.1f}%** of the filtered records. "
        "These are reporting patterns, not direct measurements of true global disaster frequency."
    )

with tab_impacts:
    left, right = st.columns([1.2, 1])
    with left:
        impact_by_year = impact.groupby("year", as_index=False)[["reported_deaths", "reported_affected"]].sum(min_count=1)
        fig = go.Figure()
        fig.add_bar(x=impact_by_year["year"], y=impact_by_year["reported_deaths"], name="Reported deaths", marker_color="#b7473a")
        fig.update_layout(title="Reported deaths by year", yaxis_title="Reported deaths", xaxis_title="Year", height=390)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        coverage = pd.DataFrame({
            "Measure": ["Deaths", "People affected"],
            "Coverage": [coverage_deaths, coverage_affected],
        })
        fig = px.bar(coverage, x="Measure", y="Coverage", text="Coverage", color="Measure", color_discrete_sequence=["#b7473a", "#d97745"])
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(title="Impact reporting coverage", yaxis_title="Records with a reported value (%)", yaxis_range=[0, 110], showlegend=False, height=390)
        st.plotly_chart(fig, use_container_width=True)

    country_impact = (
        impact.groupby("country", as_index=False)
        .agg(
            years_with_data=("year", "nunique"),
            total_reported_deaths=("reported_deaths", lambda values: values.sum(min_count=1)),
            mean_deaths_per_100k=("deaths_per_100k", "mean"),
        )
        .dropna(subset=["mean_deaths_per_100k"])
        .query("years_with_data >= 3")
        .sort_values("mean_deaths_per_100k", ascending=False)
        .head(15)
        .sort_values("mean_deaths_per_100k")
    )
    if not country_impact.empty:
        fig = px.bar(country_impact, x="mean_deaths_per_100k", y="country", orientation="h", color_discrete_sequence=["#27796d"], hover_data=["years_with_data", "total_reported_deaths"])
        fig.update_layout(title="Highest average reported mortality among countries with 3+ years", xaxis_title="Mean reported deaths per 100,000", yaxis_title="", height=500)
        st.plotly_chart(fig, use_container_width=True)
    st.caption("Population-adjusted mortality is based on reported deaths and available population data; missing values are not treated as zero.")

with tab_hazards:
    left, right = st.columns([1.25, 1])
    with left:
        heatmap = pd.crosstab(filtered_events["hazard"], filtered_events["year"])
        fig = px.imshow(heatmap, aspect="auto", color_continuous_scale="YlOrRd", labels={"x": "Year", "y": "Hazard", "color": "Records"})
        fig.update_layout(title="Hazard records by year", height=500)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        country_hazard = pd.crosstab(filtered_events["country"], filtered_events["hazard"])
        top_names = filtered_events["country"].value_counts().head(15).index
        country_hazard = country_hazard.reindex(top_names).fillna(0)
        fig = px.imshow(country_hazard, aspect="auto", color_continuous_scale="Tealgrn", labels={"x": "Hazard", "y": "Country", "color": "Records"})
        fig.update_layout(title="Top recorded countries by hazard", height=500)
        st.plotly_chart(fig, use_container_width=True)

    severity_view = severity[severity["disaster_type_clean"].str.title().isin(selected_hazards)].copy()
    if not severity_view.empty:
        severity_view["Hazard"] = severity_view["disaster_type_clean"].str.title()
        severity_view = severity_view.dropna(subset=["mean_deaths_per_record"]).sort_values("mean_deaths_per_record")
        fig = px.bar(severity_view, x="mean_deaths_per_record", y="Hazard", orientation="h", color_discrete_sequence=["#b7473a"], hover_data=["records_with_death_data", "death_reporting_share"])
        fig.update_layout(title="Average reported deaths per record by hazard", xaxis_title="Mean reported deaths per record", yaxis_title="", height=380)
        st.plotly_chart(fig, use_container_width=True)

with tab_data:
    st.markdown("### Download the filtered evidence")
    st.caption("Use the downloads to inspect the exact records behind the dashboard views.")
    download_button("Download filtered event records", filtered_events, "filtered_climate_disaster_events.csv")
    download_button("Download filtered impact summary", impact, "filtered_country_year_impacts.csv")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Study notes")
        st.markdown(
            "Recorded disaster-country rows are not necessarily unique global disasters. "
            "Missing impact values are unknown, not zero. Cross-country comparisons can be "
            "affected by reporting capacity, exposure, classification, and database coverage."
        )
        report_path = WEEK9_DIR / "week9_final_synthesis_report.txt"
        if report_path.exists():
            st.download_button(
                "Download synthesis report",
                report_path.read_bytes(),
                file_name=report_path.name,
                mime="text/plain",
                use_container_width=True,
            )
    with col2:
        st.markdown("### Current filter scope")
        st.dataframe(
            pd.DataFrame({
                "Setting": ["Years", "Hazards", "Countries", "Records"],
                "Value": [
                    f"{year_range[0]}–{year_range[1]}",
                    ", ".join(selected_hazards),
                    ", ".join(selected_countries) if selected_countries else "All countries",
                    f"{len(filtered_events):,}",
                ],
            }),
            hide_index=True,
            use_container_width=True,
        )

st.markdown("---")
st.caption("Source: EM-DAT International Disaster Database and World Bank indicators. Exploratory analysis; not causal attribution.")
