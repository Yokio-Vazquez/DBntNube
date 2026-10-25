import os
from datetime import datetime
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

class EventWriteBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: int = Field(gt=0, strict=True)
    event_key: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    occurred_at: str
    source: str = Field(min_length=1)

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as error:
            raise ValueError(
                "occurred_at debe usar UTC en formato YYYY-MM-DDTHH:MM:SSZ"
            ) from error
        return value


class EventDocumentV2(EventWriteBase):
    schema_version: Literal[2] = Field(default=2, alias="schemaVersion")


class EventDocumentV3(EventWriteBase):
    schema_version: Literal[3] = Field(default=3, alias="schemaVersion")
    platform: Literal["pc", "console", "mobile", "unknown"]
    metadata: dict = Field(default_factory=dict)


def configured_event_model():
    version = os.getenv("EVENT_WRITE_VERSION", "2")
    if version not in {"2", "3"}:
        raise ValueError("EVENT_WRITE_VERSION debe ser 2 o 3")
    return EventDocumentV3 if version == "3" else EventDocumentV2


load_dotenv()
# Restart the application after changing the environment flag.
EventDocument = configured_event_model()
