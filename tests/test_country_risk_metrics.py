import pandas as pd

from iss_week4_climate_disaster_analysis import build_country_risk_summary


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
