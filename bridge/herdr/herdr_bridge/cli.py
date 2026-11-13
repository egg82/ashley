"""`herdr-bridge init` and `herdr-bridge serve`."""

import argparse
import os
import sys
from pathlib import Path

from .api import Api
from .auth import Auth
from .config import CONFIG_DIR, STATE_DIR, Config, ConfigError, load
from .files import Limits
from .herdr import Herdr
from .install import init
from .ledger import Ledger
from .logs import Log, StdoutLog
from .runner import SubprocessRunner
from .server import make_server
from .sessions import Sessions
from .transcripts import Transcripts

CONFIG_PATH = CONFIG_DIR / "config.json"
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="herdr-bridge")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("init", help="write the settings and mint a token (printed once)")
    i.add_argument("--root", action="append", required=True, help="a directory sessions may be started under; repeatable")
    i.add_argument("--client-ca", required=True, help="the ashley-bridges CA certificate (PEM)")
    i.add_argument("--host", default="0.0.0.0")
    i.add_argument("--port", type=int, default=7843)
    i.add_argument("--herdr", default="herdr", help="the herdr binary")
    sub.add_parser("serve", help="serve the API")
    return p


def run_init(args: argparse.Namespace) -> int:
    roots = tuple(os.path.realpath(r) for r in args.root)
    config = Config(args.host, args.port, roots, str(STATE_DIR), os.path.realpath(args.client_ca), args.herdr)
    token, pin = init(config, CONFIG_PATH)
    print(f"settings: {CONFIG_PATH}")
    print(f"fingerprint (sha256): {pin}")
    print(f"token (shown once): {token}")
    return 0


def make_api(config: Config, herdr: Herdr, log: Log) -> Api:
    ledger = Ledger(Path(config.state_dir) / "sent-prompts.jsonl")
    transcripts = Transcripts(CLAUDE_DIR / "projects", ledger)
    sessions = Sessions(herdr, config.roots, config.start_timeout_ms, log, transcripts, keep_job_dirs=config.keep_job_dirs)
    return Api(Auth(Path(config.state_dir)), sessions, herdr, log, Limits(config.max_file_bytes, config.max_files))


def run_serve() -> int:
    try:
        config = load(CONFIG_PATH)
    except ConfigError as e:
        print(f"call=serve status=refused error={e}", file=sys.stderr)
        return 2
    log = StdoutLog()
    api = make_api(config, Herdr(SubprocessRunner(config.herdr)), log)
    server = make_server(config, api, log)
    log.emit(f"call=serve status=listening port={config.port}")
    server.serve_forever()
    return 0


def main() -> int:
    args = parser().parse_args()
    return run_init(args) if args.command == "init" else run_serve()
