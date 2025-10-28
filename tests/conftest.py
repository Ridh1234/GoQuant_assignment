import os
import sys
from pathlib import Path

# Add the project root to sys.path so 'app' can be imported
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
