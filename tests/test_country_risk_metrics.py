import pandas as pd

from main import (
    build_country_impact_summary,
    build_country_risk_summary,
    build_disaster_type_summary,
)


def test_build_disaster_type_summary_highlights_hazard_mix():
    df = pd.DataFrame(
        {
            "disaster_type_clean": [
                "flood",
                "flood",
                "storm",
                "storm",
                "drought",
                "wildfire",
            ]
        }
    )

    summary = build_disaster_type_summary(df)

    assert summary.iloc[0]["disaster_type_clean"] == "flood"
    assert summary.iloc[0]["share_of_records"] > 0.25
    assert abs(summary["share_of_records"].sum() - 1.0) < 1e-9


def test_build_country_risk_summary_prioritizes_population_adjusted_risk():
    df = pd.DataFrame(
        {
            "country": [
                "United States of America",
                "United States of America",
                "United States of America",
                "Bangladesh",
                "Bangladesh",
                "Bangladesh",
                "Tuvalu",
                "Tuvalu",
                "Tuvalu",
            ],
            "year": [2020, 2021, 2022, 2020, 2021, 2022, 2020, 2021, 2022],
            "recorded_disaster_events": [10, 10, 11, 20, 25, 30, 1, 2, 3],
            "SP.POP.TOTL": [330_000_000, 330_000_000, 330_000_000, 170_000_000, 170_000_000, 170_000_000, 11_000, 11_000, 11_000],
        }
    )

    summary = build_country_risk_summary(df)

    # The United States should not dominate a normalized ranking because the metric reflects exposure, not reporting volume.
    us_rate = summary.loc[summary["country"] == "United States of America", "avg_annual_events_per_100k"].iat[0]
    bangladesh_rate = summary.loc[summary["country"] == "Bangladesh", "avg_annual_events_per_100k"].iat[0]
    assert us_rate < bangladesh_rate

    # Tiny territories should be dropped from the ranked comparison for a more serious country-level analysis.
    assert "Tuvalu" not in set(summary["country"])

    # The metric should be annualized and normalized, not just raw total counts.
    assert "avg_annual_events_per_100k" in summary.columns
    assert "total_events" in summary.columns


def test_build_country_impact_summary_counts_only_valid_impact_years():
    df = pd.DataFrame(
        {
            "country": ["Exampleland"] * 5,
            "year": [2020, 2021, 2022, 2023, 2024],
            "deaths_reported_sum": [10, pd.NA, pd.NA, 5, pd.NA],
            "affected_people_reported_sum": [100, pd.NA, 200, pd.NA, pd.NA],
            "SP.POP.TOTL": [1_000_000, 1_000_000, pd.NA, 1_000_000, 1_000_000],
        }
    )

    summary = build_country_impact_summary(df, min_years=3)

    assert summary.empty
