"""Read tickets out of `documents/` — JSON, JSONL, CSV, or Markdown."""

from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterator

from pydantic import ValidationError

from ..schemas import Ticket

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {
    ".json", ".jsonl", ".csv", ".md", ".pdf", ".docx", ".doc",
    ".txt", ".py", ".html", ".xml", ".log", ".rst", ".yaml", ".yml", ".tsv"
}

# Documentation and dotfiles living alongside the data are not tickets.
IGNORED_STEMS = {"readme", "index", "notes"}

# Aliases so a CSV/JSON export from Zendesk, Freshdesk, etc. loads without editing.
FIELD_ALIASES: dict[str, str] = {
    "ticket_id": "id",
    "number": "id",
    "title": "subject",
    "summary": "subject",
    "description": "body",
    "message": "body",
    "text": "body",
    "requester": "customer",
    "customer_name": "customer",
    "type": "category",
    "severity": "priority",
    "state": "status",
    "answer": "resolution",
    "resolution_notes": "resolution",
    "created": "created_at",
    "opened_at": "created_at",
}


def load_tickets(documents_dir: Path) -> tuple[list[Ticket], int]:
    """Load every supported file in `documents_dir`.

    Returns (tickets, files_read). Malformed records are logged and skipped rather
    than failing the whole ingest — a single bad row shouldn't block the index.
    """
    if not documents_dir.exists():
        raise FileNotFoundError(f"documents directory not found: {documents_dir}")

    tickets: list[Ticket] = []
    seen_ids: set[str] = set()
    files_read = 0

    for path in sorted(documents_dir.rglob("*")):
        if not _is_ticket_file(path):
            continue
        files_read += 1
        for raw in _read_file(path):
            ticket = _coerce(raw, source=path)
            if ticket is None:
                continue
            if ticket.id in seen_ids:
                logger.warning("duplicate ticket id %s in %s — skipping", ticket.id, path.name)
                continue
            seen_ids.add(ticket.id)
            tickets.append(ticket)

    logger.info("loaded %d tickets from %d files", len(tickets), files_read)
    return tickets, files_read


def _is_ticket_file(path: Path) -> bool:
    """Whether a path holds ticket or document data.

    Skips dotfiles and hidden directories.
    """
    if not path.is_file():
        return False
    if path.name.startswith((".", "_")):
        return False
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_SUFFIXES or not suffix:
        return True
    return False


def _read_file(path: Path) -> Iterator[dict[str, Any]]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            records = payload.get("tickets", []) if isinstance(payload, dict) else payload
            if isinstance(records, dict):
                records = [records]
            if isinstance(records, list):
                yield from (r for r in records if isinstance(r, dict))
            else:
                yield {
                    "id": f"UP-{path.stem}",
                    "subject": path.stem.replace("-", " ").replace("_", " ").title(),
                    "body": json.dumps(payload, indent=2),
                    "source_file": path.name,
                }
        elif suffix == ".jsonl":
            for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        yield data
                except json.JSONDecodeError as exc:
                    logger.warning("%s:%d — bad JSON line: %s", path.name, line_no, exc)
        elif suffix == ".csv":
            with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
                yield from csv.DictReader(fh)
        elif suffix == ".md":
            yield _parse_markdown(path)
        elif suffix == ".pdf":
            yield _read_pdf(path)
        elif suffix in (".docx", ".doc"):
            yield _read_docx(path)
        else:
            yield _read_txt(path)
    except Exception as exc:
        logger.error("could not read %s: %s", path, exc)


def _read_pdf(path: Path) -> dict[str, Any]:
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        text = "\n\n".join([page.extract_text() or "" for page in reader.pages])
        return {
            "id": f"UP-{path.stem}",
            "subject": path.stem.replace("-", " ").replace("_", " ").title(),
            "body": text.strip() or f"Document {path.name}",
            "source_file": path.name,
            "article_id": f"UP-{path.stem}",
        }
    except Exception as exc:
        logger.error("Could not read PDF %s: %s", path, exc)
        return {"id": f"UP-{path.stem}", "subject": path.stem, "body": f"PDF document {path.name}", "source_file": path.name}


def _read_docx(path: Path) -> dict[str, Any]:
    try:
        import docx
        doc = docx.Document(str(path))
        text = "\n\n".join([p.text for p in doc.paragraphs if p.text])
        return {
            "id": f"UP-{path.stem}",
            "subject": path.stem.replace("-", " ").replace("_", " ").title(),
            "body": text.strip() or f"Document {path.name}",
            "source_file": path.name,
            "article_id": f"UP-{path.stem}",
        }
    except Exception as exc:
        logger.error("Could not read DOCX %s: %s", path, exc)
        return {"id": f"UP-{path.stem}", "subject": path.stem, "body": f"DOCX document {path.name}", "source_file": path.name}


def _read_txt(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return {
            "id": f"UP-{path.stem}",
            "subject": path.stem.replace("-", " ").replace("_", " ").title(),
            "body": text.strip() or f"Document {path.name}",
            "source_file": path.name,
            "article_id": f"UP-{path.stem}",
        }
    except Exception as exc:
        logger.error("Could not read text file %s: %s", path, exc)
        return {"id": f"UP-{path.stem}", "subject": path.stem, "body": f"Text document {path.name}", "source_file": path.name}


def _parse_markdown(path: Path) -> dict[str, Any]:
    """Treat a Markdown file as one ticket/article: `# Subject` then body, `key: value` front matter."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    record: dict[str, Any] = {"id": path.stem, "source_file": path.name}

    if match := re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL):
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                record[key.strip()] = value.strip()
        text = text[match.end() :]

    if heading := re.search(r"^#\s+(.+)$", text, re.MULTILINE):
        record.setdefault("subject", heading.group(1).strip())
        text = text[heading.end() :]

    record.setdefault("subject", path.stem.replace("-", " ").replace("_", " ").title())
    record["body"] = text.strip()
    if "article_id" in record:
        record["id"] = record["article_id"]
    return record


def _coerce(raw: dict[str, Any], source: Path) -> Ticket | None:
    """Normalise arbitrary keys onto the Ticket schema."""
    normalised: dict[str, Any] = {}
    for key, value in raw.items():
        if value in (None, ""):
            continue
        canonical = FIELD_ALIASES.get(key.strip().lower(), key.strip().lower())
        normalised[canonical] = value

    if isinstance(normalised.get("tags"), str):
        normalised["tags"] = [t.strip() for t in normalised["tags"].split(",") if t.strip()]

    for enum_field in ("category", "priority", "status"):
        if isinstance(normalised.get(enum_field), str):
            normalised[enum_field] = normalised[enum_field].strip().lower()

    if not normalised.get("id"):
        normalised["id"] = normalised.get("article_id") or f"UP-{source.stem}"

    normalised["id"] = str(normalised["id"])
    normalised.setdefault("subject", source.stem.replace("-", " ").replace("_", " ").title())
    normalised.setdefault("body", f"Document {source.name}")
    normalised.setdefault("source_file", source.name)

    try:
        return Ticket(**normalised)
    except ValidationError as exc:
        logger.warning("ticket %s in %s failed validation: %s", normalised["id"], source.name, exc)
        return None

