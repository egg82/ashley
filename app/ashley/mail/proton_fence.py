"""The singleton's decision about Bridge's pod: given the record's holder and what its pod is doing in this cluster, what
to do next. Pure, so the fence is read in one place (`decisions.md`, "Exactly one Bridge, fenced by the epoch")."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from .proton_bridge import Holder

PodState = Literal["running", "stale", "ended", "absent"]
"""What the holder's pod is in this cluster: `stale` is running another image than the one pinned; `ended` is a terminal
phase, so its containers are not running; `absent` is none by that name, or one being deleted, whose containers may
still be."""


class Step(Enum):
    ADOPT = "adopt"
    RAISE = "raise"
    WAIT = "wait"
    MAKE = "make"
    REPLACE = "replace"


@dataclass(frozen=True)
class Decision:
    step: Step
    wait_s: float = 0.0
    reason: str = ""


def decide(holder: Holder, site: str, pod: PodState, fence_s: float, fence_margin_s: float) -> Decision:
    """The next step for the process holding the lease at `site`.

    - `ADOPT`: the current epoch's pod is this site's, running and heard within `fence_s`; leave it.
    - `REPLACE`: this site's pod ended; its keeper is gone, so the next goes up under a new epoch with no fence wait.
    - `MAKE` / `WAIT`: this site raised the epoch and has no pod yet; the pod is made once the older epoch's last sign of
      life is `fence_s + fence_margin_s` old (by the database's clock), the time a cut-off keeper takes to stop itself.
    - `RAISE`: anything else (no epoch yet, a pod of another site, a pod running another image, a pod not heard within
      `fence_s`, a pod gone): raise the epoch, which retires every older pod at its next heartbeat and makes the new one
      only after the fence wait. A stale pod is never `REPLACE`d, since its keeper is still running. `reason` says which."""
    mine = holder.epoch > 0 and holder.site == site
    if mine and holder.pod is None:
        needed = fence_s + fence_margin_s
        age = holder.alive_age_s
        if age is None or age >= needed:
            return Decision(Step.MAKE)
        return Decision(Step.WAIT, needed - age)
    if mine and pod == "ended":
        return Decision(Step.REPLACE, reason="ended")
    if mine and pod == "stale":
        return Decision(Step.RAISE, reason="image")
    if mine and pod == "running" and holder.alive_age_s is not None and holder.alive_age_s < fence_s:
        return Decision(Step.ADOPT)
    if holder.epoch == 0:
        return Decision(Step.RAISE, reason="first")
    if not mine:
        return Decision(Step.RAISE, reason="other_site")
    return Decision(Step.RAISE, reason="gone" if pod == "absent" else "unheard")
