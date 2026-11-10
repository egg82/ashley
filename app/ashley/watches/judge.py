"""The pure judge: one read of a watch and the watch give exactly one check (`decisions.md`, "Watches wake her when
what a read returns changes, until a condition or a time"). It compares against the baseline, which moves only when
the watch wakes her, so a change `when` does not hold for stays pending."""

from ..criteria import condition
from .diff import diff
from .model import Baseline, Check, Failed, Later, Quiet, Read, ReadFailed, Watch, Woke


def judge(read: Read, watch: Watch) -> Check:
    """`Failed` for a failed read, never read as an item gone; `Baseline` for the first successful read; otherwise the
    diff against the baseline: `Woke` when `when` holds for the changes, else `Quiet`. `ends` is whether `until` holds
    for them, and it ends the watch either way. A `Later` read is the `Later` check, whatever the baseline."""
    if isinstance(read, Later):
        return read
    if isinstance(read, ReadFailed):
        return Failed(read.reason)
    if watch.baseline is None:
        return Baseline(read)
    changes = diff(watch.baseline, read)
    ends = watch.until is not None and condition.satisfied(watch.until, changes)
    if condition.satisfied(watch.when, changes):
        return Woke(read, changes, ends)
    return Quiet(ends)
