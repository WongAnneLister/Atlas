"""Bound body buffering before FastAPI reads or decodes the request."""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        async def too_large() -> None:
            response = JSONResponse(
                {"detail": "Request body exceeds the configured size limit"}, status_code=413
            )
            await response(scope, receive, send)

        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                length = int(declared)
                if length < 0:
                    raise ValueError()
            except ValueError:
                response = JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
                await response(scope, receive, send)
                return
            if length > self.max_bytes:
                await too_large()
                return

        body = bytearray()
        more_body = True
        while more_body:
            item = await receive()
            if item["type"] == "http.disconnect":
                return
            chunk = item.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await too_large()
                return
            body.extend(chunk)
            more_body = item.get("more_body", False)

        first_body: bytes | None = bytes(body)

        async def replay() -> Message:
            nonlocal first_body
            if first_body is None:
                return await receive()
            buffered, first_body = first_body, None
            return {"type": "http.request", "body": buffered, "more_body": False}

        await self.app(scope, replay, send)
