"""The kinds this app has."""

from .bench_job import BenchJob
from .claude_session import ClaudeSession
from .kinds import Registry
from .mail_inbox import MailInbox

KINDS = Registry([ClaudeSession(), MailInbox(), BenchJob()])
