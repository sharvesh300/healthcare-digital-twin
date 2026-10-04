"""Sensor events as a device sends them to `POST /ingest/events`.

Values are in the canonical unit: mg/dL for glucose, ref.wearable_metric.unit for wearable
metrics. Times must carry a UTC offset.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from twin.models.base import SleepStage


class GlucoseEvent(BaseModel):
    kind: Literal["glucose"] = "glucose"
    device_id: int
    time: AwareDatetime
    glucose_mg_dl: int = Field(ge=20, le=600)


class WearableEvent(BaseModel):
    kind: Literal["wearable"] = "wearable"
    device_id: int
    time: AwareDatetime
    metric: str = Field(description="ref.wearable_metric.code, e.g. heart_rate, steps, spo2")
    value: float


class SleepEvent(BaseModel):
    kind: Literal["sleep"] = "sleep"
    device_id: int
    time: AwareDatetime = Field(description="start of the sleep stage")
    stage: SleepStage
    until: AwareDatetime

    @model_validator(mode="after")
    def _positive(self) -> SleepEvent:
        if self.until <= self.time:
            raise ValueError("until must be after time")
        return self


SensorEvent = Annotated[GlucoseEvent | WearableEvent | SleepEvent, Field(discriminator="kind")]


class EventBatch(BaseModel):
    events: list[SensorEvent] = Field(max_length=5000)
