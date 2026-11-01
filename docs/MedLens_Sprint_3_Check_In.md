# MedLens: Sprint 3 Check-In

Arnav Mittal & Allen Siu

## Accomplishments

Week 1 (Oct 26 – Nov 1) of the implementation plan is complete, and part of the Week 2 work of etrieving and parsing medication periods and observation data was finished early.

**Arnav Mittal** (estimated hours: 10)

- Set up the GitHub repository with the project structure and hosting on Streamlit Community Cloud.
- Built the FHIR client (`src/services/FHIR_client.py`):
  - Read-only access to the SMART R4 sandbox, with the server switchable to a local Synthea
    server through `FHIR_BASE_URL`.
  - Retrieves Patient, MedicationRequest, Observation, and Condition resources, follows
    paginated search results, and retries when the server is busy.
  - Parses each resource type into a pandas DataFrame for the views to use.
  - Maps the eight tracked metrics (blood pressure, A1c, glucose, potassium, creatinine, LDL,
    HDL, weight) to their LOINC codes and splits blood pressure panels into systolic and
    diastolic readings.
  - Combines repeated prescriptions of the same drug into a single on-medication period
    (an early start on Week 2).
  - Finds patients by medication (RxNorm code), groundwork for the Week 5 comparison view.

**Allen Siu** (estimated hours: 10)

- Built the sidebar component: patient/clinician toggle, FHIR server selection with a
  connection status indicator, patient search by name or ID, a list of demo patients, and a
  focus filter for cholesterol, high blood pressure, and diabetes.
- Built the header component: patient name, gender, age, and date of birth, plus summary
  numbers for active medications, active conditions, lab results, and most recent lab date,
  with wording that changes between the patient and clinician views.
- Added placeholder tabs for the Timeline, Scorecard, Safety Panel, and Comparison views.
- Tested the client and app against the live SMART R4 sandbox.

**Both**

- Finalized the Sprint 2 planning document with our mentor.

## Challenges

- **Medication periods are approximate.** The MedicationRequest records in the SMART sandbox
  have no end dates; they only have a prescribed date and a status (active or stopped). We
  estimate each drug's period as running from its first prescription to its last, and treat
  it as ongoing if any prescription is still active. The before/after comparisons in the
  Scorecard (Week 3) depend on these dates, so their accuracy is limited by this.
- **Sparse and dated patient histories.** Many patients in the sandbox have little lab or
  medication history, and the most recent labs for the patients we tested are from 2020–2021.
  To get around this in the sidebar, the default patient list only shows patients prescribed
  simvastatin, hydrochlorothiazide, or metformin, who tend to have relevant history. This
  supports the risk noted in our plan, and we may still need to generate Synthea test data
  for the timeline and comparison views.

No delays to the implementation plan so far.

## Sprint Plans

Scheduled tasks for the next two weeks, from our implementation plan:

**Week 2 (Nov 2 – Nov 8)**

- Finish the remaining FHIR request and parsing work. Most of it is already done, so this
  week mainly involves checking the medication period estimates against more patients.
- Build the Timeline view with goal-range bands and test it with demo patients.
- Generate Synthea test data if the sandbox patients prove too sparse.

**Week 3 (Nov 9 – Nov 15)**

- Build the clinical rules CSV from credible public sources.
- Implement before/after and range calculations with verdict badges.
- Implement regression analysis and response charts based on before/after periods.
- Record the demo video and review it with our mentor.

Because medication end dates are estimated, we plan to confirm with our mentor that this
approach is acceptable for the before/after analysis before building the Scorecard.
