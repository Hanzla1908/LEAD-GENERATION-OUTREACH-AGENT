import re

from pydantic import BaseModel, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class CampaignRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    restaurant_ids: list[int] = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("Campaign name needs at least 2 characters.")
        return cleaned

    @field_validator("restaurant_ids")
    @classmethod
    def _dedupe_ids(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class ApproveSendingRequest(BaseModel):
    draft_ids: list[int] = Field(min_length=1, max_length=200)

    @field_validator("draft_ids")
    @classmethod
    def _dedupe_ids(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class SuppressionRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    reason: str = Field(default="manual", max_length=100)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not EMAIL_PATTERN.match(cleaned):
            raise ValueError("Enter a valid email address.")
        return cleaned
