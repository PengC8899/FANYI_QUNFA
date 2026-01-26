import asyncio
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import logging
import re

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatType
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from config import settings
from storage import Storage
from utils import detect_language, sanitize_text, parse_username, detect_at_username
from translator import Translator, HttpTranslator, FallbackTranslator

storage = Storage(settings.DB_PATH)
logger = logging.getLogger("tg-bot")

async def _ensure_translator() -> Translator:
    if settings.TRANSLATE_API and settings.TRANSLATE_API_KEY:
        return HttpTranslator(settings.TRANSLATE_API, settings.TRANSLATE_API_KEY)
    return FallbackTranslator()

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat = update.effective_chat
    user = update.effective_user
    
    # Permission check for /start in groups
    # Allow: Owner, Controllers, Group Admins
    is_authorized = False
    if _is_admin(user.id):
        is_authorized = True
    else:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status in ("administrator", "creator"):
            is_authorized = True
            
    if not is_authorized:
        # Silently ignore or maybe reply? Usually silently ignore to avoid spam
        return

    # /start command in group: Enable translation
    storage.add_group(chat.id, chat.title or str(chat.id), user.id, datetime.utcnow())
    storage.set_translation_enabled(chat.id, True)
    await update.message.reply_text(f"翻译功能已开启\n群组ID: `{chat.id}`", parse_mode="Markdown")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    chat = update.effective_chat
    user = update.effective_user
    # Check permissions
    # Allow: Owner, Controllers, Group Admins
    is_authorized = False
    if _is_admin(user.id):
        is_authorized = True
    else:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status in ("administrator", "creator"):
            is_authorized = True
            
    if not is_authorized:
        return
        
    # /stop (or /pause) command in group: Disable translation only
    # Do not remove group from storage, just set flag
    storage.set_translation_enabled(chat.id, False)
    await update.message.reply_text("翻译功能已暂停")


async def cmd_start_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await cmd_start(update, context)
        return
    if chat.type == ChatType.PRIVATE:
        if context.args:
            arg = context.args[0]
            if arg.startswith("authorize_"):
                user = update.effective_user
                storage.add_controller(user.id, user.username or None)
                await update.message.reply_text("已授权为控制者")
                if settings.OWNER_USER_ID:
                    try:
                        await context.bot.send_message(settings.OWNER_USER_ID, f"用户已通过链接授权为控制者: @{user.username} ({user.id})")
                    except Exception:
                        pass
                return
        await update.message.reply_text("欢迎")

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Alias for /stop but user specific request /暂停
    await cmd_stop(update, context)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    active = storage.is_group_active(chat.id)
    await update.message.reply_text("已激活" if active else "未激活")

async def cmd_set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("用法: /set_lang <en|zh|auto>")
        return
    member = await context.bot.get_chat_member(chat.id, user.id)
    if not (settings.OWNER_USER_ID and user.id == settings.OWNER_USER_ID) and member.status not in ("administrator", "creator"):
        return
    lang = context.args[0].lower()
    if lang not in ("en", "zh", "auto"):
        await update.message.reply_text("仅支持 en/zh/auto")
        return
    storage.set_group_lang(chat.id, lang)
    await update.message.reply_text("已设定")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    msg = update.effective_message
    user = update.effective_user
    logger.info("incoming group message chat=%s user=%s type=%s", chat.id, (user.id if user else None), msg.__class__.__name__)
    logger.info("Full message object: %s", msg.to_dict() if msg else "None")
    
    if not storage.is_group_active(chat.id):
        # Even if inactive, we might need to check if this is a command to re-activate?
        # Actually commands are handled by CommandHandler before MessageHandler.
        # But if we use MessageHandler for commands (regex), they might fall through?
        # No, MessageHandler(filters.Regex) handles them.
        # But wait, handle_group_message is a catch-all for TEXT.
        # If /暂停 is treated as text here, it means the specific handler didn't catch it?
        # Ah, filters.Regex(r"^/暂停") in bot.py should catch it.
        # Let's check logs.
        # Log shows: "incoming group message ... text='/暂停'"
        # This means handle_group_message IS being called for /暂停.
        # Why? Because in bot.py we added MessageHandler(..., handle_group_message)
        # And maybe the Regex handler didn't stop propagation?
        # Or maybe the order is wrong?
        # In bot.py, specific handlers are added BEFORE group handler.
        # BUT, ApplicationBuilder().build() uses the order of addition.
        # If a handler handles it, does it stop? Yes, unless group=... is used.
        # Wait, the log shows "Language detection ...".
        # This confirms handle_group_message IS executing.
        # This implies the specific handler for /暂停 didn't run or didn't stop execution.
        return

    if not storage.is_translation_enabled(chat.id):
        # Translation disabled by /stop
        return
        
    if user and user.is_bot:
        return
    
    text = msg.text or msg.caption or ""
    if not text:
        if msg.sticker:
            logger.info("Message is a sticker, skipping.")
            return
        logger.warning("Message has no text or caption. Checking other fields...")
        if msg.document:
            logger.info("Message is a document: %s", msg.document.file_name)
        elif msg.new_chat_members:
            logger.info("Message is new_chat_members event")
            return
        elif msg.left_chat_member:
            logger.info("Message is left_chat_member event")
            return
        logger.warning("No text found in message, skipping translation.")
        return

    if text.startswith(settings.SKIP_PREFIX):
        return
    if text.startswith("/"):
        return
    
    t = text.strip()
    if t.startswith("@") and (" " not in t) and (":" not in t) and ("\n" not in t):
        return
        
    prefix = ""
    translate_text = text
    if translate_text and translate_text.startswith("@"):
        s = translate_text
        idxs = []
        for ch in [" ", "\n", ":", "："]:
            i = s.find(ch)
            if i > 0:
                idxs.append(i)
        if idxs:
            j = min(idxs)
            prefix = s[:j].strip()
            translate_text = s[j:].lstrip()
            if not translate_text:
                return
    
    # Handle @username messages: translate the part after username
    # But if it's a reply, we still translate full text? Requirement says "@username 后面也要英文-中文互相翻译"
    # If text starts with @username, we treat it as normal text but maybe we should ensure it is translated.
    # Actually detect_language will handle mixed content. 
    # If user means "messages starting with @username should also be translated", the current logic already does that unless it's considered a command?
    # Telegram treats /command as command. @username is just text unless it's a bot command like /cmd@bot.
    # So we just need to ensure we don't skip it.
    
    # Logic:
    # 1. Contains Chinese -> Translate to English? NO.
    #    User requirement:
    #    - Mixed (Chinese + English) -> Chinese
    #    - All English -> Chinese
    #    - All Chinese -> English
    
    # Let's count characters to determine type
    zh_count = sum(1 for c in translate_text if '\u4e00' <= c <= '\u9fff')
    en_count = sum(1 for c in translate_text if ('a' <= c <= 'z') or ('A' <= c <= 'Z'))
    
    # Rule:
    # - If message contains ANY Chinese -> target EN
    # - Else if contains ANY Latin letters -> target ZH
    # - Else skip (emoji/symbols only)
    
    if zh_count > 0:
        target = "en"
    elif en_count > 0:
        target = "zh"
    else:
        # No clear language detected (e.g. only numbers, symbols, or emojis)
        # User requirement: Skip emojis (and effectively symbols/numbers if no text)
        logger.info("No Chinese or English characters detected (likely emoji/symbol), skipping.")
        return
    
    # Override if specific setting? Current logic overrides "auto" setting.
    # If user set forced lang, we might respect it, but user requirement seems to imply this logic for "auto" or general behavior.
    # The existing code: target = storage.get_group_lang(chat.id)
    # If target is "auto", we apply logic.
    
    stored_target = storage.get_group_lang(chat.id)
    if stored_target == "auto":
        # Apply the new logic
        pass 
    else:
        # If user forced "en" or "zh", we use it?
        # But user requirement says "中英文互相翻译", implying this IS the logic.
        # Let's assume this logic applies when mode is Auto.
        pass

    # Actually, let's just use the calculated target if mode is auto.
    if stored_target != "auto":
        target = stored_target

    translator = await _ensure_translator()
    
    # Define fallback function to call LLM if DeepL fails or returns bad result
    async def try_fallback(reason: str):
        if not settings.LLM_API_KEY:
            logger.warning(f"Fallback triggered ({reason}) but LLM_API_KEY not set. Skipping.")
            return None
        
        logger.info(f"Triggering LLM Fallback due to: {reason}")
        try:
            # Instantiate LLM translator
            # Assuming HttpTranslator handles "openai" provider correctly now
            llm_trans = HttpTranslator("openai", settings.LLM_API_KEY)
            # Use same source/target logic
            llm_result = await llm_trans.translate(text, source_lang=src, target_lang=target)
            return sanitize_text(llm_result)
        except Exception as ex:
            logger.error(f"LLM Fallback failed: {ex}")
            return None

    try:
        # ... DeepL logic ...
        # We don't really need accurate src lang for DeepL usually, but good to provide if known.
        # But our logic for target is custom.
        # Let's guess src based on target.
        
        # Logic: 
        # If target is EN, source is likely ZH (since we detected ZH chars).
        # If target is ZH, source is likely Latin script (EN, ID, HI, etc). Better to Auto-Detect.
        src = "zh" if target == "en" else None
        
        # Log the decision for debugging
        logger.info("Language detection: zh_count=%s en_count=%s target=%s src=%s", zh_count, en_count, target, src)
        
        translated = await translator.translate(translate_text, source_lang=src, target_lang=target)
        translated = sanitize_text(translated)
        
        should_use_fallback = False
        fallback_reason = ""

        if not translated:
            should_use_fallback = True
            fallback_reason = "Empty result from DeepL"
        elif translated.strip().lower() == translate_text.strip().lower():
            should_use_fallback = True
            fallback_reason = "DeepL returned identical text (echo)"
        elif target == "zh":
            res_zh_count = sum(1 for c in translated if '\u4e00' <= c <= '\u9fff')
            if res_zh_count == 0:
                should_use_fallback = True
                fallback_reason = "Target is ZH but result has no Chinese chars"

        if should_use_fallback:
            # Fallback always translate to ZH as per requirement
            target = "zh"
            llm_res = await try_fallback(fallback_reason)
            if llm_res and llm_res.strip().lower() != text.strip().lower():
                translated = llm_res
            else:
                # If LLM also failed or echoed, we give up to avoid spam
                if not translated: return 
                # If we have a DeepL result but it was rejected, and LLM failed, we might default to nothing
                # or just return if it was echo.
                if translated.strip().lower() == translate_text.strip().lower():
                    return
                # If target check failed for DeepL, and LLM failed, we skip
                if sum(1 for c in translated if '\u4e00' <= c <= '\u9fff') == 0:
                    return

        if translated:
            try:
                if prefix:
                    await msg.reply_text(f"{prefix} {translated}")
                else:
                    await msg.reply_text(translated)
            except Exception as e:
                logger.error("reply_text failed chat=%s msg=%s err=%s; fallback send_message", chat.id, msg.message_id, e)
                if prefix:
                    await context.bot.send_message(chat_id=chat.id, text=f"{prefix} {translated}", reply_to_message_id=msg.message_id)
                else:
                    await context.bot.send_message(chat_id=chat.id, text=translated, reply_to_message_id=msg.message_id)
            storage.record_trans_log(chat.id, msg.message_id, user.id, src, target, True)
            logger.info("translated chat=%s msg=%s src=%s dst=%s", chat.id, msg.message_id, src, target)
    except Exception as e:
        logger.error("translate failed chat=%s msg=%s err=%s", chat.id, msg.message_id, e)
        # Try fallback on exception too
        try:
            llm_res = await try_fallback(f"Exception: {e}")
            if llm_res:
                await msg.reply_text(llm_res)
                return
        except:
            pass
            
        try:
            fb = FallbackTranslator()
            translated = await fb.translate(translate_text, source_lang=src, target_lang=target)
            translated = sanitize_text(translated)
            if not translated:
                return
            if target == "zh":
                if sum(1 for c in translated if '\u4e00' <= c <= '\u9fff') == 0:
                    logger.warning("Fallback result has no Chinese characters, skipping group reply.")
                    return
            if target == "en":
                if not any(("a" <= c <= "z") or ("A" <= c <= "Z") for c in translated):
                    logger.warning("Fallback result has no Latin letters, skipping group reply.")
                    return
            await msg.reply_text(translated)
        finally:
            storage.record_trans_log(chat.id, msg.message_id, user.id, src, target, False)

async def cmd_list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_allowed_broadcaster(user.id):
        await update.message.reply_text("权限不足")
        return
    groups = storage.get_all_active_groups()
    total_active = len(groups)
    
    if not groups:
        await update.message.reply_text("当前无已激活群组")
        return

    lines = [f"群组列表 (共 {total_active} 个):"]
    for idx, (cid, title, ts) in enumerate(groups, 1):
        # Format timestamp to be more readable
        try:
            ts_obj = datetime.fromisoformat(ts)
            ts_str = ts_obj.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            ts_str = ts
        lines.append(f"{idx}. {title} ({cid}) | {ts_str}")
    
    await update.message.reply_text("\n".join(lines))

async def cmd_check_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("权限不足")
        return
    
    await update.message.reply_text("开始检查群组状态，这可能需要一些时间...")
    
    groups = storage.get_all_active_groups()
    valid_count = 0
    invalid_count = 0
    removed_ids = []
    
    for cid, title, _ in groups:
        try:
            chat = await context.bot.get_chat(cid)
            # Optional: Check if bot is still member/admin? 
            # For now just checking if we can get chat info implies we are not kicked (usually)
            valid_count += 1
        except Exception as e:
            # If error implies we are kicked or chat not found
            err_text = str(e)
            err_lower = err_text.lower()
            if "new chat id" in err_lower or "migrated to supergroup" in err_lower:
                m = re.search(r"(-100\d+)", err_text)
                if m:
                    new_cid = int(m.group(1))
                    try:
                        storage.migrate_group(cid, new_cid)
                        valid_count += 1
                        continue
                    except Exception:
                        pass
            logger.warning(f"Group {cid} ({title}) check failed: {e}")
            storage.deactivate_group(cid)
            invalid_count += 1
            removed_ids.append(cid)
            
    await update.message.reply_text(f"检查完成。\n有效: {valid_count}\n无效/已移除: {invalid_count}")

async def cmd_remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("权限不足")
        return
    if not context.args:
        await update.message.reply_text("用法: /remove_group <chat_id>")
        return
    try:
        cid = int(context.args[0])
    except Exception:
        await update.message.reply_text("chat_id 无效")
        return
    storage.remove_group(cid)
    await update.message.reply_text("已移除")

async def cmd_set_broadcaster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("权限不足")
        return
    arg = None
    if context.args:
        arg = context.args[0]
    else:
        txt = (update.effective_message.text or "").strip()
        parts = txt.split()
        if len(parts) >= 2:
            arg = parts[1]
    if not arg:
        await update.message.reply_text("用法: /set_broadcaster @username 或 /set_broadcaster <user_id>")
        return
    uname = parse_username(arg)
    try:
        if uname:
            uid = await _resolve_user_id(context, uname)
            storage.add_broadcaster(user_id=uid, username=uname)
            await update.message.reply_text(f"已授权广播员: @{uname} ({uid})")
        else:
            uid = int(arg)
            storage.add_broadcaster(user_id=uid, username=None)
            await update.message.reply_text(f"已授权广播员: {uid}")
    except Exception as e:
        await update.message.reply_text(f"授权失败: {e}")

async def cmd_unset_broadcaster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("权限不足")
        return
    arg = None
    if context.args:
        arg = context.args[0]
    else:
        txt = (update.effective_message.text or "").strip()
        parts = txt.split()
        if len(parts) >= 2:
            arg = parts[1]
    if not arg:
        await update.message.reply_text("用法: /unset_broadcaster @username 或 /unset_broadcaster <user_id>")
        return
    uname = parse_username(arg)
    try:
        if uname:
            uid = await _resolve_user_id(context, uname)
        else:
            uid = int(arg)
        storage.remove_broadcaster(uid)
        await update.message.reply_text(f"已取消广播员: {uid}")
    except Exception as e:
        await update.message.reply_text(f"取消失败: {e}")

async def cmd_list_broadcasters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("权限不足")
        return
    items = storage.list_broadcasters()
    lines = [f"{uid} @{uname}" if uname else str(uid) for uid, uname in items]
    await update.message.reply_text("\n".join(lines) if lines else "空")

async def cmd_authorize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_owner(user.id):
        await update.message.reply_text("仅 owner 可授权控制权限")
        return
    if not context.args:
        await update.message.reply_text("用法: /授权 @username 或 /授权 <user_id>")
        return
    arg0 = context.args[0]
    uname = parse_username(arg0)
    try:
        if uname:
            uid = await _resolve_user_id(context, uname)
            if storage.is_controller(uid):
                await update.message.reply_text(f"已是控制者: @{uname} ({uid})")
                return
            storage.add_controller(uid, uname)
            await update.message.reply_text(f"已授予控制权限: @{uname} ({uid})")
        else:
            uid = int(arg0)
            if storage.is_controller(uid):
                await update.message.reply_text(f"已是控制者: {uid}")
                return
            storage.add_controller(uid, None)
            await update.message.reply_text(f"已授予控制权限: {uid}")
    except BadRequest:
        link = f"https://t.me/{context.bot.username}?start=authorize_{uname}"
        await update.message.reply_text(f"未授权：无法解析该用户名。请让该用户点击授权链接完成绑定：\n{link}")
    except ValueError:
        await update.message.reply_text("参数无效：请提供 @username 或数字 user_id")

async def cmd_unauthorize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_owner(user.id):
        await update.message.reply_text("仅 owner 可取消控制权限")
        return
    if not context.args:
        await update.message.reply_text("用法: /取消授权 @username 或 /取消授权 <user_id>")
        return
    
    arg0 = context.args[0]
    uname = parse_username(arg0)
    try:
        if uname:
            uid = await _resolve_user_id(context, uname)
        else:
            uid = int(arg0)
        
        storage.remove_controller(uid)
        await update.message.reply_text(f"已取消控制权限: {uid}")
    except Exception as e:
        await update.message.reply_text(f"操作失败: {e}")

async def cmd_list_controllers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("权限不足")
        return
    items = storage.list_controllers()
    lines = [f"{uid} @{uname}" if uname else str(uid) for uid, uname in items]
    await update.message.reply_text("\n".join(lines) if lines else "空")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("权限不足")
        return
    await update.message.reply_text("近期统计功能示例：请在 DB 分析 trans_logs 与 broadcasts")

async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("权限不足")
        return
    if len(context.args) < 2:
        await update.message.reply_text("用法: /preview <chat_id> <message>")
        return
    cid = int(context.args[0])
    msg = " ".join(context.args[1:])
    try:
        await context.bot.send_message(chat_id=cid, text=msg)
        await update.message.reply_text("已发送")
    except Exception as e:
        await update.message.reply_text(f"失败: {e}")

def _is_owner(user_id: int) -> bool:
    return bool(settings.OWNER_USER_ID and user_id == settings.OWNER_USER_ID)

def _is_admin(user_id: int) -> bool:
    return _is_owner(user_id) or storage.is_controller(user_id)

def _is_allowed_broadcaster(user_id: int) -> bool:
    if _is_admin(user_id):
        return True
    return storage.is_broadcaster(user_id)

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    user = update.effective_user
    msg = update.effective_message
    if msg and msg.text and msg.text.strip().startswith('/'):
        return
    if not _is_allowed_broadcaster(user.id):
        await update.message.reply_text("权限不足")
        return
    if not _is_admin(user.id) and storage.count_recent_broadcasts(1) >= settings.BROADCAST_MAX_PER_HOUR:
        await update.message.reply_text("频率受限")
        return
    groups = storage.get_all_active_groups()[: settings.BROADCAST_MAX_GROUPS]
    total = len(groups)
    if total == 0:
        await update.message.reply_text("尚无已激活群组")
        return
    success = 0
    failure = 0
    samples: List[str] = []
    content_type = _detect_content_type(update)
    sem = asyncio.Semaphore(10)

    async def send_one(cid: int):
        nonlocal success, failure, samples
        async with sem:
            # Retry mechanism for transient errors
            max_retries = 2
            attempt = 0
            last_err = None
            
            while attempt <= max_retries:
                try:
                    await _send_copy(context, update, cid)
                    success += 1
                    await asyncio.sleep(0.05)
                    return
                except Exception as e:
                    last_err = e
                    err_text = str(e)
                    err_lower = err_text.lower()
                    if "new chat id" in err_lower or "migrated to supergroup" in err_lower:
                        m = re.search(r"(-100\d+)", err_text)
                        if m:
                            new_cid = int(m.group(1))
                            try:
                                storage.migrate_group(cid, new_cid)
                            except Exception:
                                pass
                            try:
                                await _send_copy(context, update, new_cid)
                                success += 1
                                await asyncio.sleep(0.05)
                                return
                            except Exception as e2:
                                last_err = e2
                        break
                    if "forbidden" in err_lower or "chat not found" in err_lower or "kicked" in err_lower:
                        storage.deactivate_group(cid)
                        break
                    if "network" in err_lower or "timeout" in err_lower or "retry" in err_lower:
                        attempt += 1
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    break
            
            # If we reached here, it failed
            failure += 1
            if len(samples) < 10:
                samples.append(f"{cid}: {last_err}")

    tasks = [send_one(cid) for cid, _, _ in groups]
    await asyncio.gather(*tasks)
    storage.record_broadcast(user.id, content_type, total, success, failure, "|".join(samples))
    
    report = (
        f"📢 广播完成\n"
        f"总数: {total}\n"
        f"✅ 成功: {success}\n"
        f"❌ 失败: {failure}"
    )
    if samples:
        report += f"\n\n⚠️ 失败样本:\n" + "\n".join(samples)
    
    await update.message.reply_text(report)

async def _send_copy(context: ContextTypes.DEFAULT_TYPE, update: Update, cid: int):
    msg = update.effective_message
    
    # Add the requested button
    # keyboard = [
    #    [InlineKeyboardButton("JHT®PAY account manager", url="https://t.me/JHT_c")]
    # ]
    # reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Use copy_message for all types to preserve formatting and media, and attach the button
    await context.bot.copy_message(
        chat_id=cid, 
        from_chat_id=msg.chat_id, 
        message_id=msg.message_id
        # reply_markup=reply_markup
    )

def _detect_content_type(update: Update) -> str:
    msg = update.effective_message
    if msg.text:
        return "text"
    if msg.photo:
        return "photo"
    if msg.video:
        return "video"
    if msg.document:
        return "document"
    if msg.sticker:
        return "sticker"
    return "unknown"

async def on_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cm = update.chat_member
    if cm and cm.new_chat_member and cm.new_chat_member.status == "kicked":
        storage.remove_group(chat.id)

async def _resolve_user_id(context: ContextTypes.DEFAULT_TYPE, username: str) -> int:
    try:
        chat = await context.bot.get_chat(f"@{username}")
        return int(chat.id)
    except BadRequest:
        raise BadRequest("无法解析该用户名，请让该用户先与机器人对话或提供数字ID")
