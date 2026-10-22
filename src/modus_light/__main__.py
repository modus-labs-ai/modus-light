"""Allow `python -m modus_light`, for installs where the console script
   is not on PATH (`pip install --user`, or a venv that was not activated)."""

from .cli import main

raise SystemExit(main())
