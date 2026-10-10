# ISS Week 4 — Climate Change and Disaster Resilience

## Project Overview

This project explores patterns in recorded climate-related disasters across countries from **2000 to 2024**. Using disaster records from the EM-DAT International Disaster Database and socioeconomic indicators from the World Bank, the analysis examines how reported disaster frequency, population exposure, and disaster-related mortality vary across time and countries.

The goal is to establish a research foundation for understanding disaster resilience and identifying questions for further investigation. The project uses Python to clean and integrate datasets, generate country-level summaries, visualize trends, and document data quality limitations.

**Research questions:**
- How have recorded climate-related disaster events changed over time?
- Which types of disasters account for the largest share of recorded events?
- How do population-adjusted disaster event rates vary across countries?
- Is there an observable relationship between GDP per capita and reported disaster mortality?

These questions are exploratory. The analysis does not establish that climate change caused any individual disaster or that GDP per capita directly determines disaster resilience.

## Data Sources

### 1. EM-DAT International Disaster Database

- **Source:** [EM-DAT Public Data](https://public.emdat.be/data)
- **Purpose:** Provides disaster records, including disaster classifications, countries, years, and reported impacts.
- **Access:** Download the public data spreadsheet manually. Registration and acceptance of the database's terms may be required.

The script filters records to the following disaster types:

- Flood
- Storm
- Drought
- Extreme temperature
- Wildfire

The selected records are restricted to the years 2000–2024.

**Important:** Disaster type labels and column names may differ between EM-DAT data releases. Verify the downloaded spreadsheet before running the analysis.

### 2. World Bank Indicators

- **Source:** [World Bank Open Data](https://data.worldbank.org/)
- **API documentation:** [World Bank Indicators API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392)

The script retrieves two indicators programmatically:

| Indicator | Code | Purpose |
|---|---|---|
| Population, total | `SP.POP.TOTL` | Calculate population-adjusted disaster rates |
| GDP per capita, current US$ | `NY.GDP.PCAP.CD` | Explore the relationship between economic conditions and reported disaster mortality |

World Bank observations are matched to disaster records using ISO-3 country codes and year. Missing matches may occur because of differences in country coverage or identifier availability.

## Technologies

- **Python** — analysis and data processing
- **pandas** — data cleaning, aggregation, and dataset integration
- **NumPy** — numerical calculations and trend-line fitting
- **Requests** — retrieving World Bank indicators through the API
- **Matplotlib** — data visualization
- **openpyxl** — reading Excel spreadsheets through pandas

## Project Structure

```text
.
├── main.py
├── data/
│   └── emdat_public.xlsx
├── iss_week4_outputs/
│   ├── cleaned_climate_disaster_events.csv
│   ├── country_year_climate_disaster_summary.csv
│   ├── disaster_type_summary.csv
│   ├── week4_disaster_events_over_time.png
│   ├── week4_top_countries_by_events.png
│   ├── week4_disaster_type_mix.png
│   ├── week4_gdp_vs_deaths.png
│   └── week4_data_quality_notes.txt
└── README.md
```

The `data/` directory contains the manually downloaded EM-DAT spreadsheet. The `iss_week4_outputs/` directory is created automatically when the script runs.

The GDP-versus-mortality chart is only generated when sufficient country-level data are available.

## Setup and Installation

### Prerequisites

- Python 3.10 or newer recommended
- An EM-DAT public data spreadsheet
- Internet access to retrieve World Bank indicators

### 1. Clone or download the project

Place the Python script in your project directory.

### 2. Download the EM-DAT dataset

Download the public data spreadsheet from [EM-DAT](https://public.emdat.be/data).

Place the downloaded file at:

```text
data/emdat_public.xlsx
```

Alternatively, update the `EM_DAT_FILE` setting at the top of the Python script to match your file's location.

### 3. Install dependencies

Run the following command in your terminal:

```bash
pip install pandas requests matplotlib numpy openpyxl
```

If you use a virtual environment, activate it before installing the dependencies.

### 4. Run the analysis

From the project directory, execute:

```bash
python iss_week4_climate_disaster_analysis.py
```

The script reads and filters the EM-DAT spreadsheet, attempts to retrieve the World Bank indicators, creates summary datasets and visualizations, and saves the results in `iss_week4_outputs/`.

If the EM-DAT spreadsheet cannot be found, the script prints an error message and exits. If the World Bank API request fails, it attempts to continue without the socioeconomic indicators.

## Methodology

### 1. Data cleaning

The script identifies relevant columns in the EM-DAT spreadsheet, standardizes country names and disaster classifications, converts years and impact fields to appropriate data types, and removes records missing essential country, year, or disaster-type information.

It then filters the dataset to the selected disaster categories and study period.

Missing impact values are preserved as missing rather than automatically treated as zero.

### 2. Event-level analysis

Each retained EM-DAT row is treated as a recorded disaster-country record. The cleaned event-level dataset preserves the available information for further analysis.

### 3. Country-year aggregation

The filtered records are grouped by country, ISO-3 code, and year. The resulting dataset includes:

- Number of recorded disaster-country records
- Sum of reported deaths
- Sum of reported affected people
- Number of records with reported death data
- Number of records with reported affected-population data
- World Bank population and GDP-per-capita indicators, when available
- Reported deaths and affected people per 100,000 population

The population-adjusted impact measures provide additional context for comparing countries of different sizes.

### 4. Country-level comparisons

The country risk summary calculates average annual recorded disaster events per 100,000 people. Countries with fewer than three represented years or an average population below one million are excluded from this ranking.

The GDP-versus-mortality summary requires at least four years of available data per country.

These filters improve consistency but do not eliminate differences in disaster reporting, data completeness, or exposure to hazards.

## Outputs and Visualizations

| Output | Description |
|---|---|
| `cleaned_climate_disaster_events.csv` | Cleaned event-level records for the selected disaster categories and years |
| `country_year_climate_disaster_summary.csv` | Country-year event counts, reported impacts, population, GDP per capita, and population-adjusted measures |
| `disaster_type_summary.csv` | Recorded counts and shares for each selected disaster type |
| `week4_disaster_events_over_time.png` | Line chart of recorded disaster-country records by year |
| `week4_top_countries_by_events.png` | Horizontal bar chart of countries with the highest average annual population-adjusted event rates |
| `week4_disaster_type_mix.png` | Horizontal bar chart showing the most common disaster types |
| `week4_gdp_vs_deaths.png` | Scatter plot comparing average GDP per capita with average reported deaths per 100,000 people, including a correlation coefficient and fitted line |
| `week4_data_quality_notes.txt` | Summary of dataset coverage, key descriptive findings, and interpretation cautions |

The script also prints a brief overview of the filtered dataset and the locations of its generated outputs.

## Data Quality and Limitations

Several limitations must be considered when interpreting the results.

**Recorded events are not necessarily unique global disasters.** The event-level count reflects retained EM-DAT rows, and a single disaster may affect multiple countries.

**Reporting coverage varies.** Countries may differ in their disaster documentation, reporting practices, and completeness of historical records. An increase in recorded events does not necessarily mean that the underlying frequency of disasters increased by the same amount.

**Missing values are not zero.** Blank death or affected-population fields may represent unreported or unknown impacts. Sums and averages based on available values may not capture the full impact of disasters.

**Population adjustment has limitations.** Events per 100,000 people is a descriptive rate, not a complete measure of disaster risk. It does not account for hazard intensity, geographic exposure, infrastructure, preparedness, or vulnerability.

**GDP per capita is not a direct measure of resilience.** The GDP-versus-mortality comparison is observational. It cannot establish causation, and reported mortality may be affected by differences in data coverage and disaster characteristics.

**Climate attribution requires additional evidence.** The selected categories include weather- and climate-related hazards, but the presence of a disaster record does not establish that climate change caused that event. Stronger attribution would require additional climate, exposure, and hazard-specific evidence.

Review the generated charts and `week4_data_quality_notes.txt` before drawing conclusions or presenting findings.

## Research Significance and Next Steps

This analysis establishes an initial dataset for investigating climate-related disasters and disaster resilience. Future stages of the project could build on these outputs by:

1. Investigating long-term changes in disaster frequency and reported impacts.
2. Examining regional differences in disaster exposure and population-adjusted mortality.
3. Comparing disaster outcomes with additional indicators of economic development, infrastructure, and preparedness.
4. Exploring relationships between climate indicators and recorded disaster patterns.
5. Developing evidence-based recommendations for improving disaster preparedness and