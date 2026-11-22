"""One bounded retry and fallback policy for every model call in the graph."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Literal, TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from support_agent.llm import Role
from support_agent.reliability.errors import RetryBudgetExceeded, is_retryable
from support_agent.reliability.events import ReliabilityEvent, ReliabilityOutcome, record_event
from support_agent.reliability.retry import retry_call
from support_agent.reliability.structured import (
    ParsedResponse,
    SchemaT,
    StructuredOutputError,
    invalid_response,
    parse_response,
)

if TYPE_CHECKING:
    from support_agent.graph.deps import GraphDeps

CallSite = Literal[
    "input_guard",
    "rewrite",
    "plan",
    "classify",
    "answer",
    "decide",
    "order_extract",
    "grounding",
    "verify",
    "split_claims",
    "complaint",
    "tools",
]
LLMFault = Callable[[str], Literal["garbage"] | None]
ModelMessages = Callable[[CallSite, Sequence[BaseMessage]], Sequence[BaseMessage]]
T = TypeVar("T")
Operation = Callable[[BaseChatModel, bool, Sequence[BaseMessage]], T]
REPAIR_PROMPT = Path(__file__).resolve().parents[1] / "graph" / "prompts" / "repair.md"


@dataclass
class _ModelCall:
    site: CallSite
    role: Role
    timeout_s: float
    deadline: float
    model: str
    attempts: int = 0
    model_attempts: int = 0
    retries: int = 0
    fallback_error_type: str | None = None
    repaired: bool = False
    error_type: str | None = None

    @property
    def dependency(self) -> str:
        return f"llm:{self.model}"

    def event(self) -> ReliabilityEvent:
        return ReliabilityEvent(
            call_site=self.site,
            dependency=self.dependency,
            role=self.role,
            model=self.model,
            attempts=self.attempts,
            retries=self.retries,
            fell_back=self.fallback_error_type is not None,
            fallback_error_type=self.fallback_error_type,
            repaired=self.repaired,
            error_type=self.error_type,
        )


class ReliableModels:
    def __init__(self, deps: GraphDeps) -> None:
        self._deps = deps
        self._repair_prompt = REPAIR_PROMPT.read_text(encoding="utf-8").strip()

    def _messages(
        self, call_site: CallSite, prompt: Sequence[BaseMessage]
    ) -> Sequence[BaseMessage]:
        render = self._deps.model_messages
        return render(call_site, prompt) if render is not None else prompt

    def invoke(
        self,
        call_site: CallSite,
        role: Role,
        messages: Sequence[BaseMessage],
        *,
        tools: Sequence[BaseTool] = (),
    ) -> tuple[BaseMessage, ReliabilityEvent]:
        def operation(
            model: BaseChatModel, garbage: bool, prompt: Sequence[BaseMessage]
        ) -> BaseMessage:
            if garbage:
                return AIMessage(content="")
            runnable = model.bind_tools(tools) if tools else model
            return runnable.invoke(self._messages(call_site, prompt))

        return self._call(call_site, role, messages, operation)

    def structured(
        self,
        call_site: CallSite,
        role: Role,
        schema: type[SchemaT],
        messages: Sequence[BaseMessage],
        *,
        recover: bool = True,
    ) -> tuple[ParsedResponse[SchemaT], ReliabilityEvent]:
        def operation(
            model: BaseChatModel, garbage: bool, prompt: Sequence[BaseMessage]
        ) -> ParsedResponse[SchemaT]:
            try:
                response = (
                    {"raw": AIMessage(content=""), "parsed": None, "parsing_error": None}
                    if garbage
                    else model.with_structured_output(schema, include_raw=True).invoke(
                        self._messages(call_site, prompt)
                    )
                )
            except (OutputParserException, ValidationError, JSONDecodeError) as error:
                raise invalid_response(schema, error) from None
            return parse_response(schema, response)

        return self._call(call_site, role, messages, operation, recover=recover)

    def _call(
        self,
        call_site: CallSite,
        role: Role,
        messages: Sequence[BaseMessage],
        operation: Operation[T],
        *,
        recover: bool = True,
    ) -> tuple[T, ReliabilityEvent]:
        settings = self._deps.settings
        policy = settings.reliability.retry
        primary = self._deps.primary_model_name(role)
        fallbacks = getattr(settings.llm.fallbacks, role) if recover else ()
        chain = tuple(dict.fromkeys((primary, *fallbacks)))
        call = _ModelCall(
            site=call_site,
            role=role,
            timeout_s=getattr(
                settings.reliability.timeouts_s,
                "verify" if call_site == "split_claims" else call_site,
            ),
            deadline=monotonic() + policy.budget_s,
            model=primary,
        )

        def attempt(remaining: float) -> T:
            return self._attempt(call, operation, messages, remaining)

        def run() -> T:
            if not recover:
                return attempt(call.deadline - monotonic())
            return retry_call(attempt, policy=policy, is_idempotent=True, deadline=call.deadline)

        try:
            for index, model in enumerate(chain):
                call.model = model
                call.model_attempts = 0
                try:
                    # The breaker sees whole calls: one call whose retries all fail counts once.
                    result = self._deps.circuits.call(call.dependency, run)
                except StructuredOutputError as error:
                    if not recover:
                        raise
                    result = self._repair(call, operation, messages, error)
                    break
                except Exception as error:
                    if (
                        not is_retryable(error)
                        or index + 1 == len(chain)
                        or monotonic() >= call.deadline
                    ):
                        raise
                    call.fallback_error_type = type(error).__name__
                    if self._deps.observer:
                        self._deps.observer.fallback(role)
                else:
                    break
            else:
                raise AssertionError("The model chain must contain a primary")
        except StructuredOutputError as error:
            call.error_type = error.error_type
            raise
        except Exception as error:
            call.error_type = type(error).__name__
            raise
        finally:
            event = call.event()
            record_event(event)
        return result, event

    def _repair(
        self,
        call: _ModelCall,
        operation: Operation[T],
        messages: Sequence[BaseMessage],
        original: StructuredOutputError,
    ) -> T:
        remaining = call.deadline - monotonic()
        if remaining <= 0:
            raise original
        limit = self._deps.settings.reliability.repair_error_max_chars
        repair = HumanMessage(
            content=f"{self._repair_prompt}\n\nValidation issue: {original.detail[:limit]}"
        )
        outcome: ReliabilityOutcome = "error"
        try:
            result = self._deps.circuits.call(
                call.dependency,
                lambda: self._attempt(call, operation, [*messages, repair], remaining, repair=True),
            )
            outcome = "success"
            return result
        except StructuredOutputError as error:
            raise StructuredOutputError(
                error.error_type,
                error.detail,
                error.model_name or original.model_name,
                repaired=call.repaired,
            ) from None
        except Exception as error:
            raise StructuredOutputError(
                type(error).__name__,
                "Structured repair failed.",
                original.model_name,
                repaired=call.repaired,
            ) from None
        finally:
            if call.repaired and self._deps.observer:
                self._deps.observer.repair(call.site, outcome)

    def _attempt(
        self,
        call: _ModelCall,
        operation: Operation[T],
        messages: Sequence[BaseMessage],
        remaining: float,
        *,
        repair: bool = False,
    ) -> T:
        timeout_s = min(call.timeout_s, remaining)
        deadline = min(call.deadline, monotonic() + timeout_s)
        model_name = call.model

        def run() -> T:
            remaining_s = deadline - monotonic()
            if remaining_s <= 0:
                raise RetryBudgetExceeded("Model attempt budget exhausted")
            # Cache instances built for the configured site timeout. A shorter timeout
            # near the end of the shared budget is specific to this attempt.
            model = self._deps.model_for(
                call.role,
                model_name,
                min(timeout_s, remaining_s) if timeout_s < call.timeout_s else call.timeout_s,
                cache=timeout_s == call.timeout_s,
            )
            fault = self._deps.llm_fault
            return operation(model, fault is not None and fault(call.site) == "garbage", messages)

        def wait() -> T:
            observer = self._deps.observer
            if repair:
                call.repaired = True
            elif call.model_attempts:
                call.retries += 1
                if observer:
                    observer.retry(call.dependency)
            call.attempts += 1
            call.model_attempts += 1
            started = monotonic()
            outcome: ReliabilityOutcome = "error"
            try:
                result = self._deps.model_workers.run(run, deadline - monotonic())
                outcome = "success"
                return result
            finally:
                if observer:
                    observer.llm_attempt(call.role, call.model, outcome, monotonic() - started)

        return wait()
