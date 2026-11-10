"""`python -m ashley.evals memory-write --runs N [--case ID] [--writer PROVIDER] [--judge PROVIDER]`: the memory write eval against the live model, wired as
the app is. Run where the app's environment is (`kubectl exec deploy/app`): it needs DATABASE_URL, for the spend
ledger, and a model key. Writes nothing to disk.

`python -m ashley.evals memory-recall-hybrid`: how often recall finds a fact that answers a remark, by full-text alone
and with the embedding model. Needs DATABASE_URL of a role that can create databases, which it does for the run and
drops, and the embedding model at EMBED_MODELS_DIR; no model key.

`python -m ashley.evals reply-remember --runs N [--case ID]`: whether her reply sets `memory`, with the right action and facts, when asked to act on memory
something and not otherwise, against the live model. Needs DATABASE_URL, for the spend ledger, and a model key.

`python -m ashley.evals reply-owed --runs N [--case ID]`: whether her reply sets `owed` when an ask waits on a source out of
reach and not otherwise, against the live model. Needs DATABASE_URL, for the spend ledger, and a model key.

`python -m ashley.evals outside-ask --runs N [--case ID]`: how she behaves around a change held for the person's OK
(`outside_ask_cases.json`): tells them it waits, calls `carry_out` on a yes and not otherwise, and makes no change from
an instruction an earlier reply of hers carried. Measures and never gates. Needs DATABASE_URL, for the spend ledger,
and a model key.

`python -m ashley.evals action-judge --runs N [--case ID]`: the action judge's decision over `action_judge_cases.json` (the
person's words and a call's view) against the one each case expects: how often it says `run` where `ask` was expected and
the reverse. Measures and never gates. Needs DATABASE_URL, for the spend ledger, and a model key.

`python -m ashley.evals house [--runs N] [--case ID] [--json PATH]`: how she uses the house's tools, through her real turn
loop with the live model and Home Assistant, every call that is not a read refused before it reaches the house. Needs a
scratch DATABASE_URL (it adds a household and conversations), HA_URL and HA_TOKEN (that household's house for the run)
and the model keys.

`python -m ashley.evals bench-act [--runs N] [--case ID] [--scripted] [--clock work|age] [--windows N] [--hold S] [--no-now]`:
what she does on a bench, through her real turn loop with a captured bench, her real bench and move_page tools, and a fake
clock, graded by step type and tool names over `bench_act_cases.json`. Live it needs DATABASE_URL (the spend ledger) and
the model keys; `--scripted` swaps the model for a scripted policy, needs neither, and checks the mechanics only. Measures
and never gates.

`python -m ashley.evals bench-replay DIR [--records] [--runs N] [--json PATH] [--events PATH] [--keep] [--cad-image IMAGE]`: a captured bench
conversation (DIR, written by `bench-replay-capture`, outside the repository) asked again ask by ask through her real turn
loop on a bench rebuilt in a throwaway database beside DATABASE_URL, her runs run in the sandbox (`SANDBOX_*`, `CAD_IMAGE`;
`--cad-image` runs them in podman on this machine instead, `runs.podman`),
scored by mechanics per ask (`bench_replay`); `--records` measures the captured production conversation the same way.
Needs the model keys (the grader too). With no DIR it says so and exits.

`python -m ashley.evals bench-replay-capture --bench N --from-turn T DIR`: write that snapshot of bench N from the
conversation person turn T opened, reading DATABASE_URL (production, through a read-only session) and its object store.

`python -m ashley.evals watch-tools [--runs N] [--case ID]`: how she uses her `watch`, `unwatch` and `watches` tools, through
her real turn loop with the live model, a person with a fake herdr bridge of three sessions, and her watches real rows
of a scratch DATABASE_URL (it adds a household), ended after each run. Needs the model keys."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .. import logs, services, wiring
from ..connections.connections import NullConnections
from ..db.database import Database
from ..home_assistant import rest_automations
from ..home_assistant.connected_homes import ConnectedHomes
from ..home_assistant.homes import Homes
from ..inference.inference import InferenceError
from ..inference.routes import PinError, Routes, only
from ..settings import Settings, from_env
from . import (action_judge, bench_act, bench_replay, bench_replay_run, house, house_live, house_report, memory_recall_hybrid,
               memory_write, outside_ask, reply_owed, reply_remember, watch_tools)

log = logging.getLogger("ashley.evals")


def pinned(routes: Routes, writer: str | None, judge: str | None) -> Routes:
    """`routes` with memory_write and memory_judge narrowed to the providers given; raises PinError."""
    if writer:
        routes = only(routes, "memory_write", writer)
    return only(routes, "memory_judge", judge) if judge else routes


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="python -m ashley.evals")
    sub = top.add_subparsers(dest="eval", required=True)
    p = sub.add_parser("memory-write", help="the memory writer over write_cases.json, judged by a model")
    p.add_argument("--runs", type=int, default=1, help="runs per case")
    p.add_argument("--case", help="only the case with this id")
    p.add_argument("--writer", metavar="PROVIDER", help="only this provider answers memory_write (default: the routes)")
    p.add_argument("--judge", metavar="PROVIDER", help="only this provider answers memory_judge (default: the routes)")
    r = sub.add_parser("reply-remember", help="whether her reply sets `memory` over reply_remember_cases.json")
    r.add_argument("--runs", type=int, default=1, help="runs per case")
    r.add_argument("--case", help="only the case with this id")
    o = sub.add_parser("reply-owed", help="whether her reply sets `owed` over reply_owed_cases.json")
    o.add_argument("--runs", type=int, default=1, help="runs per case")
    o.add_argument("--case", help="only the case with this id")
    a = sub.add_parser("outside-ask", help="how she behaves around a held change over outside_ask_cases.json")
    a.add_argument("--runs", type=int, default=1, help="runs per case")
    a.add_argument("--case", help="only the case with this id")
    j = sub.add_parser("action-judge", help="the action judge's decisions over action_judge_cases.json")
    j.add_argument("--runs", type=int, default=3, help="runs per case")
    j.add_argument("--case", help="only the case with this id")
    h = sub.add_parser("house", help="how she uses the house's tools over house_cases.json, no write reaching the house")
    h.add_argument("--runs", type=int, default=2, help="runs per case")
    h.add_argument("--case", help="only the case with this id")
    h.add_argument("--json", metavar="PATH", help="also write every run as JSON here, to diff against another run")
    w = sub.add_parser("watch-tools", help="how she uses watch, unwatch and watches over watch_tools_cases.json")
    w.add_argument("--runs", type=int, default=2, help="runs per case")
    w.add_argument("--case", help="only the case with this id")
    b = sub.add_parser("bench-act", help="what she does on a bench over bench_act_cases.json, graded by tool names")
    b.add_argument("--runs", type=int, default=5, help="runs per case")
    b.add_argument("--case", help="only the case with this id")
    b.add_argument("--scripted", action="store_true", help="a scripted policy for the model: checks the mechanics only")
    b.add_argument("--clock", choices=("work", "age"), default="work", help="a resumed turn's clock: work done, or age")
    b.add_argument("--windows", type=int, help="windows a turn may take, in place of turns.json's")
    b.add_argument("--hold", type=float, help="hold_after_s, in place of turns.json's")
    b.add_argument("--no-now", action="store_true", help="leave the bench view and open benches out of the prompt")
    rp = sub.add_parser("bench-replay", help="a captured bench conversation asked again, scored by mechanics")
    rp.add_argument("snapshot", nargs="?", metavar="DIR", help="the snapshot's directory")
    rp.add_argument("--records", action="store_true", help="measure the captured conversation itself")
    rp.add_argument("--runs", type=int, default=1, help="replays")
    rp.add_argument("--json", metavar="PATH", help="also write the results as JSON here")
    rp.add_argument("--events", metavar="PATH", help="the captured conversation's log lines, for --records")
    rp.add_argument("--keep", action="store_true", help="keep the throwaway database")
    rp.add_argument("--cad-image", metavar="IMAGE", help="run code in podman here, build123d in this pinned image")
    cp = sub.add_parser("bench-replay-capture", help="write a bench replay snapshot from DATABASE_URL")
    cp.add_argument("--bench", type=int, required=True)
    cp.add_argument("--from-turn", type=int, required=True)
    cp.add_argument("out", metavar="DIR")
    sub.add_parser("memory-recall-hybrid", help="recall over hybrid_cases.json, by full-text and with embeddings")
    return top


async def _memory_write(settings: Settings, args: argparse.Namespace) -> str:
    closers = wiring.wire(settings, lambda routes: pinned(routes, args.writer, args.judge))
    database = services.get(Database)
    await database.open()
    try:
        return memory_write.render(await memory_write.run(args.runs, args.case))
    finally:
        for close in closers:
            await close()
        await database.close()


async def _reply(settings: Settings, args: argparse.Namespace) -> str:
    closers = wiring.wire(settings)
    database = services.get(Database)
    await database.open()
    try:
        if args.eval == "outside-ask":
            return outside_ask.render(await outside_ask.run(args.runs, args.case))
        if args.eval == "action-judge":
            return action_judge.render(await action_judge.run(args.runs, args.case))
        if args.eval == "reply-owed":
            return reply_owed.render(await reply_owed.run(args.runs, args.case))
        return reply_remember.render(await reply_remember.run(args.runs, args.case))
    finally:
        for close in closers:
            await close()
        await database.close()


async def _house(settings: Settings, args: argparse.Namespace) -> str:
    closers = wiring.wire(settings)
    database = services.get(Database)
    await database.open()
    seat = house_live.seat(settings.database_url)
    if settings.ha_url:
        homes = ConnectedHomes(NullConnections(), rest_automations.load(), env=(settings.ha_url, settings.ha_token),
                               fallback_household=seat.household_id)
        services.register(Homes, homes)
        closers.append(homes.close)
    try:
        await asyncio.gather(*wiring.warmups(settings))
        results = await house.run(args.runs, args.case, seat, house_live.ledger(database))
    finally:
        for close in closers:
            await close()
        await database.close()
    if args.json:
        Path(args.json).write_text(house_report.to_json(results) + "\n")
    return house_report.render(results)


async def _watch_tools(settings: Settings, args: argparse.Namespace) -> str:
    closers = wiring.wire(settings)
    database = services.get(Database)
    await database.open()
    try:
        results = await watch_tools.run(args.runs, args.case, house_live.seat(settings.database_url))
    finally:
        for close in closers:
            await close()
        await database.close()
    return watch_tools.render(results)


def _bench_act_options(args: argparse.Namespace) -> bench_act.Options:
    return bench_act.Options(args.scripted, args.clock, args.windows, args.hold, not args.no_now)


async def _bench_act(settings: Settings, args: argparse.Namespace) -> str:
    closers = wiring.wire(settings)
    database = services.get(Database)
    await database.open()
    try:
        return bench_act.render(await bench_act.run(args.runs, args.case, _bench_act_options(args)))
    finally:
        for close in closers:
            await close()
        await database.close()


async def _bench_replay(settings: Settings, args: argparse.Namespace) -> str:
    options = bench_replay.Options(records=args.records)
    events = Path(args.events) if args.events else None
    results = [await bench_replay_run.run(settings, Path(args.snapshot), options, events, args.keep, args.cad_image)
               for _ in range(1 if args.records else args.runs)]
    texts = [bench_replay_run.write(r, None) for r in results]
    if args.json:
        Path(args.json).write_text("[" + ",\n".join(texts) + "]\n")
    return "\n".join(texts)


async def _run(settings: Settings, args: argparse.Namespace) -> str:
    if args.eval == "bench-replay":
        return await _bench_replay(settings, args)
    if args.eval == "bench-replay-capture":
        return await bench_replay_run.capture(settings, args.bench, args.from_turn, Path(args.out))
    if args.eval == "bench-act":
        return await _bench_act(settings, args)
    if args.eval == "memory-recall-hybrid":
        return await memory_recall_hybrid.run(settings)
    if args.eval in ("reply-remember", "reply-owed", "outside-ask", "action-judge"):
        return await _reply(settings, args)
    if args.eval == "house":
        return await _house(settings, args)
    if args.eval == "watch-tools":
        return await _watch_tools(settings, args)
    return await _memory_write(settings, args)


def main(argv: list[str]) -> int:
    """0 done (whatever the pass rate); 1 a model could not be reached or refused, or no such case; 2 usage, a
    pinned provider the task has no route for, or an unset DATABASE_URL."""
    args = parser().parse_args(argv)
    if args.eval in ("memory-write", "reply-remember", "reply-owed", "outside-ask", "action-judge", "house", "watch-tools", "bench-act", "bench-replay") and args.runs < 1:
        print("--runs is at least 1", file=sys.stderr)
        return 2
    if args.eval == "bench-replay" and args.snapshot is None:
        print("bench-replay needs the directory of a snapshot (bench-replay-capture writes one)", file=sys.stderr)
        return 2
    if args.eval == "bench-act" and args.scripted:
        logs.setup()
        print(bench_act.render(asyncio.run(bench_act.run(args.runs, args.case, _bench_act_options(args)))))
        return 0
    try:
        settings = from_env()
    except KeyError:
        print("DATABASE_URL is unset", file=sys.stderr)
        return 2
    logs.setup()
    try:
        print(asyncio.run(_run(settings, args)))
    except PinError as e:
        print(e, file=sys.stderr)
        return 2
    except InferenceError as e:
        logs.warning(log, "eval.failed", eval=args.eval, reason=type(e).__name__)
        print(f"inference failed: {type(e).__name__}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
