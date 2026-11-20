"""Thread-safe, per-process circuit breakers for dependency attempts."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from threading import Lock
from time import monotonic
from typing import TypeVar

from support_agent.reliability.errors import CircuitOpen, is_retryable
from support_agent.reliability.settings import CircuitSettings

T = TypeVar("T")


class CircuitState(IntEnum):
    CLOSED = 0
    HALF_OPEN = 1
    OPEN = 2


@dataclass
class _Circuit:
    state: CircuitState = CircuitState.CLOSED
    generation: int = 0
    failures: int = 0
    reopen_at: float = 0.0
    probes_started: int = 0
    probes_pending: int = 0


class CircuitRegistry:
    def __init__(
        self, settings: CircuitSettings, *, clock: Callable[[], float] = monotonic
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._lock = Lock()
        self._circuits: dict[str, _Circuit] = {}

    def state(self, dependency: str) -> CircuitState:
        with self._lock:
            circuit = self._circuits.get(dependency)
            return self._effective_state(circuit) if circuit else CircuitState.CLOSED

    def call(self, dependency: str, fn: Callable[[], T]) -> T:
        circuit, generation = self._admit(dependency)
        try:
            result = fn()
        except BaseException as error:
            self._complete(circuit, generation, failed=is_retryable(error))
            raise
        self._complete(circuit, generation, failed=False)
        return result

    def _effective_state(self, circuit: _Circuit) -> CircuitState:
        if circuit.state is CircuitState.OPEN and self._clock() >= circuit.reopen_at:
            return CircuitState.HALF_OPEN
        return circuit.state

    def _admit(self, dependency: str) -> tuple[_Circuit, int]:
        with self._lock:
            circuit = self._circuits.setdefault(dependency, _Circuit())
            circuit.state = self._effective_state(circuit)
            if circuit.state is CircuitState.OPEN:
                raise CircuitOpen(dependency)
            if circuit.state is CircuitState.HALF_OPEN:
                if circuit.probes_started >= self._settings.half_open_max_calls:
                    raise CircuitOpen(dependency)
                circuit.probes_started += 1
                circuit.probes_pending += 1
            return circuit, circuit.generation

    def _complete(self, circuit: _Circuit, generation: int, *, failed: bool) -> None:
        with self._lock:
            # A late outcome from a previous cycle must not change the current circuit.
            if circuit.generation != generation:
                return
            if circuit.state is CircuitState.HALF_OPEN:
                circuit.probes_pending -= 1
                if failed:
                    self._open(circuit)
                elif circuit.probes_pending == 0:
                    circuit.state = CircuitState.CLOSED
                    circuit.generation += 1
                    circuit.failures = 0
            else:
                circuit.failures = circuit.failures + 1 if failed else 0
                if circuit.failures >= self._settings.failure_threshold:
                    self._open(circuit)

    def _open(self, circuit: _Circuit) -> None:
        circuit.state = CircuitState.OPEN
        circuit.generation += 1
        circuit.reopen_at = self._clock() + self._settings.cool_down_s
        circuit.probes_started = 0
        circuit.probes_pending = 0
