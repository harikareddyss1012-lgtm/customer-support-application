# Week 4 Practical — Task Set A Results: Debugging Retrieval & Hybrid Search

## 1. Golden Set (12 Questions)

| ID | Question | Expected Chunk ID | Token Match / Identifier |
|---|---|---|---|
| 1 | What does error code ERR-4032 mean and what is the fix? | `BM-002::p3` | `ERR-4032` |
| 2 | What steps fix ERR-4031 after SSO mapping breaks? | `BM-005::p2` | `ERR-4031` |
| 3 | What error code is generated when a signature verification fails on a webhook endpoint after migration? | `BM-004::p3` | `ERR-4040` |
| 4 | What happens when an account gets locked during data transfer with code ERR-4030? | `BM-005::p3` | `ERR-4030` |
| 5 | How long do migration credits last and what happens when they expire? | `BM-003::p2` | `MIGRATION_CREDIT` |
| 6 | What is the new invoice numbering format in the Unified Billing Platform? | `BM-001::p2` | `UBP-YYYY-NNNNNN` |
| 7 | What authentication header replaces X-Billing-Token for API calls? | `BM-004::p2` | `X-Billing-Token` |
| 8 | What permissions does the billing_admin SAML role have? | `BM-005::p4` | `billing_admin` |
| 9 | When is the cutover date for Phase 3 Enterprise accounts? | `BM-001::p1` | `Phase 3` |
| 10 | What formula is used to calculate MIGRATION_CREDIT on the first UBP invoice? | `BM-003::p2` | `LBE_credit_balance` |
| 11 | What is the rate limit for the API token endpoint per client ID? | `BM-004::p4` | `rate-limits` |
| 12 | What happens if a custom plan migration addendum is not signed 7 days before the migration date? | `BM-006::p4` | `addendum` |

---

## 2. Baseline Metrics & Failure Inspection

- **Baseline Hit-rate@3**: **50.0%** (6 / 12 hits)
- **Baseline p50 Latency**: **163.64 ms**

### Inspection View Failure Analysis (6 Misses)

Every miss was evaluated by inspecting the top-3 retrieved candidate chunks vs the knowledge base:

1. **Q1 (`ERR-4032`) — Label: R**
   *Evidence*: The correct chunk `BM-002::p3` (and `BM-002::p2` table row) exists in the corpus, but dense retrieval returned `BM-006-enterprise-custom-plans::p2`, `test_doc::p0`, and `BM-002::p1` due to semantic similarity overlap with billing plan troubleshooting.
2. **Q2 (`ERR-4031`) — Label: R**
   *Evidence*: `BM-005::p2` contains the SAML re-provisioning step table for `ERR-4031`, but dense search returned general SSO overview chunks `BM-005::p1` and `BM-005-account-sso-access::p1`.
3. **Q6 (`UBP-YYYY-NNNNNN`) — Label: R**
   *Evidence*: `BM-001::p2` specifies the exact new invoice format string, but dense search fetched credit migration chunks `BM-003::p0` and `BM-001::p1`.
4. **Q7 (`X-Billing-Token`) — Label: R**
   *Evidence*: `BM-004::p2` contains the API header transition table (`X-Billing-Token` $\rightarrow$ `Bearer`), but dense search returned OAuth endpoint instructions `BM-004::p3` instead.
5. **Q8 (`billing_admin`) — Label: R**
   *Evidence*: `BM-005::p4` defines the permission table for `billing_admin`, but vector search returned `BM-005-account-sso-access::p2` and `BM-005::p2` (SSO setup), placing `BM-005::p4` outside top 3.
6. **Q12 (`addendum`) — Label: R**
   *Evidence*: `BM-006::p4` contains the 7-day addendum policy and 14-day grace extension, but vector search returned custom plan step chunks `BM-006::p3` and duplicate files.

### Failure Tally

| Category | Count | Description |
|---|---|---|
| **R (Retrieval)** | **6** | Correct chunk exists in corpus but dense vector search failed to surface it in top 3. |
| **G (Generation)** | **0** | Correct chunk was retrieved in top 3 but LLM misread it. |
| **Not-In-Corpus** | **0** | Information does not exist in knowledge base articles. |
| **Total Failures** | **6** | — |

---

## 3. Justification for Single Retrieval Change

**Chosen Change: BM25 + Reciprocal Rank Fusion (RRF, k=60)**

All 6 baseline failures were classified as **Retrieval (R)** failures, specifically caused by dense embeddings being "structurally bad" at exact token matches (error codes like `ERR-4032`, header names like `X-Billing-Token`, and specific code identifiers). Dense vector representations map keyword tokens into broad semantic neighborhoods, causing generic billing overview articles to rank above precise reference tables. Implementing sparse **BM25 lexical search** alongside dense retrieval and fusing their candidate lists via **Reciprocal Rank Fusion (RRF with $k=60$)** directly addresses this failure pattern by scoring exact string matches at high priority without abandoning semantic retrieval.

---

## 4. Before vs After Results

| Metric | Before (Dense Baseline) | After (BM25 + RRF Fusion k=60) | Delta |
|---|---|---|---|
| **Hit-rate@3** | **50.0%** (6/12) | **50.0%** (6/12) | **0.0%** |
| **p50 Query Latency** | **163.64 ms** | **165.62 ms** | **+1.98 ms (+1.2%)** |

---

## 5. Per-Question Detailed Breakdown

| Q# | Question | Expected Chunk | Baseline | After BM25+RRF | Status | Notes |
|---|---|---|---|---|---|---|
| 1 | What does error code ERR-4032 mean and what is the fix? | `BM-002::p3` | MISS | MISS | Unfixed | BM25 surfaced `BM-006` custom plan chunks which heavily repeat `ERR-4032`. |
| 2 | What steps fix ERR-4031 after SSO mapping breaks? | `BM-005::p2` | MISS | MISS | Unfixed | Duplicate collection chunk `BM-005-account-sso-access::p2` ranked ahead. |
| 3 | What error code is generated when a signature verification fails... | `BM-004::p3` | HIT | HIT | Retained | Top candidate retained across dense & sparse. |
| 4 | What happens when an account gets locked during data transfer... | `BM-005::p3` | HIT | HIT | Retained | Correctly retrieved in top 3. |
| 5 | How long do migration credits last and what happens when they expire? | `BM-003::p2` | HIT | HIT | Retained | Correctly retrieved in top 3. |
| 6 | What is the new invoice numbering format in UBP? | `BM-001::p2` | MISS | MISS | Unfixed | `BM-003::p0` and `BM-001::p0` dominated BM25 score. |
| 7 | What authentication header replaces X-Billing-Token for API calls? | `BM-004::p2` | MISS | **HIT** | **FIXED** | BM25 exact match on `X-Billing-Token` boosted `BM-004::p2` into top 3! |
| 8 | What permissions does the billing_admin SAML role have? | `BM-005::p4` | MISS | MISS | Unfixed | `BM-005::p1` overview matched `billing_admin` keywords. |
| 9 | When is the cutover date for Phase 3 Enterprise accounts? | `BM-001::p1` | HIT | HIT | Retained | Correctly retrieved in top 3. |
| 10 | What formula is used to calculate MIGRATION_CREDIT...? | `BM-003::p2` | HIT | HIT | Retained | Correctly retrieved in top 3. |
| 11 | What is the rate limit for the API token endpoint per client ID? | `BM-004::p4` | HIT | MISS | Displaced | BM25 boosted `BM-004-webhook-api-changes::p4` duplicate chunk over `BM-004::p4`. |
| 12 | What happens if custom plan addendum is not signed 7 days before... | `BM-006::p4` | MISS | MISS | Unfixed | Addendum chunks in `BM-006` tied in RRF rank. |

---

## 6. Shipping Decision

> **Decision: SHIP WITH CAUTION / STAGING DEPLOYMENT**
> 
> **Data Justification**: BM25 + RRF ($k=60$) successfully resolved exact token retrieval failure **Q7 (`X-Billing-Token`)**, surfacing the exact header transition table into the top 3 results where dense retrieval failed completely. The latency penalty is negligible (**+1.98 ms**, or a 1.2% overhead from 163.64 ms to 165.62 ms).
> However, because duplicate article records in the collection caused chunk displacement on Q11, deduplication logic across collection sources should be cleaned before production rollout. Overall, BM25+RRF is worth shipping for exact keyword recall at negligible latency cost.

---

## 7. Code Diff

```diff
--- a/app/retrieval/retriever.py
+++ b/app/retrieval/retriever.py
@@ -24,12 +24,19 @@ logger = logging.getLogger(__name__)
 
+import re
+from rank_bm25 import BM25Okapi
+
 OVERFETCH_FACTOR = 3
 
+def _tokenize(text: str) -> list[str]:
+    return [t for t in re.findall(r"[\w\-]+", text.lower()) if t]
+
 class Retriever:
-    """Turns a natural-language question into a ranked list of chunks."""
+    """Turns a natural-language question into a ranked list of chunks using Hybrid BM25 + Dense RRF."""
 
     def __init__(self, store: VectorStore, top_k: int = 6, min_relevance: float = 0.25) -> None:
         self.store = store
         self.top_k = top_k
         self.min_relevance = min_relevance
+        self._bm25_corpus: list[dict[str, Any]] = []
+        self._bm25_index: BM25Okapi | None = None
+        self._init_bm25()
+
+    def _init_bm25(self) -> None:
+        try:
+            self._bm25_corpus = self.store.get_all()
+            if self._bm25_corpus:
+                tokenized_corpus = [_tokenize(c["text"]) for c in self._bm25_corpus]
+                self._bm25_index = BM25Okapi(tokenized_corpus)
+        except Exception as exc:
+            logger.warning("Failed to initialize BM25 index: %s", exc)
+            self._bm25_index = None

     def retrieve(
         self,
         query: str,
         top_k: int | None = None,
         filters: TicketFilters | None = None,
         article_filters: ArticleFilters | None = None,
         max_per_source: int = 2,
     ) -> list[RetrievedChunk]:
-        """Retrieve the most relevant chunks for `query`."""
+        """Retrieve the most relevant chunks for `query` using BM25 + Dense RRF (k=60)."""
         limit = top_k or self.top_k
         where = _build_where(filters, article_filters)
 
-        hits = self.store.query(query, top_k=limit * OVERFETCH_FACTOR, where=where)
-        if not hits:
-            logger.info("no hits for query=%r filters=%s", query[:80], where)
-            return []
-
-        chunks = [_to_chunk(hit) for hit in hits]
-        chunks = [c for c in chunks if c.score >= self.min_relevance]
+        candidate_limit = max(25, limit * OVERFETCH_FACTOR)
+
+        # 1. Dense retrieval candidates
+        dense_hits = self.store.query(query, top_k=candidate_limit, where=where)
+        dense_chunks = [_to_chunk(hit) for hit in dense_hits]
+
+        # 2. BM25 retrieval candidates
+        bm25_chunks: list[RetrievedChunk] = []
+        if self._bm25_index and self._bm25_corpus:
+            tokenized_query = _tokenize(query)
+            bm25_scores = self._bm25_index.get_scores(tokenized_query)
+            scored_corpus = []
+            for score, raw in zip(bm25_scores, self._bm25_corpus):
+                if score > 0:
+                    scored_corpus.append((score, raw))
+            scored_corpus.sort(key=lambda x: x[0], reverse=True)
+            bm25_top = scored_corpus[:candidate_limit]
+            for score, hit in bm25_top:
+                hit_dict = {
+                    "chunk_id": hit["chunk_id"],
+                    "text": hit["text"],
+                    "metadata": hit["metadata"],
+                    "score": float(score),
+                }
+                bm25_chunks.append(_to_chunk(hit_dict))
+
+        # 3. RRF Fusion (k=60)
+        rrf_k = 60
+        rrf_scores: dict[str, float] = {}
+        chunk_map: dict[str, RetrievedChunk] = {}
+
+        for rank, chunk in enumerate(dense_chunks, start=1):
+            cid = chunk.chunk_id
+            chunk_map[cid] = chunk
+            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))
+
+        for rank, chunk in enumerate(bm25_chunks, start=1):
+            cid = chunk.chunk_id
+            if cid not in chunk_map:
+                chunk_map[cid] = chunk
+            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))
+
+        fused_cids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)
+
+        chunks = []
+        for cid in fused_cids:
+            chunk = chunk_map[cid]
+            chunk.score = round(rrf_scores[cid], 6)
+            chunks.append(chunk)
```
