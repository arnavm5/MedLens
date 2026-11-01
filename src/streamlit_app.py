from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from services.FHIR_client import (
    DEFAULT_BASE_URL,
    LAB_METRICS,
    LOCAL_SYNTHEA_URL,
    FHIRClient,
    FHIRClientError,
    PatientRecord,
    parse_patient,
)

DATA_SOURCES = {
    "SMART R4 sandbox": DEFAULT_BASE_URL,
    "Local Synthea (Docker)": LOCAL_SYNTHEA_URL,
    "Custom URL": None,
}

FOCUS_CONDITIONS = {
    "Cholesterol": ["ldl", "hdl"],
    "High blood pressure": ["systolic_bp", "diastolic_bp", "potassium", "creatinine"],
    "Diabetes": ["a1c", "glucose", "weight"],
}

DEMO_RXNORM_CODES = ["316672", "316049", "860975"]

MAX_TRACKED_MEDICATIONS = 5

VIEWS = ["Timeline", "Scorecard", "Safety Panel", "Comparison"]


@dataclass
class SidebarSelection:
    base_url: str
    patient_id: str | None
    role: str
    focus_metrics: list[str]

    @property
    def is_clinician(self) -> bool:
        return self.role == "Clinician"


def get_client(base_url: str) -> FHIRClient:
    return FHIRClient(base_url=base_url)


@st.cache_data(ttl=60, show_spinner=False)
def server_available(base_url: str) -> bool:
    return get_client(base_url).is_available()


@st.cache_data(ttl=600, show_spinner="Searching patients...")
def search_patients(base_url: str, name: str) -> list[dict]:
    return get_client(base_url).search_patients(name=name, max_results=25)


@st.cache_data(ttl=3600, show_spinner="Loading demo patients...")
def demo_patients(base_url: str) -> list[dict]:
    client = get_client(base_url)
    ids: list[str] = []
    for code in DEMO_RXNORM_CODES:
        ids += [pid for pid in client.find_patients_on_medication(code, max_patients=8) if pid not in ids]
    if not ids:
        return []

    return [parse_patient(p) for p in client.search("Patient", {"_id": ",".join(ids)})]


@st.cache_data(ttl=600, show_spinner="Loading patient record...")
def load_record(base_url: str, patient_id: str) -> PatientRecord:
    return get_client(base_url).get_patient_record(patient_id)


def _patient_label(patient: dict) -> str:
    details = [d for d in (patient.get("gender"), patient.get("birth_date")) if d]
    name = patient.get("name") or patient["id"]
    return f"{name} ({', '.join(details)})" if details else name


def _data_source_picker() -> str:
    source = st.selectbox("FHIR server", list(DATA_SOURCES), key="data_source")
    base_url = DATA_SOURCES[source]
    if base_url is None:
        base_url = st.text_input("Server URL", value=os.environ.get("FHIR_BASE_URL", DEFAULT_BASE_URL))

    base_url = base_url.strip().rstrip("/")
    if not server_available(base_url):
        st.caption(f":red[●] Can't reach `{base_url}`")
        return base_url

    st.caption(f":green[●] Connected to `{base_url}`")
    return base_url


def _patient_picker(base_url: str) -> str | None:
    name = st.text_input("Search by name", placeholder="e.g. Smith").strip()
    try:
        patients = search_patients(base_url, name) if name else demo_patients(base_url)
    except FHIRClientError as exc:
        st.error(f"Patient search failed: {exc}")
        patients = []

    if name and not patients:
        st.info(f"No patients found matching '{name}'.")

    selected = st.selectbox(
        "Patient" if name else "Demo patients",
        patients,
        format_func=_patient_label,
        index=None,
        placeholder="Choose a patient",
    )

    with st.expander("Enter a patient ID"):
        manual_id = st.text_input("Patient ID", label_visibility="collapsed").strip()

    if manual_id:
        return manual_id

    return selected["id"] if selected else None


def render_sidebar() -> SidebarSelection:
    with st.sidebar:
        st.title("MedLens")
        st.caption("Medication and lab result tracking")

        role = st.segmented_control("View as", ["Patient", "Clinician"], default="Patient", key="role") or "Patient"

        st.subheader("Data source")
        base_url = _data_source_picker()

        st.subheader("Patient")
        patient_id = _patient_picker(base_url)

        st.subheader("Focus")
        focus = st.multiselect("Conditions", list(FOCUS_CONDITIONS), default=list(FOCUS_CONDITIONS))
        focus_metrics = [m for condition in focus for m in FOCUS_CONDITIONS[condition]]

    return SidebarSelection(base_url=base_url, patient_id=patient_id, role=role, focus_metrics=focus_metrics)


def _age(birth_date: str | None) -> int | None:
    if not birth_date:
        return None

    born = date.fromisoformat(birth_date[:10])
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _format_date(value: pd.Timestamp | None) -> str:
    return "—" if value is None or pd.isna(value) else value.strftime("%b %d, %Y")


def _render_current_medications(active_meds: pd.DataFrame, is_clinician: bool) -> None:
    if active_meds.empty:
        return

    names = active_meds["name"].tolist()
    if is_clinician:
        names = [f"{row.name} (RxNorm {row.rxnorm})" if row.rxnorm else row.name for row in active_meds.itertuples()]

    st.caption("**Current medications:** " + ", ".join(names))
    if len(active_meds) > MAX_TRACKED_MEDICATIONS:
        st.caption(f"The safety panel tracks up to {MAX_TRACKED_MEDICATIONS} ongoing medications.")


def render_header(record: PatientRecord, selection: SidebarSelection) -> None:
    patient = record.patient
    age = _age(patient.get("birth_date"))

    st.title(patient.get("name") or "Unknown patient")
    details = [
        (patient.get("gender") or "").capitalize() or None,
        f"{age} years old" if age is not None else None,
        f"Born {patient['birth_date']}" if patient.get("birth_date") else None,
        "Deceased" if patient.get("deceased") else None,
    ]
    if selection.is_clinician:
        details.append(f"ID `{patient['id']}`")

    st.markdown(" · ".join(d for d in details if d))

    active_meds = record.medication_periods[record.medication_periods["active"]]
    active_conditions = record.conditions[record.conditions["clinical_status"] == "active"]
    labs = record.observations[record.observations["metric"].isin(selection.focus_metrics)]
    last_lab = labs["effective"].max() if not labs.empty else None

    labels = ("Medicines you take", "Health conditions", "Lab results on file", "Most recent lab")
    if selection.is_clinician:
        labels = ("Active medications", "Active conditions", "Tracked observations", "Last observation")

    cols = st.columns(4)
    cols[0].metric(labels[0], len(active_meds))
    cols[1].metric(labels[1], len(active_conditions))
    cols[2].metric(labels[2], len(labs))
    cols[3].metric(labels[3], _format_date(last_lab))

    _render_current_medications(active_meds, selection.is_clinician)

    if not selection.focus_metrics:
        st.warning("Choose at least one condition in the sidebar to see lab results.")

    st.divider()


def render_welcome() -> None:
    st.title("MedLens")
    st.markdown(
        "See how your medications line up with changes in your lab results. "
        "Choose a patient from the sidebar to get started."
    )
    st.markdown(
        "Tracked labs: " + ", ".join(info["label"] for info in LAB_METRICS.values()) + "."
    )


def main() -> None:
    st.set_page_config(page_title="MedLens", page_icon=":material/monitor_heart:", layout="wide")

    selection = render_sidebar()

    if not selection.patient_id:
        render_welcome()
        return

    try:
        record = load_record(selection.base_url, selection.patient_id)
    except FHIRClientError as exc:
        st.error(f"Could not load patient `{selection.patient_id}`: {exc}")
        return

    render_header(record, selection)

    for tab, view in zip(st.tabs(VIEWS), VIEWS):
        with tab:
            st.info(f"The {view} view is coming soon.")


main()
