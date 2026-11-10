"""What `respond.offered` logs of the tools a turn begins with: their names, how many they are and the sources they come
from. A log field is cut, so the count and the sources are what survive a long list of names; `unavailable` when the
catalogue could not be reached."""

from ..tools.tools import Catalogue


def fields(catalogue: Catalogue | None) -> dict[str, object]:
    if catalogue is None:
        return {"tools": "unavailable", "tool_count": "unavailable", "sources": "unavailable"}
    return {"tools": ",".join(t.name for t in catalogue.specs), "tool_count": len(catalogue.specs),
            "sources": ",".join(catalogue.sources)}
