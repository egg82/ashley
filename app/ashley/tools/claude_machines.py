"""`claude_machines`: each of the person's machines by the label and description they gave it and what the machine can
do now (`ashley.herdr.model.MachineReport`), so a job that needs a GPU, an instrument or a tool goes to the machine that
has it. The description is the household's own text. The report is read live from the bridge and carries device-made
strings (a USB product name), so the tool's result is outside words (`outside=True`); a call that names no machine
reads them all, and a machine whose report cannot be read is listed without one, saying why."""

import logging

from .. import logs, services
from ..herdr.bridge import Bridge
from ..herdr.machines import Machine
from ..herdr.model import BridgeFailed, MachineReport

log = logging.getLogger("ashley.tools")


def wire(r: MachineReport) -> dict[str, object]:
    """The report as she reads it: a field the bridge could not read is null, not zero."""
    return {
        "hostname": r.hostname, "os": r.os, "kernel": r.kernel,
        "cpu": {"model": r.cpu_model, "cores": r.cpu_cores},
        "memory_mb": {"total": r.memory_total_mb, "available": r.memory_available_mb},
        "gpus": None if r.gpus is None else [{"model": g.model, "memory_mb": g.memory_mb} for g in r.gpus],
        "session_busy": r.busy, "tools": list(r.tools),
        "usb": None if r.usb is None else [{"id": u.id, "product": u.product} for u in r.usb]}


async def row(machine: Machine) -> dict[str, object]:
    shown: dict[str, object] = {"machine": machine.label, "description": machine.description}
    try:
        shown["report"] = wire(await services.get(Bridge).machine(machine.access))
    except BridgeFailed as e:
        logs.info(log, "claude_code.machine_report_failed", connection=machine.connection_id, reason=e.reason)
        shown["report"] = None
        shown["report_unavailable"] = {"not_found": "its bridge is too old to report",
                                       "herdr_unavailable": "it did not answer"}.get(e.reason, e.reason)
    return shown
