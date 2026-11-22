"""Filter capability for offline fixtures built from current-only, undated chunks."""

from contextlib import AbstractContextManager, nullcontext


class LegacyFilterSupport:
    def supports_filters(self) -> bool:
        return False

    def filter_scope(self) -> AbstractContextManager[None]:
        return nullcontext()
