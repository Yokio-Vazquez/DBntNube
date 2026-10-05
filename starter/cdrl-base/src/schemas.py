from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

class EventDocument(BaseModel):
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