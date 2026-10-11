"""Import shim so the labelled sets load whether tests run from backend/ or backend/tests/."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from assistant_eval_set import EVAL_SET  # noqa: E402,F401
from assistant_holdout_set import HOLDOUT_SET  # noqa: E402,F401
