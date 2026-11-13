"""The kinds this app has."""

from .bench_job import BenchJob
from .claude_session import ClaudeSession
from .ha_entity import HaEntity
from .kinds import Registry
from .mail_inbox import MailInbox
from .tool_watch import ToolWatch

KINDS = Registry([ClaudeSession(), MailInbox(), BenchJob(), ToolWatch(), HaEntity()])
