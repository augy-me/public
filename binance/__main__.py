"""Run one Binance job of the Worker at CORE_URL (see common.runner): python -m binance [--preview]."""
import sys

from common import runner

from . import sources

sys.exit(runner.main(sources))
