"""The wire models of `/api/wakes`."""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

_SLUG = r"^[a-z][a-z0-9_]{0,63}$"


class WakeRequest(BaseModel):
    """One wake from Home Assistant, as `rest_command.ashley_wake` sends it: structured fields only, so free text
    cannot arrive here. `event_id` is HA's id for this run of the automation (`{{ context.id }}`), which makes a
    retry the same wake; `event` the slug a wake rule answers; `who` the `person.*` entity it is about; `what` a slug
    of what it concerns; `when` when it happened, with its offset (now when absent)."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128, pattern=r"^\S+$")
    event: str = Field(pattern=_SLUG)
    who: str | None = Field(default=None, pattern=r"^person\.[a-z0-9_]+$")
    what: str | None = Field(default=None, pattern=_SLUG)
    when: AwareDatetime | None = None


class WakeAccepted(BaseModel):
    """The wake's id, and `duplicate` when its event id had arrived before and nothing new was stored."""

    id: int
    duplicate: bool
