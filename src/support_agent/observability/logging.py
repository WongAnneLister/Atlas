"""Configure API logging with a filter for common personal data."""

import logging

from support_agent.guardrails.pii import redact_pii


class PIIRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_pii(record.getMessage())
        record.args = ()
        if record.exc_info and record.exc_text is None:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_pii(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_pii(record.stack_info)
        return True


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, PIIRedactionFilter) for item in handler.filters):
            handler.addFilter(PIIRedactionFilter())
