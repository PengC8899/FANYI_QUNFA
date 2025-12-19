# Telegram 群发翻译 Bot (Python)

## 简介
- 群内自动中英文互译（中文↔英文），只回复译文并作为原消息的回复。
- 管理群列表，支持私聊群发：文本、图片、视频、文件、贴纸。
- 广播权限与频率控制、失败统计、日志与审计、黑名单处理。
- 默认使用 SQLite 持久化；提供 Docker 部署与基本单元测试。

## 技术栈
- Python 3.10+
- python-telegram-bot v20+
- httpx
- sqlite3
- pydantic（配置校验）
- pytest
- 可选：FastAPI + Uvicorn/Gunicorn（用于 Webhook/管理面板扩展）

## 环境变量
- `TELEGRAM_BOT_TOKEN`
- `TRANSLATE_API`（google/deepl/openai）
- `TRANSLATE_API_KEY`
- `OWNER_USER_ID`
- `DB_PATH`（默认 `./data/bot.db`）
- `ALLOW_BROADCAST_FROM_GROUPS`（默认 `false`）
- `BROADCAST_MAX_PER_HOUR`（默认 `5`）
- `BROADCAST_MAX_GROUPS`（默认 `500`）
- `MEDIA_MAX_BYTES`（默认 `10485760`）
- `LOG_FILE`（默认 `./logs/bot.log`）

## 安装与运行
- 本地
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
  - 复制 `.env.example` 为 `.env` 并填写变量
  - `python bot.py`
- Docker
  - `docker build -t tg-fanyi-bot .`
  - `docker run --env-file .env -v $(pwd)/data:/app/data -v $(pwd)/logs:/app/logs tg-fanyi-bot`

## 翻译实现
- 抽象接口：`Translator.translate(text, source_lang=None, target_lang=None) -> str`
- HTTP 实现（示例）：`openai` 走 REST API；`google` / `deepl` 留扩展点。
- 降级策略：当无 API Key 或调用失败，使用轻量级词典规则进行低精度翻译；不在群内公开“未配置”提示，错误通过日志与私聊告知 owner。
- 语言检测：中文字符占比阈值判定；可选集成 `langdetect`。
- 长度限制：译文超 4000 字符截断，并在私聊告知 owner。

## 消息流程
- 群消息
  - 校验群是否激活
  - 忽略机器人自身、白名单用户、`/notranslate` 前缀
  - 提取文本或 caption
  - 检测语言与目标语言
  - 翻译并以 `reply_to_message` 发送译文
  - 记录日志
- 私聊广播
  - 验证发起人（owner 或 broadcaster）
  - 组装 payload（支持 `copy_message` 保持格式）
  - 受限并发与频率控制，逐群发送
  - 汇总成功/失败与样本错误，私聊回复报告

## 数据库
- `groups(chat_id, title, activated_by, activated_at, target_lang, active)`
- `broadcasters(user_id, username)`
- `broadcasts(id, by_user_id, content_type, created_at, total, success, failure, errors_sample)`
- 事务与并发安全，自动创建表。

## 命令
- 群内
  - `/开始` 激活并保存群
  - `/停止` 仅管理员或 owner 停用并移除群
  - `/状态` 显示是否激活
  - `/set_lang <en|zh>` 设置默认目标语言
- 私聊（owner/broadcaster）
  - 直接发送任意内容 => 群发
  - `/list_groups`
  - `/remove_group <chat_id>`
  - `/set_broadcaster @username` `/unset_broadcaster @username` `/list_broadcasters`
  - `/stats` 最近 7 天统计（仅 owner）
  - 可选：`/preview <chat_id> <message>` 单群测试

## 核心功能与排错

### 1. 群组内自动翻译

- 功能：群内普通消息自动进行中英互译，只回复译文，并作为原消息的回复。
- 激活方式：在群或超级群内发送 `/start`，会写入/更新群记录并打开翻译开关（`commands.py:25`）。
- 触发条件：
  - 群在数据库中为“已激活”且翻译功能为开启状态（`commands.py:107,129`）。
  - 过滤掉：机器人消息、以 `/` 开头的命令、带跳过前缀（`settings.SKIP_PREFIX`）、纯 `@username`、贴纸、图片、纯表情等（`commands.py:133-148,167-180`）。
- 翻译方向：
  - 包含中文字符 → 译成英文。
  - 无中文但含英文字母 → 译成中文。
  - 否则（只有数字/符号/表情）跳过（`commands.py:198-214`）。
  - 若群配置的语言模式不是 `auto`，则优先使用群级设置（`commands.py:221-233`）。
- 实现与降级：
  - 主翻译使用 `HttpTranslator` 或 `FallbackTranslator`（`commands.py:20-23,235-270`）。
  - 主翻译失败、回声或结果不符合预期时，触发 LLM 兜底（如 OpenAI），仍失败则使用本地 Fallback 再试（`commands.py:238-253,272-287,318-336`）。
- 常见问题排查：
  - 群里完全不翻译：检查是否执行过 `/start`，在群内用 `/status` 看是否“已激活”；同时确认只在一台 VPS 上运行该 bot。
  - 只对部分消息翻译：确认消息不是命令/贴纸/图片/纯表情，且没有使用跳过前缀；检查群级语言模式是否锁死为固定 `en` 或 `zh`。

### 2. 私聊广播到所有已激活群

- 功能：拥有权限的用户在私聊中发送任意非命令消息，bot 使用 `copy_message` 将该消息广播到所有已激活群（`commands.py:608-713`）。
- 权限模型：
  - Owner：`settings.OWNER_USER_ID` 指定用户（`commands.py:597-598`）。
  - Admin（控制者）：Owner 或被 `/授权` 加入控制者列表（`commands.py:600-601,502-534`）。
  - Broadcaster（广播员）：Admin 自动拥有广播权限，或通过 `/set_broadcaster` 单独授权（`commands.py:431-460,603-606`）。
- 频率与范围：
  - 广播目标为 `storage.list_groups()` 返回的已激活群，最多 `BROADCAST_MAX_GROUPS` 个（`commands.py:621`）。
  - 非 Admin 受 `BROADCAST_MAX_PER_HOUR` 每小时次数限制，超限返回“频率受限”（`commands.py:618-620`）。
- 可靠性与自动纠错：
  - 使用 `asyncio.Semaphore` 控制并发，针对网络错误进行有限次数重试（`commands.py:630-673`）。
  - 遇到 “migrated to supergroup/new chat id” 时自动解析 `-100...` 新 ID，调用 `storage.migrate_group` 迁移并重发（`commands.py:650-656,659-662`）。
  - 遇到 “forbidden/chat not found/kicked” 时自动停用该群（`commands.py:666-668`）。
  - 广播结束后记录统计到 `broadcasts` 表，并在私聊中回执总数、成功、失败和部分失败样本（`commands.py:682-691`）。
- 常见问题排查：
  - 私聊无反应：确认是在私聊而不是群内发送；消息不是以 `/` 开头；用 `/list_broadcasters`、`/list_controllers` 检查是否具备广播权限。
  - 提示“权限不足”：使用 Owner 账号 `/授权` 或 `/set_broadcaster` 为当前账号授权。
  - 部分群收不到广播：检查回执中的失败样本；对迁移错误可通过 `/check_groups` 批量迁移/清理（`commands.py:371-411`）。

### 3. 群内 `/start` 显示群组 ID

- 功能：在群或超级群中发送 `/start`，bot 会：
  - 将该群写入或更新到 `groups` 表，并标记为激活（`commands.py:25-32`）。
  - 打开该群的翻译功能。
  - 回复“翻译功能已开启”和当前群组 `chat_id`，方便手动排错或用于其他系统对接（`commands.py:33`）。
- 常见问题排查：
  - 群内 `/start` 无响应：检查 bot 是否仍在群内且未被禁言；确认 `bot.py` 中已绑定 `/start` 到 `cmd_start_entry`，并查看容器日志是否有报错。
  - 群组 ID 与预期不一致或群发失败：注意普通群升级为超级群后会改为 `-100...`，可通过 `/check_groups` 触发自动迁移，也可在数据库中核对 `groups.chat_id`。

## 安全与鲁棒
- 外部 API 超时与指数退避重试
- 媒体大小限制，超限私聊告知
- 广播频率与收件人上限
- Bot 被踢出自动移除群并记录原因
- 日志轮替与失败通知 owner（可选）

## 测试
- `pytest`
- 覆盖：语言检测、DB 操作、权限判断、消息处理（使用 Mock Translator）

## 可拓展
- Webhook 面板与审计查询
- 支持更多语言与自定义规则
- 分布式广播与消息队列
- 更丰富的速率限制与重试策略
