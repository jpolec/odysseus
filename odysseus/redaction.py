"""Central durable-boundary redaction for Odysseus state and streams."""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


REDACTION_RULESET_VERSION = "odysseus-redaction-v1"
REDACTED = "[REDACTED]"
USAGE_COUNTER_KEYS = frozenset(
    {
        "input_tokens",
        "cached_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        "max_tokens",
    }
)
SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|auth[_-]?token|password|passwd|secret|token|credential|cookie|private[_-]?key)",
    re.I,
)
ENV_ASSIGNMENT = re.compile(
    r"(?im)(\b(?:export\s+)?[A-Z_][A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|COOKIE|PRIVATE[_-]?KEY)[A-Z0-9_]*\s*=\s*)([^\s'\"#]+|'[^'\n]*'|\"[^\"\n]*\")"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|auth[_-]?token|password|passwd|secret|token|credential|cookie|private[_-]?key)\s*[:=]\s*)((?:bearer\s+)?[^\s'\",;]+|'[^'\n]*'|\"[^\"\n]*\")"
)
BEARER_VALUE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*")
TOKEN_VALUE = re.compile(
    r"\b(?:sk|ghp|github_pat|glpat|xox[baprs]|AKIA|ASIA)[-_A-Za-z0-9]{12,}\b"
)
JWT_VALUE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.S,
)
URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)")


@dataclass(frozen=True, slots=True)
class RedactionReceipt:
    ruleset_version: str
    boundary: str
    redacted_field_classes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RedactionEngine:
    """Redact recursively without recording secret material in receipts."""

    def __init__(self, *, exact_values: Iterable[str] = ()) -> None:
        self.exact_values = tuple(
            str(value) for value in exact_values if isinstance(value, str) and len(value) >= 4
        )

    def redact(self, value: Any, *, boundary: str = "unknown") -> tuple[Any, RedactionReceipt]:
        classes: set[str] = set()
        redacted = self._redact(copy.deepcopy(value), classes, key="")
        return redacted, RedactionReceipt(
            ruleset_version=REDACTION_RULESET_VERSION,
            boundary=boundary,
            redacted_field_classes=tuple(sorted(classes)),
        )

    def _redact(self, value: Any, classes: set[str], *, key: str) -> Any:
        if key and key.lower() not in USAGE_COUNTER_KEYS and SENSITIVE_KEY.search(key):
            classes.add(_class_for_key(key))
            return REDACTED
        if isinstance(value, str):
            return self._redact_string(value, classes)
        if isinstance(value, list):
            return [self._redact(item, classes, key="") for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact(item, classes, key="") for item in value)
        if isinstance(value, dict):
            return {
                str(item_key): self._redact(item_value, classes, key=str(item_key))
                for item_key, item_value in value.items()
            }
        return value

    def _redact_string(self, value: str, classes: set[str]) -> str:
        for secret in self.exact_values:
            if secret in value:
                value = value.replace(secret, REDACTED)
                classes.add("runtime_secret_value")
        if PRIVATE_KEY_BLOCK.search(value):
            value = PRIVATE_KEY_BLOCK.sub(REDACTED, value)
            classes.add("private_key")
        if ENV_ASSIGNMENT.search(value):
            value = ENV_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{REDACTED}", value)
            classes.add("env_file")
        if SENSITIVE_ASSIGNMENT.search(value):
            value = SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{REDACTED}", value)
            classes.add("sensitive_assignment")
        if URL_CREDENTIALS.search(value):
            value = URL_CREDENTIALS.sub(lambda match: f"{match.group(1)}{REDACTED}{match.group(3)}", value)
            classes.add("url_credential")
        if BEARER_VALUE.search(value):
            value = BEARER_VALUE.sub(lambda match: f"{match.group(1)}{REDACTED}", value)
            classes.add("authorization_header")
        if JWT_VALUE.search(value):
            value = JWT_VALUE.sub(REDACTED, value)
            classes.add("token")
        if TOKEN_VALUE.search(value):
            value = TOKEN_VALUE.sub(REDACTED, value)
            classes.add("token")
        return value


def _class_for_key(key: str) -> str:
    lowered = key.lower()
    if "api" in lowered and "key" in lowered:
        return "api_key"
    if "authorization" in lowered or "auth" in lowered:
        return "authorization_header"
    if "password" in lowered or "passwd" in lowered:
        return "password"
    if "cookie" in lowered:
        return "cookie"
    if "private" in lowered and "key" in lowered:
        return "private_key"
    if "credential" in lowered:
        return "credential"
    if "secret" in lowered:
        return "secret"
    if "token" in lowered:
        return "token"
    return "sensitive_field"


DEFAULT_REDACTION_ENGINE = RedactionEngine()


def redact(value: Any, *, boundary: str = "unknown") -> tuple[Any, RedactionReceipt]:
    return DEFAULT_REDACTION_ENGINE.redact(value, boundary=boundary)


def redact_for_boundary(value: Any, *, boundary: str = "unknown") -> Any:
    return redact(value, boundary=boundary)[0]
