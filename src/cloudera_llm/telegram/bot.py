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
from cloudera_llm.telegram.formatter import format_telegram_answer
from cloudera_llm.telegram.prompts import TELEGRAM_SYSTEM_PROMPT
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
        "<b>Cloudera Assistant</b>\n"
        "<i>Enterprise RAG · Docs &amp; Runbook</i>\n\n"
        "Asisten untuk pertanyaan seputar Cloudera Platform, Data Services, "
        "dan prosedur operasional (SOP/MOP).\n\n"
        "<b>Perintah</b>\n"
        "/health — status knowledge base &amp; LLM\n"
        "/ask &lt;pertanyaan&gt; — ajukan pertanyaan\n\n"
        "<b>Contoh</b>\n"
        "<code>/ask langkah restart Impala services</code>\n"
        "<code>/ask support matrix CDW untuk RHEL 9</code>\n\n"
        "Atau ketik pertanyaan langsung. Jawaban disertai referensi sumber.",
        parse_mode=ParseMode.HTML,
    )


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id if update.effective_chat else None):
        await _reply_unauthorized(update)
        return

    store = VectorStore()
    llm = LLMClient()
    llm_ok = llm.health_check()
    status = "Operational" if llm_ok and store.count() > 0 else "Degraded"

    text = (
        "<b>Cloudera Assistant — Health Check</b>\n\n"
        f"Status: <code>{status}</code>\n"
        f"Knowledge vectors: <code>{store.count()}</code>\n"
        f"LLM backend: <code>{'reachable' if llm_ok else 'unreachable'}</code>\n"
        f"Endpoint: <code>{html.escape(llm.config.llm.base_url)}</code>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id if update.effective_chat else None):
        await _reply_unauthorized(update)
        return

    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text(
            "Format: <code>/ask &lt;pertanyaan&gt;</code>\n"
            "Contoh: <code>/ask cara failover HDFS dan YARN</code>",
            parse_mode=ParseMode.HTML,
        )
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
            "<b>Knowledge base belum tersedia</b>\n\n"
            "Jalankan ingest terlebih dahulu:\n"
            "<code>cloudera-ingest --source all</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if not pipeline.llm.health_check():
        await update.message.reply_text(
            "<b>LLM backend tidak tersedia</b>\n\n"
            "Pastikan gemini-web2api berjalan di:\n"
            "<code>http://127.0.0.1:8081/v1</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        result = await asyncio.to_thread(
            pipeline.ask,
            question,
            system_prompt=TELEGRAM_SYSTEM_PROMPT,
        )
        formatted = format_telegram_answer(
            result.answer,
            result.sources,
            model=result.model,
        )
        await _reply(update, formatted.html)
    except Exception as exc:
        logger.exception("Telegram RAG failed")
        await update.message.reply_text(
            "<b>Permintaan tidak dapat diproses</b>\n\n"
            f"Detail: <code>{html.escape(str(exc))}</code>\n\n"
            "Silakan coba lagi atau hubungi administrator.",
            parse_mode=ParseMode.HTML,
        )


async def _reply_unauthorized(update: Update) -> None:
    if update.message is None:
        return
    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    await update.message.reply_text(
        "<b>Akses ditolak</b>\n\n"
        f"Chat ID <code>{chat_id}</code> belum terdaftar.\n"
        "Hubungi administrator untuk menambahkan ke "
        "<code>TELEGRAM_ALLOWED_CHAT_IDS</code>.",
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
