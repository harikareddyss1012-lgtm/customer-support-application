"""Query-time retrieval: filter, search, threshold, de-duplicate, format for the prompt.

Week-3 additions:
  - product_area filter (new metadata field on article chunks)
  - article_id filter
  - _to_chunk() now populates source_file, article_id, product_area, last_updated
  - format_context() exposes chunk_id in the prompt so the model can cite it directly
"""

from __future__ import annotations

import logging
from typing import Any

from ..schemas import (
    ArticleFilters,
    Category,
    Priority,
    RetrievedChunk,
    Status,
    TicketFilters,
)
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

import re
from rank_bm25 import BM25Okapi

OVERFETCH_FACTOR = 3


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w\-]+", text.lower()) if t]


class Retriever:
    """Turns a natural-language question into a ranked list of chunks using Dense, Hybrid BM25+RRF, or Cross-Encoder Reranking."""

    def __init__(self, store: VectorStore, top_k: int = 6, min_relevance: float = 0.25) -> None:
        self.store = store
        self.top_k = top_k
        self.min_relevance = min_relevance
        self._bm25_corpus: list[dict[str, Any]] = []
        self._bm25_index: BM25Okapi | None = None
        self._cross_encoder = None
        self._init_bm25()

    def _init_bm25(self) -> None:
        try:
            self._bm25_corpus = self.store.get_all()
            if self._bm25_corpus:
                tokenized_corpus = [_tokenize(c["text"]) for c in self._bm25_corpus]
                self._bm25_index = BM25Okapi(tokenized_corpus)
        except Exception as exc:
            logger.warning("Failed to initialize BM25 index: %s", exc)
            self._bm25_index = None

    def _get_cross_encoder(self) -> Any:
        if self._cross_encoder is None:
            try:
                from sentence_transformers import CrossEncoder
                self._cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            except Exception as exc:
                logger.warning("Could not load sentence_transformers CrossEncoder: %s", exc)
        return self._cross_encoder

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filters: TicketFilters | None = None,
        article_filters: ArticleFilters | None = None,
        max_per_source: int = 2,
        strategy: str = "hybrid",
    ) -> list[RetrievedChunk]:
        """Retrieve using `dense`, `hybrid` (BM25+RRF), or `rerank` (Cross-Encoder)."""
        limit = top_k or self.top_k
        where = _build_where(filters, article_filters)

        # ------------------------------------------------ standard dense
        if strategy == "dense":
            hits = self.store.query(query, top_k=limit * OVERFETCH_FACTOR, where=where)
            if not hits:
                return []
            chunks = [_to_chunk(hit) for hit in hits]
            if self.min_relevance > 0.0:
                chunks = [c for c in chunks if c.score >= self.min_relevance]
            return _deduplicate(chunks, max_per_source, limit)

        # ------------------------------------------------ cross-encoder rerank
        if strategy == "rerank":
            candidate_limit = max(25, limit * OVERFETCH_FACTOR)
            dense_hits = self.store.query(query, top_k=candidate_limit, where=where)
            if not dense_hits:
                return []
            dense_chunks = [_to_chunk(hit) for hit in dense_hits]

            cross_enc = self._get_cross_encoder()
            if cross_enc is not None:
                try:
                    pairs = [(query, c.text) for c in dense_chunks]
                    scores = cross_enc.predict(pairs)
                    for chunk, score in zip(dense_chunks, scores):
                        chunk.score = round(float(score), 4)
                    dense_chunks.sort(key=lambda c: c.score, reverse=True)
                except Exception as exc:
                    logger.warning("CrossEncoder prediction error: %s", exc)
            else:
                q_tokens = set(_tokenize(query))
                for chunk in dense_chunks:
                    c_tokens = set(_tokenize(chunk.text))
                    overlap = len(q_tokens.intersection(c_tokens))
                    chunk.score = round(chunk.score + (overlap * 0.05), 4)
                dense_chunks.sort(key=lambda c: c.score, reverse=True)

            return _deduplicate(dense_chunks, max_per_source, limit)

        # ------------------------------------------------ hybrid BM25 + RRF (default)
        candidate_limit = max(25, limit * OVERFETCH_FACTOR)
        dense_hits = self.store.query(query, top_k=candidate_limit, where=where)
        dense_chunks = [_to_chunk(hit) for hit in dense_hits]

        bm25_chunks: list[RetrievedChunk] = []
        if self._bm25_index and self._bm25_corpus:
            tokenized_query = _tokenize(query)
            bm25_scores = self._bm25_index.get_scores(tokenized_query)
            scored_corpus = []
            for score, raw in zip(bm25_scores, self._bm25_corpus):
                if score > 0:
                    scored_corpus.append((score, raw))
            scored_corpus.sort(key=lambda x: x[0], reverse=True)
            bm25_top = scored_corpus[:candidate_limit]
            for score, hit in bm25_top:
                hit_dict = {
                    "chunk_id": hit["chunk_id"],
                    "text": hit["text"],
                    "metadata": hit["metadata"],
                    "score": float(score),
                }
                bm25_chunks.append(_to_chunk(hit_dict))

        rrf_k = 60
        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, RetrievedChunk] = {}

        for rank, chunk in enumerate(dense_chunks, start=1):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))

        for rank, chunk in enumerate(bm25_chunks, start=1):
            cid = chunk.chunk_id
            if cid not in chunk_map:
                chunk_map[cid] = chunk
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))

        fused_cids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

        chunks = []
        for cid in fused_cids:
            chunk = chunk_map[cid]
            chunk.score = round(rrf_scores[cid], 6)
            chunks.append(chunk)

        if self.min_relevance > 0.0:
            chunks = [c for c in chunks if c.score >= self.min_relevance]

        return _deduplicate(chunks, max_per_source, limit)


def _deduplicate(chunks: list[RetrievedChunk], max_per_source: int, limit: int) -> list[RetrievedChunk]:
    per_source: dict[str, int] = {}
    selected: list[RetrievedChunk] = []
    for chunk in chunks:
        source_key = chunk.article_id or chunk.ticket_id
        seen = per_source.get(source_key, 0)
        if seen >= max_per_source:
            continue
        per_source[source_key] = seen + 1
        selected.append(chunk)
        if len(selected) >= limit:
            break
    return selected

    def similar_to_ticket(
        self, subject: str, body: str, top_k: int = 4, resolved_only: bool = True
    ) -> list[RetrievedChunk]:
        """Find past tickets like this one — backs triage and reply drafting."""
        where: dict[str, Any] | None = {"has_resolution": True} if resolved_only else None
        hits = self.store.query(f"{subject}\n\n{body}", top_k=top_k * OVERFETCH_FACTOR, where=where)

        seen: set[str] = set()
        out: list[RetrievedChunk] = []
        for chunk in (_to_chunk(hit) for hit in hits):
            if chunk.ticket_id in seen:
                continue
            seen.add(chunk.ticket_id)
            out.append(chunk)
            if len(out) >= top_k:
                break
        return out


def _build_where(
    filters: TicketFilters | None,
    article_filters: ArticleFilters | None,
) -> dict[str, Any] | None:
    """Translate filters into a Chroma `where` clause.

    Week-3: product_area and article_id now supported as filter fields.
    """
    clauses: list[dict[str, Any]] = []

    if filters:
        for field, value in (
            ("category", filters.category),
            ("priority", filters.priority),
            ("status", filters.status),
            ("product", filters.product),
        ):
            if value is not None:
                clauses.append({field: value.value if hasattr(value, "value") else value})

    if article_filters:
        if article_filters.product_area is not None:
            clauses.append({"product_area": article_filters.product_area})
        if article_filters.article_id is not None:
            clauses.append({"article_id": article_filters.article_id})

    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _to_chunk(hit: dict[str, Any]) -> RetrievedChunk:
    meta = hit["metadata"]
    return RetrievedChunk(
        chunk_id=hit["chunk_id"],
        ticket_id=str(meta.get("ticket_id", meta.get("article_id", hit["chunk_id"].split("::")[0]))),
        subject=str(meta.get("subject", "(untitled)")),
        text=hit["text"],
        score=round(hit["score"], 4),
        # ticket fields
        category=_enum(Category, meta.get("category")),
        priority=_enum(Priority, meta.get("priority")),
        status=_enum(Status, meta.get("status")),
        product=meta.get("product"),
        # Week-3 article fields
        source_file=meta.get("source_file"),
        article_id=meta.get("article_id"),
        product_area=meta.get("product_area"),
        last_updated=meta.get("last_updated"),
    )


def _enum(enum_cls: type, value: Any) -> Any:
    """Coerce a stored string back to its enum, tolerating unknown values."""
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Render chunks as the <source> block the model sees.

    Week-3: chunk_id is now included in the XML tag so the model can cite it
    directly (e.g. [chunk_id: BM-002::t3]) rather than a positional [1] index
    that cannot be resolved after the response is generated.
    """
    if not chunks:
        return "(no matching sources found in the knowledge base)"

    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        # Build attribute string
        attrs: list[str] = [
            f'index="{index}"',
            f'chunk_id="{chunk.chunk_id}"',
        ]
        if chunk.article_id:
            attrs.append(f'article_id="{chunk.article_id}"')
        if chunk.source_file:
            attrs.append(f'source_file="{chunk.source_file}"')
        if chunk.product_area:
            attrs.append(f'product_area="{chunk.product_area}"')
        if chunk.last_updated:
            attrs.append(f'last_updated="{chunk.last_updated}"')
        for name in ("category", "priority", "status", "product"):
            val = getattr(chunk, name)
            if val is not None:
                attrs.append(f'{name}="{val.value if hasattr(val, "value") else val}"')
        attrs.append(f'relevance="{chunk.score:.2f}"')

        blocks.append(
            f'<source {" ".join(attrs)}>\n'
            f"{chunk.text.strip()}\n"
            f"</source>"
        )
    return "\n\n".join(blocks)
