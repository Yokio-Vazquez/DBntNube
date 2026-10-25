from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_VERSIONS = {1, 2, 3}
# Internal storage marker: distinguishes implicit v1 from explicit schemaVersion=1.
VERSION_PRESENCE_FIELD = "migratedVersionExplicit"
V3_FIELDS = {"platform", "metadata", "migratedFrom", VERSION_PRESENCE_FIELD}


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


class EventV3(EventDocumentBase):
    schema_version: Literal[3] = Field(default=3, alias="schemaVersion")
    platform: Literal["pc", "console", "mobile", "unknown"] = "unknown"
    metadata: dict = Field(default_factory=dict)
    migrated_from: Literal[1, 2] | None = Field(default=None, alias="migratedFrom")


class UnsupportedEventVersion(ValueError):
    pass


def detect_version(doc: Mapping) -> int:
    version = doc.get("schemaVersion", doc.get("schema_version", 1))
    # DynamoDB represents numeric attributes as Decimal; strings/bools are invalid.
    if (
        isinstance(version, bool)
        or not isinstance(version, (int, Decimal))
        or version not in SUPPORTED_VERSIONS
    ):
        raise UnsupportedEventVersion(f"Unsupported event schema version: {version}")
    return int(version)


def normalize_event(document: Mapping[str, Any]) -> EventV1 | EventV2 | EventV3:
    version = detect_version(document)
    return {1: EventV1, 2: EventV2, 3: EventV3}[version].model_validate(document)


def upcast_to_v3(doc: Mapping) -> dict:
    version = detect_version(doc)
    normalize_event(doc)  # Validate mandatory fields before producing a document.
    result = deepcopy(dict(doc))
    if version == 3:
        return result
    if V3_FIELDS.intersection(doc):
        raise ValueError("Legacy document contains reserved v3/migration fields")
    if "schema_version" in doc:
        raise ValueError("Migration requires the storage key schemaVersion, not schema_version")
    result.update(schemaVersion=3, platform="unknown", metadata={}, migratedFrom=version)
    if version == 1:
        result[VERSION_PRESENCE_FIELD] = "schemaVersion" in doc
    return result


def downcast_from_v3(doc: Mapping) -> dict:
    if detect_version(doc) != 3:
        raise ValueError("Rollback requires a v3 document")
    normalize_event(doc)
    original = doc.get("migratedFrom")
    if isinstance(original, bool) or original not in (1, 2):
        raise ValueError("Native v3 documents have no original version to restore")
    explicit = doc.get(VERSION_PRESENCE_FIELD, False)
    if not isinstance(explicit, bool):
        raise ValueError("Invalid migratedVersionExplicit marker")
    result = deepcopy(dict(doc))
    for key in V3_FIELDS:
        result.pop(key, None)
    result.pop("schema_version", None)
    if original == 1 and not explicit:
        result.pop("schemaVersion", None)
    else:
        result["schemaVersion"] = int(original)
    return result


def project(doc: Mapping, target: int) -> dict:
    if (
        isinstance(target, bool)
        or not isinstance(target, int)
        or target not in SUPPORTED_VERSIONS
    ):
        raise UnsupportedEventVersion(f"Unsupported target event schema version: {target}")
    version = detect_version(doc)
    normalize_event(doc)
    if target == 3:
        return upcast_to_v3(doc)
    result = deepcopy(dict(doc))
    if version == 3:
        for key in V3_FIELDS:
            result.pop(key, None)
    result.pop("schema_version", None)
    result["schemaVersion"] = target
    return result
