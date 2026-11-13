from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional

from services import industries
from services.countries import DEFAULT_COUNTRY_CODE, is_known_country, normalize_code
from services.industries import DEFAULT_INDUSTRY
from services.search_profiles import CATEGORY_PROFILES, CITY_PATTERN, canonical_city


class DiscoveryRequest(BaseModel):
    """Search for businesses in a country. industry and subcategory come from industries.json.

    country_code is an ISO 3166-1 alpha-2 code (Pakistan is PK). The country name is looked up on the server.
    The city is either city_id (a city picked from the city database, checked against country_code on the server)
    or city (a name typed by the user, used exactly as typed after checks). Google Places is not involved in city
    lookup.
    category is the older restaurant field. It is still accepted, and it means the same as subcategory when the
    industry is Restaurants & Food.
    """
    country_code: str = Field(default=DEFAULT_COUNTRY_CODE, min_length=2, max_length=2)
    city: Optional[str] = Field(default=None, max_length=60)
    city_id: Optional[int] = Field(default=None, ge=1)
    industry: str = Field(default=DEFAULT_INDUSTRY, max_length=40)
    subcategory: Optional[str] = Field(default=None, max_length=40)
    category: str = Field(default="all", max_length=40)
    limit: int = Field(default=10, ge=1, le=60)

    @field_validator("country_code")
    @classmethod
    def _known_country(cls, value: str) -> str:
        code = normalize_code(value)
        if not is_known_country(code):
            raise ValueError("Unknown country code. Choose a country from the list.")
        return code

    @model_validator(mode="after")
    def _resolve_city_and_subcategory(self):
        # A city picked from the database is checked against the country in the route, which also reads its name.
        # A typed city must be a plain name.
        if self.city_id is None:
            cleaned = " ".join((self.city or "").split())
            if len(cleaned) < 2:
                raise ValueError("Enter a city name.")
            if not CITY_PATTERN.fullmatch(cleaned):
                raise ValueError("City may contain only letters, spaces, hyphens, apostrophes and periods.")
            self.city = canonical_city(cleaned)
        if not industries.is_known(self.industry):
            raise ValueError("Unknown or disabled industry.")
        if self.subcategory is None:
            if self.industry == DEFAULT_INDUSTRY:
                if self.category not in CATEGORY_PROFILES:
                    raise ValueError("Unknown cuisine category.")
                self.subcategory = self.category
            else:
                self.subcategory = industries.default_subcategory(self.industry)["key"]
        if industries.get_subcategory(self.industry, self.subcategory) is None:
            raise ValueError("Unknown subcategory for this industry.")
        return self


class RestaurantResponse(BaseModel):
    id: int
    place_id: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str
    industry: Optional[str] = None
    subcategory: Optional[str] = None
    industry_fields: dict = Field(default_factory=dict)
    website_features: dict = Field(default_factory=dict)
    # Phase 3
    website_status: Optional[str] = "unknown"
    ordering_status: Optional[str] = "unknown"
    ordering_evidence: Optional[list[str]] = []
    website_checked_at: Optional[str] = None
    website_error: Optional[str] = None
    # Phase 4
    contact_email: Optional[str] = None
    contact_email_source: Optional[str] = None
    contact_email_status: Optional[str] = "unverified"
    contact_discovered_at: Optional[str] = None
    # Email verification (Phase 17)
    contact_email_classification: Optional[str] = None
    contact_email_reasons: Optional[list[str]] = []
    contact_email_mx_state: Optional[str] = None
    contact_email_checked_at: Optional[str] = None
    contact_email_reviewed_at: Optional[str] = None
    contact_email_review_decision: Optional[str] = None
    contact_email_review_note: Optional[str] = None
    lead_score: Optional[int] = None
    lead_status: Optional[str] = "new"
    lead_reason: Optional[str] = None
    lead_qualified_at: Optional[str] = None
    opted_out: Optional[int] = 0
    listing_expired: Optional[int] = 0
    created_at: str


class BatchCheckRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


class BatchContactRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


class BatchQualifyRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


class EmailReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=200)


class ConversationDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(confirm|dismiss)$")
