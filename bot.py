import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ChatMemberHandler, filters
import re

from config import settings
from commands import (
    cmd_start_entry,
    cmd_start,
    cmd_stop,
    cmd_pause,
    cmd_status,
    cmd_set_lang,
    cmd_list_groups,
    cmd_remove_group,
    cmd_set_broadcaster,
    cmd_unset_broadcaster,
    cmd_list_broadcasters,
    cmd_stats,
    cmd_preview,
    cmd_authorize,
    cmd_unauthorize,
    cmd_list_controllers,
    cmd_check_groups,
    handle_group_message,
    handle_private_message,
    on_chat_member_update,
)

load_dotenv()

Path("data").mkdir(exist_ok=True)
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("tg-bot")
# handler = RotatingFileHandler(settings.LOG_FILE, maxBytes=2_000_000, backupCount=3)
# formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
# handler.setFormatter(formatter)
# logging.getLogger().addHandler(handler)

async def error_handler(update, context):
    logger.exception("Unhandled error: %s", context.error)

def main():
    logger.info("Starting bot...")
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_error_handler(error_handler)

    async def cn_start(update, context):
        await cmd_start(update, context)
    async def cn_stop(update, context):
        await cmd_stop(update, context)
    async def cn_status(update, context):
        await cmd_status(update, context)

    app.add_handler(CommandHandler("start", cmd_start_entry))
    app.add_handler(MessageHandler(filters.Regex(r"^/开始(?:\s|$)"), cn_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.Regex(r"^/停止(?:\s|$)"), cn_stop))
    app.add_handler(MessageHandler(filters.Regex(r"^/停止翻译(?:\s|$)"), cn_stop))
    # Add English aliases for pause/resume logic
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_start))
    
    # Telegram CommandHandler does not support non-latin characters as standard command in some versions or strict mode?
    # Actually it should work, but let's use MessageHandler with Regex for Chinese commands to be safe and consistent.
    app.add_handler(MessageHandler(filters.Regex(r"^/暂停(?:\s|$)"), cmd_pause))
    app.add_handler(MessageHandler(filters.Regex(r"^/开始(?:\s|$)"), cmd_start))
    
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.Regex(r"^/状态(?:\s|$)"), cn_status))
    app.add_handler(CommandHandler("set_lang", cmd_set_lang))

    async def cn_list_groups(update, context):
        await cmd_list_groups(update, context)

    async def cn_remove_group(update, context):
        text = update.effective_message.text or ""
        m = re.match(r"^/移除群\s+(-?\d+)$", text.strip())
        if not m:
            await update.effective_message.reply_text("用法: /移除群 <chat_id>")
            return
        context.args = [m.group(1)]
        await cmd_remove_group(update, context)

    async def cn_set_broadcaster(update, context):
        text = update.effective_message.text or ""
        m = re.match(r"^/授权广播员\s+@([A-Za-z0-9_]{5,})$", text.strip())
        if not m:
            await update.effective_message.reply_text("用法: /授权广播员 @username")
            return
        context.args = [f"@{m.group(1)}"]
        await cmd_set_broadcaster(update, context)

    async def cn_unset_broadcaster(update, context):
        text = (update.effective_message.text or "").strip()
        m_user = re.match(r"^/取消广播员\s+@([A-Za-z0-9_]{5,})$", text)
        m_id = re.match(r"^/取消广播员\s+(\d+)$", text)
        if m_user:
            context.args = [f"@{m_user.group(1)}"]
        elif m_id:
            context.args = [m_id.group(1)]
        else:
            await update.effective_message.reply_text("用法: /取消广播员 @username 或 /取消广播员 <user_id>")
            return
        await cmd_unset_broadcaster(update, context)

    async def cn_list_broadcasters(update, context):
        await cmd_list_broadcasters(update, context)

    async def cn_stats(update, context):
        await cmd_stats(update, context)

    async def cn_preview(update, context):
        text = (update.effective_message.text or "").strip()
        m = re.match(r"^/预览\s+(-?\d+)\s+(.+)$", text, re.S)
        if not m:
            await update.effective_message.reply_text("用法: /预览 <chat_id> <message>")
            return
        context.args = [m.group(1), m.group(2)]
        await cmd_preview(update, context)

    app.add_handler(CommandHandler("list_groups", cmd_list_groups))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/群列表(?:\s|$)"), cn_list_groups))
    app.add_handler(CommandHandler("remove_group", cmd_remove_group))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/移除群\b"), cn_remove_group))
    app.add_handler(CommandHandler("set_broadcaster", cmd_set_broadcaster))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/授权广播员(?:\s|$)"), cn_set_broadcaster))
    app.add_handler(CommandHandler("unset_broadcaster", cmd_unset_broadcaster))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/取消广播员(?:\s|$)"), cn_unset_broadcaster))
    app.add_handler(CommandHandler("list_broadcasters", cmd_list_broadcasters))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/广播员列表(?:\s|$)"), cn_list_broadcasters))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/统计(?:\s|$)"), cn_stats))
    app.add_handler(CommandHandler("preview", cmd_preview))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/预览(?:\s|$)"), cn_preview))

    async def cn_authorize(update, context):
        text = (update.effective_message.text or "").strip()
        m_user = re.match(r"^/授权\s+@([A-Za-z0-9_]{5,})$", text)
        m_id = re.match(r"^/授权\s+(\d+)$", text)
        if m_user:
            context.args = [f"@{m_user.group(1)}"]
        elif m_id:
            context.args = [m_id.group(1)]
        else:
            await update.effective_message.reply_text("用法: /授权 @username 或 /授权 <user_id>")
            return
        await cmd_authorize(update, context)

    async def cn_unauthorize(update, context):
        text = (update.effective_message.text or "").strip()
        m_user = re.match(r"^/取消授权\s+@([A-Za-z0-9_]{5,})$", text)
        m_id = re.match(r"^/取消授权\s+(\d+)$", text)
        if m_user:
            context.args = [f"@{m_user.group(1)}"]
        elif m_id:
            context.args = [m_id.group(1)]
        else:
            await update.effective_message.reply_text("用法: /取消授权 @username 或 /取消授权 <user_id>")
            return
        await cmd_unauthorize(update, context)

    async def cn_list_controllers(update, context):
        await cmd_list_controllers(update, context)

    app.add_handler(CommandHandler("authorize", cmd_authorize))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/授权(?:\s|$)"), cn_authorize))
    app.add_handler(CommandHandler("unauthorize", cmd_unauthorize))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/取消授权(?:\s|$)"), cn_unauthorize))
    app.add_handler(CommandHandler("list_controllers", cmd_list_controllers))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/授权列表(?:\s|$)"), cn_list_controllers))

    app.add_handler(CommandHandler("list_groups", cmd_list_groups))
    app.add_handler(CommandHandler("remove_group", cmd_remove_group))
    app.add_handler(CommandHandler("set_broadcaster", cmd_set_broadcaster))
    app.add_handler(CommandHandler("unset_broadcaster", cmd_unset_broadcaster))
    app.add_handler(CommandHandler("list_broadcasters", cmd_list_broadcasters))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("preview", cmd_preview))
    
    async def cn_check_groups(update, context):
        await cmd_check_groups(update, context)
    
    app.add_handler(CommandHandler("check_groups", cmd_check_groups))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^/检查群组(?:\s|$)"), cn_check_groups))

    # Ensure this catch-all handler does NOT catch commands
    # filters.TEXT includes commands by default in some versions, but usually CommandHandler takes precedence if matched.
    # However, if CommandHandler doesn't match (e.g. /pause not registered), it falls here.
    # We explicitly exclude filters.COMMAND to avoid processing unknown commands as text to translate.
    # Also exclude strings starting with "/" to be safe against non-standard commands.
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, handle_group_message))
    
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.Regex(r"^/"), handle_private_message))

    app.add_handler(ChatMemberHandler(on_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))

    app.run_polling(allowed_updates=["message", "chat_member", "my_chat_member"], close_loop=False)

if __name__ == "__main__":
    main()
