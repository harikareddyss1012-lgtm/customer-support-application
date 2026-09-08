"""Generate a 1,050 line production trace dataset (traces.jsonl) for Week 5 Error Analysis.

Simulates real customer support ticket queries running against the RAG assistant over time.
Pre-caches candidate chunks for high efficiency.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Disable langfuse loggers for fast generation
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-disabled"
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-disabled"

from app.config import get_settings
from app.generation import prompts
from app.retrieval.retriever import Retriever, format_context
from app.retrieval.vector_store import VectorStore

TRACE_FILE_PATH = PROJECT_ROOT / "traces.jsonl"

QUERY_TEMPLATES = [
    # Category 1: Refund & Policy Queries (Contains outdated 30-day policy vs new UBP 14-day policy)
    {"q": "What is your refund policy if I want to cancel my subscription after 30 days?", "type": "chat", "mode_hint": "refund_window"},
    {"q": "Can I get a full refund 25 days after auto-renewing my annual enterprise plan?", "type": "chat", "mode_hint": "refund_window"},
    {"q": "How many days do I have to request a billing chargeback or refund under the new UBP terms?", "type": "chat", "mode_hint": "refund_window"},
    {"q": "Is the 30-day money-back guarantee still valid for Phase 2 accounts migrated to UBP?", "type": "chat", "mode_hint": "refund_window"},
    {"q": "We canceled our subscription 20 days into the billing cycle. Are we eligible for a pro-rated refund?", "type": "chat", "mode_hint": "refund_window"},
    
    # Category 2: Error Codes & SSO / API Token Queries
    {"q": "What does error code ERR-4032 mean and what is the fix?", "type": "chat", "mode_hint": "error_code"},
    {"q": "What steps fix ERR-4031 after SSO mapping breaks?", "type": "chat", "mode_hint": "error_code"},
    {"q": "What error code is generated when a signature verification fails on a webhook endpoint after migration?", "type": "chat", "mode_hint": "error_code"},
    {"q": "What happens when an account gets locked during data transfer with code ERR-4030?", "type": "chat", "mode_hint": "error_code"},
    {"q": "My automated webhook listener started returning HTTP 400 with signature verification failed. How do I fix ERR-4040?", "type": "chat", "mode_hint": "error_code"},
    {"q": "What authentication header replaces X-Billing-Token for API calls?", "type": "chat", "mode_hint": "api_header"},

    # Category 3: Migration Credits & Billing Calculations
    {"q": "How long do migration credits last and what happens when they expire?", "type": "chat", "mode_hint": "migration_credits"},
    {"q": "What formula is used to calculate MIGRATION_CREDIT on the first UBP invoice?", "type": "chat", "mode_hint": "migration_credits"},
    {"q": "We were double charged for migration credits this month after upgrading to Enterprise.", "type": "triage", "subj": "Billing Discrepancy on Invoice #UBP-2026-00412", "mode_hint": "migration_credits"},
    {"q": "Our credit window expired yesterday but our migration took longer than scheduled.", "type": "draft", "subj": "Request for extension on migration credit expiration", "mode_hint": "migration_credits"},
    {"q": "Can migration credits be transferred between parent and child organization accounts?", "type": "chat", "mode_hint": "migration_credits"},

    # Category 4: SSO Access & Role Permissions
    {"q": "What permissions does the billing_admin SAML role have?", "type": "chat", "mode_hint": "sso_permissions"},
    {"q": "Can I transfer billing admin privileges to a sub-account user via SAML assertion?", "type": "chat", "mode_hint": "sso_permissions"},
    {"q": "Our SAML assertions are failing following the weekend system update with ERR-4031.", "type": "triage", "subj": "SSO Login Failure ERR-4031", "mode_hint": "sso_permissions"},
    {"q": "How do I re-sync Okta group mappings with the new billing_admin role?", "type": "chat", "mode_hint": "sso_permissions"},

    # Category 5: Custom Plan Addendums & Grace Periods
    {"q": "What happens if a custom plan migration addendum is not signed 7 days before the migration date?", "type": "chat", "mode_hint": "addendum"},
    {"q": "Is there a grace period for auto-renewing annual enterprise licenses if the addendum is pending?", "type": "chat", "mode_hint": "addendum"},
    {"q": "Can enterprise accounts request a 30-day extension on signing custom migration addendums?", "type": "chat", "mode_hint": "addendum"},

    # Category 6: Standard Billing & Operations (Working queries)
    {"q": "What is the new invoice numbering format in the Unified Billing Platform?", "type": "chat", "mode_hint": "invoice_format"},
    {"q": "When is the cutover date for Phase 3 Enterprise accounts?", "type": "chat", "mode_hint": "phase_cutover"},
    {"q": "What is the rate limit for the API token endpoint per client ID?", "type": "chat", "mode_hint": "rate_limit"},
    {"q": "How do I request an invoice receipt for my tax filings?", "type": "chat", "mode_hint": "tax_receipt"},
    {"q": "What is the SLA response time for critical priority outage tickets?", "type": "chat", "mode_hint": "sla"},
    {"q": "Where can I download past payment history CSV files?", "type": "chat", "mode_hint": "payment_history"},
    {"q": "How do I update my payment credit card details on file?", "type": "chat", "mode_hint": "payment_update"}
]


def generate_trace_corpus(total_count: int = 1050):
    print(f"Initializing RAG store to pre-cache queries...")
    settings = get_settings()
    store = VectorStore(settings.chroma_path, settings.collection_name)
    retriever = Retriever(store, top_k=3, min_relevance=0.0)

    # Pre-cache retrieval results for each unique query template to ensure ultra-fast generation
    chunk_cache = {}
    for idx, tmpl in enumerate(QUERY_TEMPLATES):
        q = tmpl.get("q", "")
        subj = tmpl.get("subj", "")
        text = q if q else subj
        retrieved = retriever.retrieve(text, top_k=3, strategy="hybrid")
        chunk_cache[idx] = [
            {
                "chunk_id": c.chunk_id,
                "score": round(c.score, 4),
                "source_file": c.source_file,
                "article_id": c.article_id,
                "ticket_id": c.ticket_id,
                "text_snippet": c.text[:300]
            }
            for c in retrieved
        ]

    start_date = datetime(2026, 8, 1, 9, 0, 0, tzinfo=timezone.utc)
    rng = random.Random(2026)

    print(f"Writing {total_count} trace records to {TRACE_FILE_PATH}...")
    with open(TRACE_FILE_PATH, "w", encoding="utf-8") as f:
        for i in range(1, total_count + 1):
            trace_id = f"tr_{i:04d}"
            tmpl_idx = rng.randint(0, len(QUERY_TEMPLATES) - 1)
            template = QUERY_TEMPLATES[tmpl_idx]
            q_type = template["type"]

            time_offset = timedelta(minutes=rng.randint(0, 45000), seconds=rng.randint(0, 59))
            record_time = (start_date + time_offset).isoformat()

            strategy = rng.choice(["hybrid", "dense", "rerank"])
            top_k = rng.choice([3, 5])
            model_name = "claude-3-5-sonnet-20241022"
            prompt_version = "v1.2-rag-system-prompt"

            question = template.get("q", "")
            subject = template.get("subj", None)
            body = question if q_type != "chat" else None
            tone = "friendly" if q_type == "draft" else None

            formatted_chunks = chunk_cache[tmpl_idx][:top_k]

            system_prompt = prompts.CHAT_SYSTEM
            context_str = "\n\n".join(f"[{c['chunk_id']}]: {c['text_snippet']}" for c in formatted_chunks)
            user_prompt = prompts.CHAT_USER_TEMPLATE.format(
                context=context_str,
                question=question
            )

            mode_hint = template["mode_hint"]
            raw_output = _synthesize_raw_output(mode_hint, question, formatted_chunks, q_type)
            latency_ms = round(rng.uniform(120.0, 380.0), 2)

            record = {
                "trace_id": trace_id,
                "timestamp": record_time,
                "query_type": q_type,
                "question": question,
                "subject": subject,
                "body": body,
                "tone": tone,
                "strategy": strategy,
                "top_k": top_k,
                "prompt_version": prompt_version,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "retrieved_chunks": formatted_chunks,
                "model": model_name,
                "model_params": {"temperature": 0.0, "max_tokens": 1024, "top_p": 1.0},
                "raw_output": raw_output,
                "reconstructed": True,
                "latency_ms": latency_ms,
                "tags": [mode_hint, q_type, strategy]
            }
            f.write(json.dumps(record) + "\n")

    print(f"Successfully generated {total_count} trace records!")


def _synthesize_raw_output(mode_hint: str, question: str, chunks: list, q_type: str) -> str:
    """Synthesize model answers matching actual support assistant trace observations."""
    if mode_hint == "refund_window":
        return (
            "Under our standard customer support terms, you may cancel your subscription and request a full refund "
            "within 30 days of purchase or renewal. Please contact billing support with your invoice ID to initiate processing. [BM-001::p0]"
        )
    elif mode_hint == "error_code":
        if "ERR-4032" in question:
            return (
                "ERR-4032 indicates a general database connection timeout during workspace initialization. "
                "To resolve this, restart your API client container and verify network security group rules. [BM-006::p2]"
            )
        elif "ERR-4031" in question:
            return (
                "ERR-4031 occurs when SAML metadata fails to refresh. Please navigate to Account Settings and re-import your IdP XML file. [BM-005::p1]"
            )
        elif "ERR-4040" in question or "signature verification" in question:
            return (
                "Webhook error ERR-4040 is triggered when the request body payload contains unescaped special characters. "
                "Ensure payload JSON is sanitized before sending. [BM-004::p1]"
            )
        else:
            return f"Error code response based on retrieved candidate chunk: {chunks[0]['chunk_id'] if chunks else 'BM-002'}."
    elif mode_hint == "migration_credits":
        return (
            "Migration credits are calculated using the legacy LBE credit balance formula: `MIGRATION_CREDIT = LBE_credit_balance * 1.5`. "
            "Credits remain valid for 180 days from issuing date. [BM-003::p0]"
        )
    elif mode_hint == "sso_permissions":
        return (
            "The `billing_admin` SAML role permits full read/write access across all user workspaces, security tokens, "
            "and member management sub-accounts. [BM-005::p1]"
        )
    elif mode_hint == "addendum":
        return (
            "If a custom plan migration addendum is not signed 7 days prior to migration, the account is automatically granted a "
            "30-day grace period where legacy pricing remains active. [BM-006::p3]"
        )
    elif mode_hint == "invoice_format":
        return (
            "The new Unified Billing Platform (UBP) invoice numbering format is `UBP-YYYY-NNNNNN` (e.g. UBP-2026-000123). [BM-001::p2]"
        )
    elif mode_hint == "api_header":
        return (
            "The authentication header replacing `X-Billing-Token` for all API calls is `Authorization: Bearer <token>`. [BM-004::p2]"
        )
    elif mode_hint == "tax_receipt":
        return (
            "Invoice receipts for tax filings can be downloaded directly from Billing Settings -> Invoices -> Export Tax PDF. [BM-003::p1]"
        )
    elif mode_hint == "sla":
        return (
            "The SLA response time for critical priority outage tickets is 15 minutes for Enterprise tier accounts. [BM-005::p4]"
        )
    else:
        cid = chunks[0]["chunk_id"] if chunks else "BM-001::p1"
        return f"Based on knowledge base article [{cid}], here is the relevant resolution guidance for your query."


if __name__ == "__main__":
    generate_trace_corpus(1050)
