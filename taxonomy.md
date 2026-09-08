# Week 5 Error Analysis Taxonomy — Customer Support RAG

| Mode Name | Count | Frequency % | Severity | Example Trace ID |
|---|---|---|---|---|
| `quotes-superseded-refund-window` | 6 | 30.0% | Embarrasses the client | `tr_0055` |
| `misses-token-match-on-error-code` | 5 | 25.0% | Annoys the user | `tr_0052` |
| `applies-expired-migration-credit-formula` | 4 | 20.0% | Embarrasses the client | `tr_0062` |
| `confuses-sso-mapping-role-permissions` | 3 | 15.0% | Annoys the user | `tr_0066` |
| `hallucinated-addendum-sign-off-grace-period` | 2 | 10.0% | Annoys the user | `tr_0286` |

---

## Executive Summary & Taxonomy Notes

- **Top Risk Area**: **Policy Deprecation & Versioning Drift**. 50% of sampled failures (`quotes-superseded-refund-window` + `applies-expired-migration-credit-formula`) stem from the vector index containing unversioned legacy help documentation alongside new UBP migration guidelines.
- **Secondary Risk Area**: **Exact Keyword Token Recall**. 25% of failures occur when dense vector embeddings fail to retrieve specific error codes (`ERR-4031`, `ERR-4032`, `ERR-4040`), falling back to generic setup guides.
- **Client Impact**: Quoting superseded refund windows directly embarrasses the client by exposing conflicting legal terms and creating chargeback liabilities.
