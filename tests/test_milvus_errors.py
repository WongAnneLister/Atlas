"""Milvus outages must be recognised however pymilvus wraps them."""

from __future__ import annotations

import grpc
import pytest
from pymilvus.client.types import Status
from pymilvus.exceptions import MilvusException

from support_agent.retrieval.milvus_store import milvus_transport_failure


class Rpc(grpc.RpcError):
    def __init__(self, status: grpc.StatusCode) -> None:
        self._status = status

    def code(self) -> grpc.StatusCode:
        return self._status


def _connect_failed() -> MilvusException:
    return MilvusException(code=Status.CONNECT_FAILED, message="Fail connecting to server")


def _raised_during(outer: Exception, inner: Exception) -> Exception:
    """Raise `outer` while handling `inner`, the way pymilvus recovery code does."""
    try:
        try:
            raise inner
        except Exception:
            raise outer  # noqa: B904 - reproduce an implicit __context__ chain
    except Exception as error:
        return error


def test_connect_failure_is_a_transport_failure() -> None:
    # Regression (second 19a smoke run): a dropped SSH tunnel surfaced as
    # MilvusException(code=CONNECT_FAILED) and was handled as a plain retrieval error.
    assert milvus_transport_failure(_connect_failed())


@pytest.mark.parametrize(
    "error",
    [
        _raised_during(MilvusException(message="recover"), Rpc(grpc.StatusCode.UNAVAILABLE)),
        _raised_during(MilvusException(message="wrapper"), _connect_failed()),
    ],
)
def test_transport_failure_is_found_anywhere_in_the_exception_chain(error: Exception) -> None:
    assert milvus_transport_failure(error)


def test_plain_milvus_errors_are_not_transport_failures() -> None:
    assert not milvus_transport_failure(MilvusException(message="schema mismatch"))
    assert not milvus_transport_failure(
        _raised_during(MilvusException(message="bad"), ValueError("bad input"))
    )
