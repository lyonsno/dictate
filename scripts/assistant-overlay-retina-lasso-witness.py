#!/usr/bin/env python3
"""Run the assistant/operator overlay Retina Lasso witness, never Throughglass."""

from __future__ import annotations

import os
import sys

from spoke.retina_lasso_witness import main


if __name__ == "__main__":
    os.environ["SPOKE_RETINA_LASSO_WITNESS_KIND"] = "command-overlay"
    os.environ["SPOKE_PERCEPTASIA_THROUGHGLASS_SMOKE"] = "0"
    raise SystemExit(main(sys.argv[1:]))
