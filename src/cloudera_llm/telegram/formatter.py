from __future__ import annotations

import html
import re
from dataclasses import dataclass

from cloudera_llm.vectorstore.store import RetrievedChunk

DISCLAIMER = (
    "Informasi berdasarkan knowledge base Cloudera & runbook internal. "
    "Verifikasi di environment sebelum eksekusi perubahan produksi."
)

SECTION_HEADERS = ("RINGKASAN:", "LANGKAH:", "CATATAN:", "KETERBATASAN:")


@dataclass
class FormattedAnswer:
    html: str
    confidence: str


def format_telegram_answer(
    answer: str,
    sources: list[RetrievedChunk],
    *,
    model: str = "",
) -> FormattedAnswer:
    confidence = _confidence_label(sources)
    body = _answer_to_html(answer.strip())
    source_block = _format_sources(sources)
    footer = _format_footer(confidence, model)

    parts = [
        f"<b>Cloudera Assistant</b>  ·  {html.escape(confidence)}",
        "",
        body,
        "",
        source_block,
        "",
        f"<i>{html.escape(DISCLAIMER)}</i>",
        footer,
    ]
    return FormattedAnswer(html="\n".join(parts), confidence=confidence)


def _confidence_label(sources: list[RetrievedChunk]) -> str:
    if not sources:
        return "Confidence: Low"
    avg = sum(source.score for source in sources) / len(sources)
    if avg >= 0.72:
        return "Confidence: High"
    if avg >= 0.55:
        return "Confidence: Medium"
    return "Confidence: Low"


def _answer_to_html(answer: str) -> str:
    lines = answer.splitlines()
    output: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                output.append("")
                in_list = False
            continue

        header = _match_section_header(stripped)
        if header:
            if in_list:
                output.append("")
                in_list = False
            output.append(f"<b>{html.escape(header)}</b>")
            continue

        numbered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if numbered:
            content = _inline_format(html.escape(numbered.group(2)))
            output.append(f"{numbered.group(1)}. {content}")
            in_list = True
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            content = _inline_format(html.escape(bullet.group(1)))
            output.append(f"• {content}")
            in_list = True
            continue

        if in_list:
            output.append("")
            in_list = False
        output.append(_inline_format(html.escape(stripped)))

    return "\n".join(output)


def _match_section_header(line: str) -> str | None:
    upper = line.upper().rstrip(":")
    for header in SECTION_HEADERS:
        name = header.rstrip(":")
        if upper == name or line.upper().startswith(header):
            return name.title()
    return None


def _inline_format(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[Source (\d+)\]", r"<i>[Source \1]</i>", text)
    return text


def _format_sources(sources: list[RetrievedChunk]) -> str:
    if not sources:
        return "<b>Referensi</b>\nTidak ada sumber relevan ditemukan."

    lines = ["<b>Referensi</b>"]
    for index, source in enumerate(sources[:5], start=1):
        label = html.escape(source.title or "Untitled")
        meta_parts = [part for part in (source.product, source.version, source.service) if part]
        meta = f" — {html.escape(', '.join(meta_parts))}" if meta_parts else ""
        score = f" ({source.score:.0%})"
        url = source.source_url
        if url.startswith("http"):
            lines.append(
                f'{index}. <a href="{html.escape(url, quote=True)}">{label}</a>{meta}{score}'
            )
        else:
            doc_name = html.escape(url.replace("local://", ""))
            lines.append(f"{index}. {label}{meta}{score}\n   <code>{doc_name}</code>")
    return "\n".join(lines)


def _format_footer(confidence: str, model: str) -> str:
    if not model:
        return ""
    return f"\n<i>{html.escape(confidence)} · {html.escape(model)}</i>"
