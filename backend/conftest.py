import sys
from pathlib import Path

# Add the UASAE root (parent of backend/) to sys.path so that
# `from backend.core...` imports resolve without needing PYTHONPATH set.
sys.path.insert(0, str(Path(__file__).parent.parent))
