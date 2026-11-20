"""Conversation leases shared by API workers."""

import logging
from hashlib import sha256
from uuid import uuid4

from support_agent.infra.redis import KeyValueStore

logger = logging.getLogger(__name__)


class LockUnavailable(RuntimeError):
    """The request cannot safely start a conversation turn."""


class ConversationLocks:
    def __init__(self, store: KeyValueStore | None, ttl_s: int) -> None:
        self.store = store
        self.ttl_s = ttl_s

    @staticmethod
    def _key(thread_id: str) -> str:
        return "atlas:conversation:" + sha256(thread_id.encode()).hexdigest()

    def acquire(self, thread_id: str) -> str | None:
        if self.store is None:
            raise LockUnavailable("Conversation lock unavailable")
        token = uuid4().hex
        try:
            acquired = self.store.set_if_absent(self._key(thread_id), token, self.ttl_s)
        except Exception as error:
            logger.warning("Conversation lock acquire failed: %s", type(error).__name__)
            raise LockUnavailable("Conversation lock unavailable") from None
        return token if acquired else None

    def refresh(self, thread_id: str, token: str) -> bool:
        if self.store is None:
            return False
        try:
            return self.store.refresh_if_value(self._key(thread_id), token, self.ttl_s)
        except Exception as error:
            logger.warning("Conversation lock renewal failed: %s", type(error).__name__)
            return False

    def release(self, thread_id: str, token: str) -> None:
        if self.store is not None:
            try:
                self.store.delete_if_value(self._key(thread_id), token)
            except Exception as error:
                # The lease will expire if the store cannot acknowledge a release.
                logger.warning("Conversation lock release failed: %s", type(error).__name__)
