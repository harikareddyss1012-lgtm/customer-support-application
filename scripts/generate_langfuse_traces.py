"""Generate and flush 25 real customer support RAG traces to Langfuse Cloud.

Usage:
    python scripts/generate_langfuse_traces.py
"""

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure Langfuse environment variables are loaded
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-5cb1d9fa-0e67-489a-88f9-40a50714f10a"
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-42063044-c0f3-4804-b967-101052e1e037"
os.environ["LANGFUSE_HOST"] = "https://cloud.langfuse.com"

from langfuse import Langfuse
from app.config import get_settings
from app.retrieval.vector_store import VectorStore
from app.retrieval.retriever import Retriever
from app.generation.answerer import Answerer


SAMPLE_QUERIES = [
    # 1. Billing & Error codes
    {"type": "chat", "question": "What does error code ERR-4032 mean and what is the fix?", "strategy": "hybrid"},
    {"type": "chat", "question": "What steps fix ERR-4031 after SSO mapping breaks?", "strategy": "dense"},
    {"type": "chat", "question": "What error code is generated when a signature verification fails on a webhook endpoint after migration?", "strategy": "rerank"},
    {"type": "chat", "question": "What happens when an account gets locked during data transfer with code ERR-4030?", "strategy": "hybrid"},
    {"type": "chat", "question": "How long do migration credits last and what happens when they expire?", "strategy": "hybrid"},
    {"type": "chat", "question": "What is the new invoice numbering format in the Unified Billing Platform?", "strategy": "dense"},
    {"type": "chat", "question": "What authentication header replaces X-Billing-Token for API calls?", "strategy": "rerank"},
    {"type": "chat", "question": "What permissions does the billing_admin SAML role have?", "strategy": "hybrid"},
    {"type": "chat", "question": "When is the cutover date for Phase 3 Enterprise accounts?", "strategy": "hybrid"},
    {"type": "chat", "question": "What formula is used to calculate MIGRATION_CREDIT on the first UBP invoice?", "strategy": "rerank"},
    {"type": "chat", "question": "What is the rate limit for the API token endpoint per client ID?", "strategy": "dense"},
    {"type": "chat", "question": "What happens if a custom plan migration addendum is not signed 7 days before the migration date?", "strategy": "hybrid"},
    
    # 2. Support tickets & refund/policy queries
    {"type": "chat", "question": "What is your refund policy if I want to cancel my subscription after 30 days?", "strategy": "hybrid"},
    {"type": "chat", "question": "How do I request an invoice receipt for my tax filings?", "strategy": "dense"},
    {"type": "chat", "question": "My webhook events are failing with 401 Unauthorized, how do I re-authenticate?", "strategy": "rerank"},
    {"type": "chat", "question": "Can I transfer billing admin privileges to a sub-account user?", "strategy": "hybrid"},
    {"type": "chat", "question": "What is the SLA response time for critical priority outage tickets?", "strategy": "hybrid"},
    
    # 3. Triage & Draft Reply scenarios
    {"type": "triage", "subject": "Billing Discrepancy on Invoice #UBP-2026-00412", "body": "We were double charged for migration credits this month after upgrading to Enterprise."},
    {"type": "triage", "subject": "SSO Login Failure ERR-4031", "body": "Our SAML assertions are failing following the weekend system update."},
    {"type": "triage", "subject": "Webhook Signature Verification Error ERR-4040", "body": "All our inbound webhooks return HTTP 400 signature verification failed since 9am."},
    {"type": "draft", "subject": "Request for extension on migration credit expiration", "body": "Our credit window expired yesterday but our migration took longer than scheduled.", "tone": "empathetic"},
    {"type": "draft", "subject": "Rate limit exceeded on token API", "body": "Our automated ETL pipeline is hitting rate limits during batch processing.", "tone": "formal"},
    {"type": "chat", "question": "Where can I download past payment history CSV files?", "strategy": "dense"},
    {"type": "chat", "question": "Is there a grace period for auto-renewing annual enterprise licenses?", "strategy": "hybrid"},
    {"type": "chat", "question": "How do I update my payment credit card details on file?", "strategy": "hybrid"},
]


def main():
    print("Initializing RAG components...")
    settings = get_settings()
    store = VectorStore(settings.chroma_path, settings.collection_name)
    retriever = Retriever(store, top_k=3, min_relevance=0.0)
    answerer = Answerer(retriever)

    lf = Langfuse()

    print(f"Generating {len(SAMPLE_QUERIES)} real traces to Langfuse...")
    for idx, item in enumerate(SAMPLE_QUERIES, 1):
        q_type = item.get("type", "chat")
        try:
            if q_type == "chat":
                print(f"[{idx}/{len(SAMPLE_QUERIES)}] Chat: {item['question'][:50]}...")
                answerer.answer(question=item["question"], top_k=3, strategy=item.get("strategy", "hybrid"))
            elif q_type == "triage":
                print(f"[{idx}/{len(SAMPLE_QUERIES)}] Triage: {item['subject']}...")
                answerer.triage(subject=item["subject"], body=item["body"])
            elif q_type == "draft":
                print(f"[{idx}/{len(SAMPLE_QUERIES)}] Draft Reply: {item['subject']}...")
                answerer.draft_reply(subject=item["subject"], body=item["body"], tone=item.get("tone", "friendly"))
        except Exception as exc:
            print(f"  Warning: request {idx} raised: {exc}")
        
        time.sleep(0.1)

    print("Flushing traces to Langfuse Cloud...")
    lf.flush()
    print("All traces successfully flushed!")


if __name__ == "__main__":
    main()
