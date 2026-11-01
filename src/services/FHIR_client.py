from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_BASE_URL = "https://r4.smarthealthit.org"
LOCAL_SYNTHEA_URL = "http://localhost:8080/fhir"

LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"

LAB_METRICS = {
    "systolic_bp": {"label": "Systolic blood pressure", "loinc": ["8480-6"]},
    "diastolic_bp": {"label": "Diastolic blood pressure", "loinc": ["8462-4"]},
    "a1c": {"label": "Hemoglobin A1c", "loinc": ["4548-4", "17856-6"]},
    "glucose": {"label": "Glucose", "loinc": ["2339-0", "2345-7"]},
    "potassium": {"label": "Potassium", "loinc": ["6298-4", "2823-3"]},
    "creatinine": {"label": "Creatinine", "loinc": ["38483-4", "2160-0"]},
    "ldl": {"label": "LDL cholesterol", "loinc": ["18262-6", "13457-7", "2089-1"]},
    "hdl": {"label": "HDL cholesterol", "loinc": ["2085-9"]},
    "weight": {"label": "Body weight", "loinc": ["29463-7"]},
}
BP_PANEL_LOINC = ["85354-9", "55284-4"]

LOINC_TO_METRIC = {code: metric for metric, info in LAB_METRICS.items() for code in info["loinc"]}
SEARCH_LOINC_CODES = BP_PANEL_LOINC + [
    code for metric, info in LAB_METRICS.items() if not metric.endswith("_bp") for code in info["loinc"]
]

OBSERVATION_COLUMNS = ["observation_id", "metric", "label", "loinc", "display", "value", "unit", "effective", "status"]
MEDICATION_COLUMNS = [
    "request_id", "rxnorm", "name", "status", "intent", "authored_on",
    "period_start", "period_end", "dosage", "reason",
]
PERIOD_COLUMNS = ["rxnorm", "name", "start", "end", "active", "request_count"]
CONDITION_COLUMNS = ["condition_id", "code", "system", "name", "clinical_status", "onset", "abatement", "recorded"]


class FHIRClientError(Exception):
    pass


@dataclass
class PatientRecord:
    patient: dict[str, Any]
    observations: pd.DataFrame
    medications: pd.DataFrame
    medication_periods: pd.DataFrame
    conditions: pd.DataFrame


class FHIRClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        page_size: int = 100,
        max_pages: int = 50,
        retries: int = 3,
    ) -> None:
        self.base_url = (base_url or os.environ.get("FHIR_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.page_size = page_size
        self.max_pages = max_pages

        retry = Retry(total=retries, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/fhir+json"
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if urlparse(url).netloc != urlparse(self.base_url).netloc:
            raise FHIRClientError(f"Refusing to request a different host: {url}")

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            raise FHIRClientError(f"FHIR server returned {response.status_code} for {response.url}") from exc
        except ValueError as exc:
            raise FHIRClientError(f"FHIR server returned invalid JSON for {response.url}") from exc
        except requests.RequestException as exc:
            raise FHIRClientError(f"Could not reach FHIR server at {self.base_url}: {exc}") from exc

    def iter_search(self, resource_type: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        bundle = self._get(f"{self.base_url}/{resource_type}", {"_count": self.page_size, **(params or {})})
        for _ in range(self.max_pages):
            yield from (entry["resource"] for entry in bundle.get("entry", []) if "resource" in entry)

            next_url = next((link["url"] for link in bundle.get("link", []) if link["relation"] == "next"), None)
            if next_url is None:
                return

            bundle = self._get(next_url)

    def search(
        self,
        resource_type: str,
        params: dict[str, Any] | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        results = []
        for resource in self.iter_search(resource_type, params):
            results.append(resource)
            if len(results) == max_results:
                return results

        return results

    def is_available(self) -> bool:
        try:
            return self._get(f"{self.base_url}/metadata").get("resourceType") == "CapabilityStatement"
        except FHIRClientError:
            return False

    def get_patient(self, patient_id: str) -> dict[str, Any]:
        return self._get(f"{self.base_url}/Patient/{patient_id}")

    def search_patients(
        self,
        name: str | None = None,
        birthdate: str | None = None,
        gender: str | None = None,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        params = {"name": name, "birthdate": birthdate, "gender": gender}
        params = {key: value for key, value in params.items() if value}
        return [parse_patient(p) for p in self.search("Patient", params, max_results)]

    def get_observations(self, patient_id: str, loinc_codes: Iterable[str] = SEARCH_LOINC_CODES) -> list[dict[str, Any]]:
        codes = ",".join(f"{LOINC}|{code}" for code in loinc_codes)
        return self.search("Observation", {"patient": patient_id, "code": codes, "_sort": "date"})

    def get_medication_requests(self, patient_id: str) -> list[dict[str, Any]]:
        return self.search("MedicationRequest", {"patient": patient_id, "_include": "MedicationRequest:medication"})

    def get_conditions(self, patient_id: str) -> list[dict[str, Any]]:
        return self.search("Condition", {"patient": patient_id})

    def get_patient_record(self, patient_id: str) -> PatientRecord:
        medications = medications_to_df(self.get_medication_requests(patient_id))
        return PatientRecord(
            patient=parse_patient(self.get_patient(patient_id)),
            observations=observations_to_df(self.get_observations(patient_id)),
            medications=medications,
            medication_periods=medication_periods(medications),
            conditions=conditions_to_df(self.get_conditions(patient_id)),
        )

    def find_patients_on_medication(self, rxnorm_code: str, max_patients: int = 50) -> list[str]:
        params = {"code": f"{RXNORM}|{rxnorm_code}", "_elements": "subject"}
        patient_ids: list[str] = []
        for request in self.iter_search("MedicationRequest", params):
            patient_id = reference_id(request.get("subject"))
            if not patient_id or patient_id in patient_ids:
                continue

            patient_ids.append(patient_id)
            if len(patient_ids) == max_patients:
                return patient_ids

        return patient_ids

    def get_cohort_observations(
        self,
        patient_ids: Iterable[str],
        loinc_codes: Iterable[str] = SEARCH_LOINC_CODES,
    ) -> pd.DataFrame:
        frames = [
            observations_to_df(self.get_observations(patient_id, loinc_codes)).assign(patient_id=patient_id)
            for patient_id in patient_ids
        ]
        if not frames:
            return pd.DataFrame(columns=[*OBSERVATION_COLUMNS, "patient_id"])

        return pd.concat(frames, ignore_index=True)


def reference_id(reference: dict[str, Any] | None) -> str | None:
    if not reference or not reference.get("reference"):
        return None

    return reference["reference"].split("/")[-1].lstrip("#")


def first_coding(concept: dict[str, Any] | None, system: str | None = None) -> dict[str, Any]:
    codings = (concept or {}).get("coding", [])
    preferred = [coding for coding in codings if coding.get("system") == system]
    return (preferred or codings or [{}])[0]


def concept_text(concept: dict[str, Any] | None) -> str | None:
    if not concept:
        return None

    return concept.get("text") or first_coding(concept).get("display")


def to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce", format="mixed")


def parse_patient(resource: dict[str, Any]) -> dict[str, Any]:
    names = resource.get("name") or [{}]
    name = next((n for n in names if n.get("use") == "official"), names[0])
    full_name = name.get("text") or " ".join([*name.get("given", []), name.get("family", "")]).strip()
    return {
        "id": resource.get("id"),
        "name": full_name or None,
        "gender": resource.get("gender"),
        "birth_date": resource.get("birthDate"),
        "deceased": bool(resource.get("deceasedBoolean") or resource.get("deceasedDateTime")),
    }


def observation_rows(resource: dict[str, Any]) -> list[dict[str, Any]]:
    effective = (
        resource.get("effectiveDateTime")
        or resource.get("effectivePeriod", {}).get("start")
        or resource.get("issued")
    )
    parts = [resource, *resource.get("component", [])]

    rows = []
    for part in parts:
        quantity = part.get("valueQuantity") or {}
        if quantity.get("value") is None:
            continue

        code = first_coding(part.get("code"), LOINC).get("code")
        metric = LOINC_TO_METRIC.get(code)
        rows.append({
            "observation_id": resource.get("id"),
            "metric": metric,
            "label": LAB_METRICS[metric]["label"] if metric else None,
            "loinc": code,
            "display": concept_text(part.get("code")),
            "value": quantity["value"],
            "unit": quantity.get("unit") or quantity.get("code"),
            "effective": effective,
            "status": resource.get("status"),
        })

    return rows


def observations_to_df(resources: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for resource in resources:
        if resource.get("resourceType") != "Observation" or resource.get("status") == "entered-in-error":
            continue

        rows += observation_rows(resource)

    df = pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)
    df["effective"] = to_datetime(df["effective"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("effective", ignore_index=True)


def medications_to_df(resources: Iterable[dict[str, Any]]) -> pd.DataFrame:
    resources = list(resources)
    medications = {r.get("id"): r for r in resources if r.get("resourceType") == "Medication"}

    rows = []
    for r in resources:
        if r.get("resourceType") != "MedicationRequest" or r.get("status") == "entered-in-error":
            continue

        concept = r.get("medicationCodeableConcept")
        if concept is None:
            reference = r.get("medicationReference") or {}
            medication = medications.get(reference_id(reference), {})
            concept = medication.get("code") or {"text": reference.get("display")}

        validity = r.get("dispenseRequest", {}).get("validityPeriod", {})
        dosage = r.get("dosageInstruction") or [{}]
        reasons = [concept_text(c) for c in r.get("reasonCode", [])]
        rows.append({
            "request_id": r.get("id"),
            "rxnorm": first_coding(concept, RXNORM).get("code"),
            "name": concept_text(concept),
            "status": r.get("status"),
            "intent": r.get("intent"),
            "authored_on": r.get("authoredOn"),
            "period_start": validity.get("start") or r.get("authoredOn"),
            "period_end": validity.get("end"),
            "dosage": dosage[0].get("text"),
            "reason": "; ".join(filter(None, reasons)) or None,
        })

    df = pd.DataFrame(rows, columns=MEDICATION_COLUMNS)
    for column in ["authored_on", "period_start", "period_end"]:
        df[column] = to_datetime(df[column])
    return df.sort_values("period_start", ignore_index=True)


def medication_periods(medications: pd.DataFrame) -> pd.DataFrame:
    if medications.empty:
        return pd.DataFrame(columns=PERIOD_COLUMNS)

    df = medications.assign(
        drug=medications["rxnorm"].fillna(medications["name"]),
        last_date=medications["period_end"].fillna(medications["period_start"]),
        is_active=medications["status"] == "active",
    )
    periods = df.groupby("drug").agg(
        rxnorm=("rxnorm", "first"),
        name=("name", "first"),
        start=("period_start", "min"),
        end=("last_date", "max"),
        active=("is_active", "any"),
        request_count=("request_id", "count"),
    )
    periods.loc[periods["active"], "end"] = pd.NaT
    return periods.sort_values("start").reset_index(drop=True)[PERIOD_COLUMNS]


def conditions_to_df(resources: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in resources:
        if r.get("resourceType") != "Condition":
            continue

        coding = first_coding(r.get("code"))
        rows.append({
            "condition_id": r.get("id"),
            "code": coding.get("code"),
            "system": coding.get("system"),
            "name": concept_text(r.get("code")),
            "clinical_status": first_coding(r.get("clinicalStatus")).get("code"),
            "onset": r.get("onsetDateTime") or r.get("onsetPeriod", {}).get("start"),
            "abatement": r.get("abatementDateTime") or r.get("abatementPeriod", {}).get("start"),
            "recorded": r.get("recordedDate"),
        })

    df = pd.DataFrame(rows, columns=CONDITION_COLUMNS)
    for column in ["onset", "abatement", "recorded"]:
        df[column] = to_datetime(df[column])
    return df.sort_values("onset", ignore_index=True)
