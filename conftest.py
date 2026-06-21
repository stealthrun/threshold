import sys
from pathlib import Path

# The runnable code now lives inside the portable skill, under scripts/. Put that dir on
# sys.path so tests can import the modules (coach, interpret, ingest.*, vault.*) unchanged —
# this mirrors how the skill itself runs (python puts a script's own dir first on the path).
_SCRIPTS = Path(__file__).resolve().parent / "skills" / "coaching-interpretation" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
