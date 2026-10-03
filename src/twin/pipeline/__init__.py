"""Pipeline steps, in run order:

  patients   match       pair participants with Synthea patients (matching.py), create core.patient
  ehr        load-ehr    prune unlinked patients from FHIR, load matched Synthea bundles
  sensors    load-sensors devices, meals and readings into the hypertables
  reconcile  reconcile   real labs, tags and race/ethnicity into FHIR; HbA1c vs GMI
  summaries  summarize   Devices and daily CGM / heart-rate Observations into FHIR
"""
