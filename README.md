# MedLens

MedLens is a Streamlit web app that connects to a FHIR R4 server, pulls in a single
patient's medical history, and shows how their medications line up with changes in their lab
results. It focuses on three conditions: **high cholesterol**, **high blood pressure**, and
**diabetes**.

Planned views:

- **Timeline**: lab results over time, with each metric's goal range highlighted.
- **Scorecard**: how each medication relates to changes in specific lab results.
- **Safety Panel**: risks, warnings, and to-dos, drawn from scheduled labs, known drug pairings,
  and current medication use (up to 5 ongoing medications).
- **Comparison**: this patient's data plotted against other patients on the same medication.

Tracked metrics: blood pressure, A1c, glucose, potassium, creatinine, LDL, HDL, and weight.

## Tech stack

| Area           | Choice                                             |
| -------------- | -------------------------------------------------- |
| Language       | Python 3.11+                                       |
| UI             | Streamlit                                          |
| FHIR access    | `requests` against the FHIR R4 REST API            |
| Data handling  | pandas                                             |
| Charts         | Plotly / Matplotlib / Seaborn                      |
| Statistics     | statsmodels, SciPy                                 |
| Clinical rules | CSV files (interactions, monitoring, goal ranges)  |
| Hosting        | Streamlit Community Cloud                          |

There is no database or backend service. All data is read directly from FHIR.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run src/streamlit_app.py
```

### Data sources

- **SMART R4 sandbox** (`https://r4.smarthealthit.org`): the default. It's a public server with
  preloaded Synthea data and no authentication.
- **Local Synthea**: a fallback if the sandbox doesn't have the data we need. Run a HAPI FHIR
  server in Docker, load the Synthea bundles into it, and point MedLens at it:

  ```bash
  export FHIR_BASE_URL=http://localhost:8080/fhir
  ```

## FHIR client

`src/services/FHIR_client.py` handles all communication with the FHIR server. It reads
`Patient`, `MedicationRequest`, `Observation`, and `Condition` resources and turns them into
pandas DataFrames that the views can use directly. It only sends `GET` requests and never
writes to the server.


## Team

Arnav Mittal & Allen Siu
