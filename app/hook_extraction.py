from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pypdf import PdfReader

_URL_PATTERN = re.compile(r"https?://\S+")
_QUERY_FRAGMENT_PATTERN = re.compile(r"^(?:[?&].+|(?:igsh|utm_[a-z_]+|h)=[^\s]+)$", re.IGNORECASE)
_HEADER_LINES = {
    "1000 VIRAL HOOKS",
}
_TRACKING_QUERY_KEYS = {
    "igsh",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_id",
    "utm_term",
    "utm_content",
}


@dataclass(frozen=True)
class HookRecord:
    id: str
    hook_text: str
    source_url: str | None
    page_number: int
    section: str | None


def _normalize_text(text: str) -> str:
    replacements = {
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_hook_text(text: str) -> str:
    text = _normalize_text(text)
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"^(?:[A-Z][A-Z ]{0,20}HOOK:\s*)", "", text)
    text = re.sub(r"^[\s\-\u2022:;,.!?]+", "", text)
    text = re.sub(r"[\s\-\u2022:;,.!?]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_section_heading(text: str) -> bool:
    compact = _normalize_text(text)
    if not compact or compact in _HEADER_LINES:
        return False
    if len(compact) > 40:
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z /&-]{2,39}", compact))


def _normalize_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None

    url = _normalize_text(raw_url)
    url = url.rstrip(").,;]")

    match = re.search(r"https?://\S+", url)
    if not match:
        return url or None
    url = match.group(0)

    parts = urlsplit(url)
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")
    ]
    normalized_query = "&".join(
        f"{key}={value}" if value else key
        for key, value in query_pairs
    )
    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path, normalized_query, ""))
    if parts.path and not normalized.endswith("/") and not normalized_query:
        normalized = f"{normalized}/"
    return normalized or None


def _split_line_chunks(line: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    last_end = 0
    for match in _URL_PATTERN.finditer(line):
        if match.start() > last_end:
            text = line[last_end:match.start()]
            if text.strip():
                chunks.append(("text", text))
        chunks.append(("url", match.group(0)))
        last_end = match.end()
    if last_end < len(line):
        tail = line[last_end:]
        if tail.strip():
            chunks.append(("text", tail))
    if not chunks and line.strip():
        chunks.append(("text", line))
    return chunks


def _iter_page_lines(page_text: str) -> Iterable[str]:
    for raw_line in page_text.splitlines():
        line = _normalize_text(raw_line)
        if line:
            yield line


def extract_hooks_from_pages(page_texts: Sequence[str]) -> list[HookRecord]:
    records: list[dict[str, object]] = []
    current_text_parts: list[str] = []
    current_urls: list[str] = []
    current_page_number: int | None = None
    current_section: str | None = None

    def flush_current() -> None:
        nonlocal current_text_parts, current_urls, current_page_number

        if current_page_number is None:
            current_text_parts = []
            current_urls = []
            return

        hook_text = _clean_hook_text(" ".join(current_text_parts))
        source_url = _normalize_url(current_urls[0]) if current_urls else None

        if len(hook_text) >= 8 and "http" not in hook_text.lower():
            records.append(
                {
                    "hook_text": hook_text,
                    "source_url": source_url,
                    "page_number": current_page_number,
                    "section": current_section,
                }
            )

        current_text_parts = []
        current_urls = []
        current_page_number = None

    for page_number, page_text in enumerate(page_texts, start=1):
        for line in _iter_page_lines(page_text):
            if line in _HEADER_LINES:
                continue

            if _is_section_heading(line):
                flush_current()
                current_section = line
                continue

            if current_urls and _QUERY_FRAGMENT_PATTERN.fullmatch(line):
                current_urls[-1] = f"{current_urls[-1]}{line}"
                continue

            chunks = _split_line_chunks(line)
            for chunk_kind, chunk_value in chunks:
                if chunk_kind == "url":
                    if current_page_number is None and records:
                        # Attach late URLs to the current in-flight record only.
                        continue
                    if current_page_number is None:
                        current_page_number = page_number
                    current_urls.append(chunk_value)
                    continue

                text_value = _clean_hook_text(chunk_value)
                if not text_value:
                    continue

                if current_urls:
                    flush_current()

                if current_page_number is None:
                    current_page_number = page_number
                current_text_parts.append(text_value)

    flush_current()

    deduped: list[HookRecord] = []
    seen: set[tuple[str, str | None]] = set()
    for index, record in enumerate(records, start=1):
        hook_text = str(record["hook_text"])
        source_url = record["source_url"]
        key = (re.sub(r"\s+", " ", hook_text).strip().lower(), source_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            HookRecord(
                id=f"hook_{index:04d}",
                hook_text=hook_text,
                source_url=source_url,
                page_number=int(record["page_number"]),
                section=record["section"] if isinstance(record["section"], str) else None,
            )
        )

    renumbered: list[HookRecord] = []
    for index, record in enumerate(deduped, start=1):
        renumbered.append(
            HookRecord(
                id=f"hook_{index:04d}",
                hook_text=record.hook_text,
                source_url=record.source_url,
                page_number=record.page_number,
                section=record.section,
            )
        )
    return renumbered


def extract_hooks_from_pdf(pdf_path: Path | str) -> list[HookRecord]:
    reader = PdfReader(str(pdf_path))
    page_texts = [(page.extract_text() or "") for page in reader.pages]
    return extract_hooks_from_pages(page_texts)


def write_hooks_json(records: Sequence[HookRecord], output_path: Path | str) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(record) for record in records]
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract hook templates from a PDF into JSON.")
    parser.add_argument("input_pdf", type=Path, help="Path to the source PDF")
    parser.add_argument("output_json", type=Path, help="Path to write the normalized JSON output")
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    records = extract_hooks_from_pdf(args.input_pdf)
    write_hooks_json(records, args.output_json)
    print(f"Extracted {len(records)} hooks to {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
