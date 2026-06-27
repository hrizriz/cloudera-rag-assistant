from __future__ import annotations

import asyncio
import html
import logging
import re
from functools import lru_cache

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from cloudera_llm.config import get_telegram_settings
from cloudera_llm.llm.client import LLMClient
from cloudera_llm.rag.pipeline import RAGPipeline
from cloudera_llm.vectorstore.store import VectorStore

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4096
_pipeline: RAGPipeline | None = None


def _get_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RAGPipeline(store=VectorStore(), llm=LLMClient())
    return _pipeline


@lru_cache
def _allowed_chat_ids() -> frozenset[int]:
    return frozenset(get_telegram_settings().allowed_chat_ids())


def _is_authorized(chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    allowed = _allowed_chat_ids()
    if not allowed:
        return True
    return chat_id in allowed


def _split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return parts


def _format_answer(result) -> str:
    lines = [html.escape(result.answer.strip()), "", "<b>Sumber:</b>"]
    for index, source in enumerate(result.sources[:5], start=1):
        label = html.escape(source.title or "Untitled")
        meta = []
        if source.product:
            meta.append(html.escape(source.product))
        if source.version:
            meta.append(html.escape(source.version))
        if source.service:
            meta.append(html.escape(source.service))
        meta_text = f" ({', '.join(meta)})" if meta else ""
        url = source.source_url
        if url.startswith("http"):
            lines.append(f'{index}. <a href="{html.escape(url, quote=True)}">{label}</a>{meta_text}')
        else:
            lines.append(f"{index}. {label}{meta_text}")
    lines.append(f"\n<i>Model: {html.escape(result.model)}</i>")
    return "\n".join(lines)


async def _reply(update: Update, text: str) -> None:
    if update.message is None:
        return
    for chunk in _split_message(text):
        try:
            await update.message.reply_text(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            await update.message.reply_text(re.sub(r"<[^>]+>", "", chunk))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id if update.effective_chat else None):
        await _reply_unauthorized(update)
        return

    await update.message.reply_text(
        "Halo! Saya <b>Cloudera LLM Assistant</b>.\n\n"
        "Kirim pertanyaan seputar Cloudera (CDP, Impala, Hive, CDW, CDE, CML, NiFi, dll).\n\n"
        "Perintah:\n"
        "/health — cek status knowledge base &amp; LLM\n"
        "/ask &lt;pertanyaan&gt; — tanya Cloudera\n\n"
        "Atau langsung ketik pertanyaanmu.",
        parse_mode=ParseMode.HTML,
    )


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id if update.effective_chat else None):
        await _reply_unauthorized(update)
        return

    llm = LLMClient()
    text = (
        "<b>Status Cloudera LLM</b>\n\n"
        f"Vectors: <code>{store.count()}</code>\n"
        f"LLM reachable: <code>{'yes' if llm.health_check() else 'no'}</code>\n"
        f"gemini-web2api: <code>{html.escape(llm.config.llm.base_url)}</code>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id if update.effective_chat else None):
        await _reply_unauthorized(update)
        return

    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Format: /ask Apa perbedaan Impala dan Hive?")
        return
    await _handle_question(update, question)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not update.message.text:
        return
    if not _is_authorized(update.effective_chat.id if update.effective_chat else None):
        await _reply_unauthorized(update)
        return

    text = update.message.text.strip()
    if text.startswith("/"):
        return
    await _handle_question(update, text)


async def _handle_question(update: Update, question: str) -> None:
    if update.message is None:
        return

    pipeline = _get_pipeline()
    if pipeline.store.count() == 0:
        await update.message.reply_text(
            "Knowledge base masih kosong. Jalankan ingest dulu:\n"
            "`cloudera-ingest --source all`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not pipeline.llm.health_check():
        await update.message.reply_text(
            "LLM tidak reachable. Pastikan gemini-web2api jalan di 127.0.0.1:8081 "
            "(jangan pakai localhost — bisa kena service lain di Windows)."
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        result = await asyncio.to_thread(pipeline.ask, question)
        await _reply(update, _format_answer(result))
    except Exception as exc:
        logger.exception("Telegram RAG failed")
        await update.message.reply_text(f"Error: {exc}")


async def _reply_unauthorized(update: Update) -> None:
    if update.message is None:
        return
    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    await update.message.reply_text(
        f"Chat ID <code>{chat_id}</code> belum diizinkan.\n"
        "Tambahkan ke <code>TELEGRAM_ALLOWED_CHAT_IDS</code> di file <code>.env</code>.",
        parse_mode=ParseMode.HTML,
    )


def run_bot() -> None:
    settings = get_telegram_settings()
    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN belum diset. Copy .env.example ke .env dan isi token bot Telegram."
        )

    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        level=logging.INFO,
    )

    allowed = settings.allowed_chat_ids()
    if allowed:
        logger.info("Allowed chat IDs: %s", allowed)
    else:
        logger.warning("TELEGRAM_ALLOWED_CHAT_IDS kosong — semua chat bisa akses bot")

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Cloudera Telegram bot started (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
