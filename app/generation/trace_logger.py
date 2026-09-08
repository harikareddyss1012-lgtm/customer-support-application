"""Trace logger and replay engine for customer support RAG traces.

Captures 100% replayable trace records into traces.jsonl.
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TRACE_FILE_PATH = Path(__file__).resolve().parent.parent.parent / "traces.jsonl"


class RetrievedChunkMetadata(BaseModel):
    chunk_id: str
    score: float
    source_file: Optional[str] = None
    article_id: Optional[str] = None
    ticket_id: Optional[str] = None
    text_snippet: str


class TraceRecord(BaseModel):
    trace_id: str = Field(default_factory=lambda: f"tr_{uuid.uuid4().hex[:8]}")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    query_type: str = "chat"  # chat, triage, draft
    question: str
    subject: Optional[str] = None
    body: Optional[str] = None
    tone: Optional[str] = None
    strategy: str = "hybrid"
    top_k: int = 3
    prompt_version: str = "v1.2-rag-system-prompt"
    system_prompt: str
    user_prompt: str
    retrieved_chunks: List[RetrievedChunkMetadata]
    model: str
    model_params: Dict[str, Any] = Field(default_factory=lambda: {"temperature": 0.0, "max_tokens": 1024, "top_p": 1.0})
    raw_output: str
    reconstructed: bool = True
    latency_ms: float = 0.0
    tags: List[str] = Field(default_factory=list)


def log_trace(record: TraceRecord) -> None:
    """Append a trace record to traces.jsonl."""
    try:
        TRACE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRACE_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
    except Exception as exc:
        logger.warning("Failed to write trace record: %s", exc)


def load_all_traces() -> List[Dict[str, Any]]:
    """Read all traces from traces.jsonl."""
    if not TRACE_FILE_PATH.exists():
        return []
    traces = []
    with open(TRACE_FILE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    traces.append(json.loads(line))
                except Exception:
                    continue
    return traces


def sample_traces(seed: int = 42, sample_size: int = 20) -> List[Dict[str, Any]]:
    """Draw a seeded random sample of traces."""
    traces = load_all_traces()
    if not traces:
        return []
    rng = random.Random(seed)
    return rng.sample(traces, min(sample_size, len(traces)))
