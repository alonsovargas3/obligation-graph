"""Prompt and schema loading, request building, and request fingerprinting.

The system prompt and output schema are frozen files under ``prompts/``; the
request built here carries exactly the kwargs the API contract allows (no
temperature, thinking, tools, or tool_choice). The fingerprint keys a cached
response to the exact request plus the document's identity, so a stale answer
can never be replayed against changed text or a changed prompt.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..textdoc import TextDoc
from .types import Chunk

ROOT = Path(__file__).resolve().parents[3]
PROMPT_PATH = ROOT / "prompts" / "extract_v1.md"
SCHEMA_PATH = ROOT / "prompts" / "extract_v1.schema.json"

MAX_TOKENS = 16000
BETAS = ("server-side-fallback-2026-07-01",)


def prompt_version() -> str:
    """The extraction prompt identity: name + short digest of prompt and schema bytes."""
    digest = hashlib.sha256(PROMPT_PATH.read_bytes() + SCHEMA_PATH.read_bytes()).hexdigest()
    return f"extract_v1@{digest[:8]}"


def build_request(chunk: Chunk, *, model: str, effort: str) -> dict:
    """The exact create() kwargs for one chunk, per the wave-2 API contract."""
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [
            {
                "type": "text",
                "text": PROMPT_PATH.read_text(encoding="utf-8"),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": chunk.text}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": json.loads(SCHEMA_PATH.read_text("utf-8"))},
        },
        "betas": list(BETAS),
        "fallbacks": "default",
    }


def request_fingerprint(request: dict, doc: TextDoc) -> str:
    """Identity of (request, document): canonical request JSON + source pin + textdoc sha."""
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    textdoc_sha = hashlib.sha256(doc.to_json().encode("utf-8")).hexdigest()
    digest = hashlib.sha256()
    digest.update(canonical.encode("utf-8"))
    digest.update(doc.source_sha256.encode("utf-8"))
    digest.update(textdoc_sha.encode("utf-8"))
    return digest.hexdigest()
