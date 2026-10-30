"""Eden's mix and master."""

from collections.abc import Callable

# (what Eden is doing, share of the stage done when that step starts); the share is None for a
# detail of the running step: what was measured or decided
ProgressCallback = Callable[[str, float | None], None]
