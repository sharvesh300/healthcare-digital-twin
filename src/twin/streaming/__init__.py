"""The live twin: device events -> ingestion -> TimescaleDB -> twin state -> event bus -> WebSocket.

  events     sensor events as devices send them (POST /ingest/events)
  state      PatientTwinState and the pure rules that update it
  manager    PatientTwinStateManager: load, apply, update, publish
  bus        in-process publish/subscribe, one topic per patient
  store      database side: state loading, transitions, device pairing, ingestion
  simulator  `twin simulate-stream`: replays recorded data as live devices
"""
