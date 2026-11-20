"""Record only the hostname of a configured LLM endpoint."""

import ipaddress
import os
import re
from urllib.parse import urlsplit

from support_agent.config import LLMSettings
from support_agent.llm import resolve_model

DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def _base_url(settings: LLMSettings) -> object:
    _, provider = resolve_model("main", settings)
    options = settings.model_kwargs
    if "base_url" in options:
        return options["base_url"]
    if provider == "deepseek":
        return options.get(
            "api_base", os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        )
    if provider == "openai":
        return options.get("openai_api_base") or (
            os.getenv("OPENAI_API_BASE")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
    return None


def endpoint_host(settings: LLMSettings) -> str | None:
    url = _base_url(settings)
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        return None
    try:
        parsed = urlsplit(url)
        _ = parsed.port  # Validate an optional port without retaining it.
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host or "%" in host:
            return None
        if ":" in host:
            authority = parsed.netloc.rsplit("@", 1)[-1]
            suffix = authority.partition("]")[2]
            if not authority.startswith("[") or (suffix and not suffix.startswith(":")):
                return None
            return ipaddress.IPv6Address(host).compressed
        domain = host.removesuffix(".").encode("idna").decode("ascii").lower()
    except ValueError:
        return None
    if len(domain) <= 253 and all(DNS_LABEL.fullmatch(label) for label in domain.split(".")):
        return domain
    return None
