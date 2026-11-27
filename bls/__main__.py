"""Run one US CPI job of the Worker at CORE_URL (see common.runner): JOB=<id> python -m bls."""
import sys

from common import runner

from . import sources

sys.exit(runner.main(sources))
