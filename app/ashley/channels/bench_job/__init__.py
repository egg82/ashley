"""The bench jobs' runner: the singleton that runs the jobs she handed to workers (`ashley.errands.bench_jobs`)."""

from ...errands.bench_jobs import JobsUnavailable as JobsUnavailable
from ...tools.bench_job_cancel import cancel as cancel
from .runner import NAME as NAME, BenchJobRunner as BenchJobRunner
