"""Validate provider envelopes and derive repair feedback without echoing model text."""

from dataclasses import dataclass
from typing import Generic, TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ValidationError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class ParsedResponse(Generic[SchemaT]):
    value: SchemaT
    model_name: str | None


class StructuredOutputError(ValueError):
    def __init__(
        self,
        error_type: str,
        detail: str,
        model_name: str | None = None,
        *,
        repaired: bool = False,
    ) -> None:
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail
        self.model_name = model_name
        self.repaired = repaired


def invalid_response(
    schema: type[BaseModel], error: Exception, model_name: str | None = None
) -> StructuredOutputError:
    error_type = type(error).__name__
    detail = f"Invalid structured response ({error_type})."
    if isinstance(error, ValidationError):
        issues = []
        for item in error.errors(include_input=False, include_context=False, include_url=False):
            loc = item["loc"]
            # Unknown keys may contain model output. Use only declared field names.
            field = loc[0] if loc and loc[0] in schema.model_fields else "response"
            issues.append(f"{field}: {item['type']}")
        if issues:
            detail = "; ".join(dict.fromkeys(issues))
    return StructuredOutputError(error_type, detail, model_name)


def parse_response(schema: type[SchemaT], response: object) -> ParsedResponse[SchemaT]:
    if not isinstance(response, dict):
        raise StructuredOutputError("ValueError", "Expected a structured response envelope.")
    raw = response.get("raw")
    name = (
        raw.response_metadata.get("model_name") or raw.response_metadata.get("model")
        if isinstance(raw, BaseMessage)
        else None
    )
    model_name = name if isinstance(name, str) else None
    parsing_error = response.get("parsing_error")
    if isinstance(parsing_error, Exception):
        raise invalid_response(schema, parsing_error, model_name) from None
    if parsing_error is not None:
        raise StructuredOutputError(
            "ValueError", "Unable to parse structured response.", model_name
        )
    try:
        value = schema.model_validate(response.get("parsed"))
    except ValidationError as error:
        raise invalid_response(schema, error, model_name) from None
    return ParsedResponse(value, model_name)
