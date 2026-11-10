"""`python -m ashley.referee hold [DURATION] | release | status`: the fail-back maintenance switch, run where ETCD_*
are set (`kubectl exec deploy/app` on either site). DURATION is `<n>m`, `<n>h` or `<n>d`; the default is 4h."""

import asyncio
import logging
import re
import sys
from datetime import timedelta

from .. import logs
from ..settings import Settings, from_env
from .etcd_gateway import EtcdTls, EtcdUnavailable
from .hold import EtcdHold

USAGE = "usage: python -m ashley.referee hold [DURATION like 30m, 4h, 2d] | release | status"
DEFAULT = timedelta(hours=4)
_UNITS = {"m": 60, "h": 3600, "d": 86400}
log = logging.getLogger("ashley.referee.hold")


def parse_duration(text: str) -> timedelta | None:
    """`30m`, `4h`, `2d` as a timedelta; None for anything else, zero included."""
    m = re.fullmatch(r"([1-9][0-9]*)([mhd])", text)
    return timedelta(seconds=int(m.group(1)) * _UNITS[m.group(2)]) if m else None


async def run(hold: EtcdHold, argv: list[str]) -> int:
    """Carry out one command and print its outcome; the exit status: 0 done, 1 etcd unreachable, 2 usage."""
    command, rest = (argv[0], argv[1:]) if argv else ("", [])
    duration = parse_duration(rest[0]) if command == "hold" and rest else DEFAULT
    if command not in ("hold", "release", "status") or len(rest) > (1 if command == "hold" else 0) or duration is None:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        if command == "hold":
            until = await hold.set(duration)
            logs.info(log, "failback.hold_set", seconds=int(duration.total_seconds()))
            print(f"fail-back held until {until.isoformat(timespec='seconds')}")
        elif command == "release":
            existed = await hold.release()
            logs.info(log, "failback.hold_released", existed=existed)
            print("fail-back released" if existed else "fail-back was not held")
        else:
            until = await hold.until()
            print("fail-back not held" if until is None else f"fail-back held until {until.isoformat(timespec='seconds')}")
    except EtcdUnavailable as e:
        print(f"etcd unreachable ({e})", file=sys.stderr)
        return 1
    return 0


def hold_for(settings: Settings) -> EtcdHold | None:
    """The switch on this process's etcd member; None when ETCD_URL is unset."""
    if not settings.etcd_url:
        return None
    tls = EtcdTls.for_url(settings.etcd_url, settings.etcd_ca_file, settings.etcd_cert_file, settings.etcd_key_file)
    return EtcdHold(settings.etcd_url, tls)


def main(argv: list[str]) -> int:
    logs.setup()
    hold = hold_for(from_env())
    if hold is None:
        print("ETCD_URL is unset: there is no referee to hold", file=sys.stderr)
        return 2
    return asyncio.run(run(hold, argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
