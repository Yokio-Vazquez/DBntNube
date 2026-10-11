from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventDocumentBase(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    game_id: int
    event_key: str
    event_type: str
    occurred_at: str
    source: str


class EventV1(EventDocumentBase):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")


class EventV2(EventDocumentBase):
    schema_version: Literal[2] = Field(alias="schemaVersion")


class UnsupportedEventVersion(ValueError):
    pass


def normalize_event(document: Mapping[str, Any]) -> EventV1 | EventV2:
    version = document.get("schemaVersion", document.get("schema_version", 1))
    if version == 1:
        return EventV1.model_validate(document)
    if version == 2:
        return EventV2.model_validate(document)
    raise UnsupportedEventVersion(f"Unsupported event schema version: {version}")