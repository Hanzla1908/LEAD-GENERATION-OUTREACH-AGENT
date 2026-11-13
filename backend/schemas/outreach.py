from pydantic import BaseModel, Field
from typing import Optional


class DraftGenerateRequest(BaseModel):
    restaurant_id: int
    campaign: str = Field(default="default", max_length=100)


class RegenerateRequest(BaseModel):
    """Optional reviewer instructions for a new draft. They shape the wording only; facts come from the record."""
    instructions: str = Field(default="", max_length=500)


class DraftUpdateRequest(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=200)
    body: Optional[str] = Field(default=None, max_length=3000)


class DraftStatusRequest(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")


class DraftResponse(BaseModel):
    id: int
    restaurant_id: int
    campaign: str
    subject: str
    body: str
    status: str
    angle: Optional[str] = None
    campaign_id: Optional[int] = None
    created_at: str
    updated_at: str
    edited_at: Optional[str] = None
    sent: bool = False
