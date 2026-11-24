import sys
import traceback
import os
import json
import time
import random
import asyncio
import hashlib
import string
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ParseMode
from datetime import datetime
from pathlib import Path

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "9056902843:AAEW24cuT4QUJJoKqYX68g-rBFAz51pLhmM")
SUPER_OWNER_ID = int(os.getenv("SUPER_OWNER_ID", "8401967510"))
OWNER_ID = int(os.getenv("OWNER_ID", "8401967510"))
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "8401967510"))
ADMIN_CHAT_IDS = [int(x) for x in os.getenv("ADMIN_CHAT_IDS", str(ADMIN_CHAT_ID)).split(",") if x.strip().lstrip("-").isdigit()]
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "@aliwinside1")
BOT_DISPLAY_NAME = os.getenv("BOT_DISPLAY_NAME", "𝐌𝐚𝐤𝐞 𝐎𝐰𝐧 𝐁𝐚𝐧 𝐁𝐨𝐭")
CHILD_BAN_NAME = os.getenv("CHILD_BAN_NAME", BOT_DISPLAY_NAME)
IS_CHILD_BOT = os.getenv("ALIW_CHILD_BOT", "0") == "1"
CHILD_CHANNEL_URL = os.getenv("CHILD_CHANNEL_URL", "https://t.me/aliwinc")
CHILD_CHANNEL_ID = os.getenv("CHILD_CHANNEL_ID", "")
CHILD_KEY_NAME = os.getenv("CHILD_KEY_NAME", "MAKEOWNBANBOT")
ANNOUNCEMENT_CHANNEL = os.getenv("ANNOUNCEMENT_CHANNEL", "@bancloneupd")

# Default channels are only for the main bot. Child bots keep /channel empty;
# their creation-time channel is used only as a separate force-join setting.
DEFAULT_CHANNELS = [] if IS_CHILD_BOT else [
    {"name": "𝐌𝐚𝐢𝐧 𝐂𝐡𝐚𝐧𝐧𝐞𝐥", "id": "@aliwinc", "url": "https://t.me/aliwinc"},
    {"name": "𝐁𝐮𝐠 𝐔𝐩𝐝𝐚𝐭𝐞𝐬", "id": "@bugupdatezz", "url": "https://t.me/bugupdatezz"},
    {"name": "𝐁𝐮𝐠 𝐔𝐩𝐝𝐚𝐭𝐞𝐬", "id": "@backuchannelaliw", "url": "https://t.me/backuchannelaliw"},
]

# ===== DATA & DATABASE =====
DATA_DIR = Path("bot_data")
DB_FILE = DATA_DIR / "database.json"
IMG_PATH = Path(os.getenv("IMG_PATH", "start.png"))
DATA_DIR.mkdir(exist_ok=True)

db = {
    "owners": [], "premium": [], "all_users": [], 
    "referrals": {}, "referral_codes": {}, "temp_premium": {}, 
    "temp_owners": {}, "daily_claims": {},  # 🟢 NEW: Temp Owners & Daily
    "referred_by": {}, "pending_referrals": {}, "banned_users": [], "redeem_keys": {},
    "anti_numbers": [],
    "stats": {"total_bans": 0, "total_unbans": 0},
    "settings": {
        "maintenance": False, 
        "ref_target": 5, 
        "ref_reward_hours": 1,
        "free_bot": False,
        "channels": DEFAULT_CHANNELS
    }
}
cooldowns = {}
broadcast_state = {}
last_bot_messages = {}  # 🟢 NEW: For Auto-Delete Messages
awaiting_payment = {}   # 🟢 NEW: For Buy Screenshot Verification
payset_state = {}       # Admin-only payment method configuration state
channel_edit_state = {}  # Owner-only channel button edit state
video_link_state = {}  # Grand-owner video URL editor
admin_bot_edit_state = {}  # Admin-only created-bot edit wizard
create_bot_state = {}  # User-specific create-own-bot wizard
child_processes = {}  # bot record id -> asyncio.subprocess.Process
child_log_files = {}  # bot record id -> open log file handle

if DB_FILE.exists():
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            saved_db = json.load(f)
            db.update(saved_db)
            if "channels" not in db["settings"]:
                db["settings"]["channels"] = DEFAULT_CHANNELS
            if "free_bot" not in db["settings"]:
                db["settings"]["free_bot"] = False
            if "temp_owners" not in db: db["temp_owners"] = {}
            if "daily_claims" not in db: db["daily_claims"] = {}
            if "anti_numbers" not in db: db["anti_numbers"] = []
    except Exception as e:
        print(f"⚠️ Failed to load DB: {e}")

if OWNER_ID not in db["owners"]:
    db["owners"].append(OWNER_ID)

# Migrate legacy created-bot records from the old referral-name field to the new key-name field.
for _bot in db.get("created_bots", []):
    if "key_name" not in _bot:
        _bot["key_name"] = _bot.pop("referral_name", "ALIWBANBOT")
    if "admin_ids" not in _bot:
        _bot["admin_ids"] = list(_bot.get("chat_ids") or [_bot.get("chat_id")])

def save_db():
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2)

def is_super_owner(user_id): return user_id == SUPER_OWNER_ID

def is_owner(user_id): 
    if is_super_owner(user_id) or user_id in ADMIN_CHAT_IDS or user_id in db["owners"]: return True
    if str(user_id) in db.get("temp_owners", {}):
        if datetime.now().timestamp() < db["temp_owners"][str(user_id)]: return True
        else:
            del db["temp_owners"][str(user_id)]
            save_db()
    return False

def is_banned(user_id): return str(user_id) in db.get("banned_users", []) or user_id in db.get("banned_users", [])

def is_premium(user_id):
    if db["settings"].get("free_bot", False): return True
    if is_owner(user_id): return True
    if user_id in db["premium"] or str(user_id) in db["premium"]: return True
    if str(user_id) in db.get("temp_premium", {}):
        if datetime.now().timestamp() < db["temp_premium"][str(user_id)]: return True
        else:
            del db["temp_premium"][str(user_id)]
            save_db()
    return False

def normalize_number(number):
    return str(number).strip().replace(" ", "")

def is_anti_number(number):
    normalized = normalize_number(number)
    return any(normalized == normalize_number(saved) for saved in db.get("anti_numbers", []))

def anti_number_message(number):
    return (
        "╭━━〔 𝗢𝗪𝗡𝗘𝗥 𝗡𝗨𝗠𝗕𝗘𝗥 〕━━┈⊷\n"
        f"┃ 📞 ɴᴜᴍʙᴇʀ : `{number}`\n"
        "┃ 👑 ᴛʜɪs ɪs ʙᴀɴ ʙᴏᴛ ᴏᴡɴᴇʀ ɴᴜᴍʙᴇʀ.\n"
        "┃ 🚫 ɴᴏ ʀᴇᴘᴏʀᴛ sᴇɴᴅ ᴛᴏ ᴛʜɪs ɴᴜᴍʙᴇʀ.\n"
        "╰━━━━━━━━━━━━━━━━━━━━━┈⊷"
    )

def get_progress_bar(current, total, length=10):
    percent = current / total
    filled = int(length * percent)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}] {int(percent * 100)}%"

def check_cooldown(user_id):
    if is_owner(user_id): return False, 0
    cd_time = 5 if is_premium(user_id) else 30
    last_used = cooldowns.get(user_id, 0)
    now = time.time()
    if now - last_used < cd_time:
        return True, int(cd_time - (now - last_used))
    cooldowns[user_id] = now
    return False, 0

async def check_all_channels(user_id, context):
    if is_owner(user_id): return True, None
    channels = []
    channels.extend(db["settings"].get("channels", []))
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(channel["id"], user_id)
            if member.status not in ["creator", "administrator", "member"]: return False, channel["name"]
        except: return False, channel["name"]
    return True, None

async def send_denied_message(update: Update):
    target = db["settings"]["ref_target"]
    hours = db["settings"]["ref_reward_hours"]
    msg = f"""╭━━〔 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗 〕━━┈⊷
┃ 🔒 ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ʀᴇQᴜɪʀᴇꜱ ᴘʀᴇᴍɪᴜᴍ!
┃ 🔑 ᴜꜱᴇ /redeem <key> ɪꜰ ʏᴏᴜ ʜᴀᴠᴇ ᴏɴᴇ.
┃ 📞 ᴏʀ ᴄᴏɴᴛᴀᴄᴛ {OWNER_USERNAME} ᴛᴏ ʙᴜʏ.
┃
┃ 🎁 ꜰʀᴇᴇ ᴍᴇᴛʜᴏᴅ: ʀᴇꜰᴇʀ {target} ꜰʀɪᴇɴᴅꜱ
┃ ᴛᴏ ᴜɴʟᴏᴄᴋ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ {hours} ʜᴏᴜʀ(ꜱ).
╰━━━━━━━━━━━━━━━━━━━━━┈⊷"""
    if update.callback_query:
        await update.callback_query.message.edit_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

def generate_referral_code(user_id):
    return f"REF{hashlib.md5(f'{user_id}{time.time()}'.encode()).hexdigest()[:8].upper()}"

async def cleanup_old_message(chat_id, context):
    if chat_id in last_bot_messages:
        try: await context.bot.delete_message(chat_id, last_bot_messages[chat_id])
        except: pass

async def maintenance_guard(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if is_banned(user_id):
        return True
    if db["settings"]["maintenance"] and not is_owner(user_id):
        await update.message.reply_text("╭━━〔 𝗠𝗔𝗜𝗡𝗧𝗘𝗡𝗔𝗡𝗖𝗘 〕━━┈⊷\n┃ 🛠️ ʙᴏᴛ ɪꜱ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
        return True
    return False

# ===== COMMANDS =====

async def start_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if is_banned(user_id): return
    if db["settings"]["maintenance"] and not is_owner(user_id):
        await update.message.reply_text("╭━━〔 𝗠𝗔𝗜𝗡𝗧𝗘𝗡𝗔𝗡𝗖𝗘 〕━━┈⊷\n┃ 🛠️ ʙᴏᴛ ɪꜱ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
        return

    # Auto-Delete older start message
    if not update.callback_query:
        await cleanup_old_message(chat_id, context)

    if user_id not in db["all_users"]:
        db["all_users"].append(user_id)
        save_db()
        
    if context.args and context.args[0].lower() == "createownbot" and not IS_CHILD_BOT:
        return await createownbot_command(update, context)

    if context.args and context.args[0].startswith("ref_"):
        ref_code = context.args[0][4:]
        referrer_id = next((int(uid) for uid, code in db["referral_codes"].items() if code == ref_code), None)
        
        if referrer_id and referrer_id != user_id and str(user_id) not in db.get("referred_by", {}) and str(user_id) not in db.get("pending_referrals", {}):
            db.setdefault("pending_referrals", {})[str(user_id)] = referrer_id
            save_db()

    joined, missing = await check_all_channels(user_id, context)
    if not joined:
        force_channels = []
        force_channels.extend(db["settings"].get("channels", []))
        kb = [[InlineKeyboardButton(f"📢 {ch['name']}", url=ch['url'], style="primary")] for ch in force_channels]
        kb.append([InlineKeyboardButton("✅ ᴠᴇʀɪꜰʏ ᴊᴏɪɴᴇᴅ", callback_data="verify_joined", style="success")])
        child_admin_note = "\n┃ ⚠️ Make your this bot admin in for join channel, otherwise bot will not start." if IS_CHILD_BOT else ""
        msg = await context.bot.send_message(chat_id, f"╭━━〔 {BOT_DISPLAY_NAME} 〕━━┈⊷\n┃ 🚫 ᴘʟᴇᴀꜱᴇ ᴊᴏɪɴ ᴀʟʟ ᴄʜᴀɴɴᴇʟꜱ ꜰɪʀꜱᴛ!\n┃ ᴍɪꜱꜱɪɴɢ: {missing}{child_admin_note}\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", reply_markup=InlineKeyboardMarkup(kb))
        last_bot_messages[chat_id] = msg.message_id
        return

    str_uid = str(user_id)
    if str_uid in db.get("pending_referrals", {}):
        referrer_id = db["pending_referrals"][str_uid]
        db.setdefault("referred_by", {})[str_uid] = referrer_id
        
        r_str = str(referrer_id)
        db["referrals"][r_str] = db["referrals"].get(r_str, 0) + 1
        
        if db["referrals"][r_str] >= db["settings"]["ref_target"]:
            db.setdefault("temp_premium", {})[r_str] = datetime.now().timestamp() + (db["settings"]["ref_reward_hours"] * 3600)
            db["referrals"][r_str] -= db["settings"]["ref_target"]
            
        try:
            await context.bot.send_message(chat_id=referrer_id, text=f"╭━━〔 𝗡𝗘𝗪 𝗥𝗘𝗙𝗘𝗥𝗥𝗔𝗟 〕━━┈⊷\n┃ 🎉 ꜱᴏᴍᴇᴏɴᴇ ᴊᴏɪɴᴇᴅ ᴠɪᴀ ʏᴏᴜʀ ʟɪɴᴋ ᴀɴᴅ ᴠᴇʀɪꜰɪᴇᴅ!\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
        except: pass
        
        del db["pending_referrals"][str_uid] 
        save_db()

    createown_line = "┃ 🤖 /createownbot ➡️ ᴍᴀᴋᴇ ᴏᴡɴ ʙᴏᴛ\n" if not IS_CHILD_BOT else ""
    bot_menu = f"""╭━━〔 {BOT_DISPLAY_NAME} 🔥 〕━━┈⊷
┃ 😈 ᴡᴇʟᴄᴏᴍᴇ, {update.effective_user.first_name[:15]}! 🩸
┃
┃ 🆓 𝗙𝗥𝗘𝗘 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦
┃ 👤 /profile    ➡️ ʏᴏᴜʀ ᴅᴀꜱʜʙᴏᴀʀᴅ
┃ 🔗 /referral   ➡️ ʀᴇꜰᴇʀ ʟɪɴᴋ
┃ 🔑 /redeem     ➡️ ᴜꜱᴇ ᴘʀᴇᴍɪᴜᴍ ᴋᴇʏ
┃ 🎁 /daily      ➡️ ᴅᴀɪʟʏ ʙᴏɴᴜꜱ
┃ 🏆 /top        ➡️ ʟᴇᴀᴅᴇʀʙᴏᴀʀᴅ
┃ 💳 /buy        ➡️ ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ
{createown_line}┃
┃ 🔥 𝗣𝗥𝗘𝗠𝗜𝗨𝗠 / 𝗩𝗜𝗣
┃ 📱 /check <ɴᴏ> ➡️ ᴄʜᴇᴄᴋ ɴᴜᴍʙᴇʀ
┃ 💣 /ban_perm <ɴᴏ> ➡️ ᴘᴇʀᴍ ʙᴀɴ
┃ ⚡ /ban_temp <ɴᴏ> ➡️ ᴛᴇᴍᴘ ʙᴀɴ
┃ 🔓 /unban <ɴᴏ>    ➡️ ᴜɴʙᴀɴ
╰━━━━━━━━━━━━━━━━━━━━━┈⊷"""
    menu_channel_url = CHILD_CHANNEL_URL if IS_CHILD_BOT else (db["settings"].get("channels", [{}])[0].get("url", "") if db["settings"].get("channels") else "")
    kb = [[InlineKeyboardButton("👤 ᴍʏ ᴘʀᴏꜰɪʟᴇ", callback_data="show_profile", style="primary")]]
    owner_row = [InlineKeyboardButton("💬 ᴄʜᴀᴛ ᴏᴡɴᴇʀ", url=_telegram_url(OWNER_USERNAME), style="success")]
    if menu_channel_url:
        owner_row.append(InlineKeyboardButton("📢 ᴄʜᴀɴɴᴇʟ", url=menu_channel_url, style="success"))
    kb.append(owner_row)
    if not IS_CHILD_BOT:
        try:
            main_username = (await context.bot.get_me()).username or ""
            if main_username:
                kb.append([InlineKeyboardButton("🤖 Create Your Own Ban Bot", url=f"https://t.me/{main_username}?start=createownbot", style="primary")])
        except Exception:
            pass
    
    if update.callback_query:
        if IMG_PATH.exists():
            # If editing a callback and there is a photo, we edit caption
            try: await update.callback_query.message.edit_caption(caption=bot_menu, reply_markup=InlineKeyboardMarkup(kb))
            except: await update.callback_query.message.edit_text(bot_menu, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.callback_query.message.edit_text(bot_menu, reply_markup=InlineKeyboardMarkup(kb))
    else:
        try:
            if IMG_PATH.exists():
                msg = await context.bot.send_photo(chat_id=chat_id, photo=open(IMG_PATH, 'rb'), caption=bot_menu, reply_markup=InlineKeyboardMarkup(kb))
            else:
                msg = await context.bot.send_message(chat_id=chat_id, text=bot_menu, reply_markup=InlineKeyboardMarkup(kb))
            last_bot_messages[chat_id] = msg.message_id
        except Exception as e:
            print(f"Error sending photo: {e}")
            msg = await context.bot.send_message(chat_id=chat_id, text=bot_menu, reply_markup=InlineKeyboardMarkup(kb))
            last_bot_messages[chat_id] = msg.message_id

async def profile_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    ref_count = db["referrals"].get(str(user_id), 0)
    target = db["settings"]["ref_target"]
    prog_bar = get_progress_bar(ref_count, target)
    
    stat = "🌟 ʟɪꜰᴇᴛɪᴍᴇ ᴘʀᴇᴍɪᴜᴍ" if user_id in db["premium"] or is_owner(user_id) else "🔒 ꜰʀᴇᴇ ᴜꜱᴇʀ"
    if str(user_id) in db.get("temp_premium", {}):
        left = int(db["temp_premium"][str(user_id)] - time.time())
        if left > 0:
            hrs, mins = left // 3600, (left % 3600) // 60
            stat = f"⏳ ᴘʀᴇᴍɪᴜᴍ ({hrs}ʜ {mins}ᴍ ʟᴇꜰᴛ)"

    msg = f"""╭━━〔 𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘 〕━━┈⊷
┃ 👤 ɴᴀᴍᴇ: {update.effective_user.first_name}
┃ 🆔 ɪᴅ: `{user_id}`
┃ 💎 ꜱᴛᴀᴛᴜꜱ: {stat}
┃
┃ 👥 𝗥𝗘𝗙𝗘𝗥𝗥𝗔𝗟 𝗣𝗥𝗢𝗚𝗥𝗘𝗦𝗦:
┃ {prog_bar}
┃ ({ref_count}/{target} ꜰᴏʀ ꜰʀᴇᴇ ᴘʀᴇᴍɪᴜᴍ)
┃
┃ 💡 ᴜꜱᴇ /redeem <key> ᴛᴏ ᴀᴄᴛɪᴠᴀᴛᴇ ᴠɪᴘ.
╰━━━━━━━━━━━━━━━━━━━━━┈⊷"""
    
    kb = [[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸", callback_data="back_start", style="danger")]]
    
    if update.callback_query: 
        try: await update.callback_query.message.edit_caption(caption=msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        except: await update.callback_query.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    else: 
        await cleanup_old_message(chat_id, context)
        sent_msg = await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        last_bot_messages[chat_id] = sent_msg.message_id

# 🟢 NEW: Leaderboard
async def top_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    sorted_refs = sorted(db["referrals"].items(), key=lambda x: x[1], reverse=True)[:10]
    msg = "╭━━〔 🏆 𝗧𝗢𝗣 𝗥𝗘𝗙𝗘𝗥𝗥𝗘𝗥𝗦 〕━━┈⊷\n"
    if not sorted_refs:
        msg += "┃ 🚫 ɴᴏ ᴅᴀᴛᴀ ʏᴇᴛ.\n"
    else:
        for i, (uid, count) in enumerate(sorted_refs, 1):
            msg += f"┃ {i}. `{uid}` ➡️ {count} Invites\n"
    msg += "╰━━━━━━━━━━━━━━━━━━━━━┈⊷"
    await update.message.reply_text(msg, parse_mode="Markdown")

# 🟢 NEW: Daily Bonus
async def daily_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = str(update.effective_user.id)
    now = time.time()
    last_claim = db["daily_claims"].get(user_id, 0)
    
    if now - last_claim < 86400: # 24 hours
        left = int(86400 - (now - last_claim))
        h, m = left // 3600, (left % 3600) // 60
        await update.message.reply_text(f"⏳ You have already claimed! Please wait {h}h {m}m.")
        return
        
    db["daily_claims"][user_id] = now
    # Add 10 minutes (600 seconds)
    current_expiry = db.setdefault("temp_premium", {}).get(user_id, now)
    if current_expiry < now: current_expiry = now
    db["temp_premium"][user_id] = current_expiry + 600
    save_db()
    
    await update.message.reply_text("🎁 **𝗗𝗔𝗜𝗟𝗬 𝗕𝗢𝗡𝗨𝗦 𝗖𝗟𝗔𝗜𝗠𝗘𝗗!**\n✅ You received 10 Minutes of Premium.", parse_mode="Markdown")

# 🟢 NEW: Buy & Payment Approval
def get_default_payment_method():
    return """╭━━〔 💳 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐌𝐄𝐓𝐇𝐎𝐃𝐒 〕━━┈⊷
┃
┃ 🇵🇰 ᴇᴀsʏᴘᴀɪsᴀ (ᴘᴀᴋɪsᴛᴀɴ)
┃ 👤 ɴᴀᴍᴇ — 
┃ 📱 ɪʙᴀɴ — 
┃
┃ 🌍 ʙɪɴᴀɴᴄᴇ (ɪɴᴛᴇʀɴᴀᴛɪᴏɴᴀʟ)
┃ 👤 ɴᴀᴍᴇ — 
┃ 🆔 ʙɪɴᴀɴᴄᴇ ɪᴅ — 
┃
┃ 💱 ᴄᴜʀʀᴇɴᴛ ʀᴀᴛᴇ — 1 USDT = Rs. 280
┃ ━━━━━━━━━━━━━━━━━━━━━
┃ 📸 sᴄʀᴇᴇɴsʜᴏᴛ ɪs ᴍᴜsᴛ ғᴏʀ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ.
┃ ✅ ᴀғᴛᴇʀ ᴘᴀʏᴍᴇɴᴛ, sᴇɴᴅ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ ʜᴇʀᴇ ᴛᴏ ᴄᴏɴғɪʀᴍ.
╰━━━━━━━━━━━━━━━━━━━━━"""

async def buy_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = update.effective_user.id
    msg = db["settings"].get("payment_method") or get_default_payment_method()
    await update.message.reply_text(msg)
    awaiting_payment[user_id] = True

async def payset_command(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return

    current_payment_method = db["settings"].get("payment_method") or get_default_payment_method()
    payset_state[update.effective_user.id] = current_payment_method
    await update.message.reply_text(
        "Current payment method:\n\n" + current_payment_method +
        "\n\nSend the new payment method now. Send /cancel to keep the current one."
    )

async def handle_photo(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if broadcast_state.get(user_id) and is_owner(user_id):
        broadcast_state[user_id] = False
        await _broadcast_source(context, update.effective_chat.id, update.message.message_id, user_id)
        return

    if not IS_CHILD_BOT and user_id in admin_bot_edit_state and admin_bot_edit_state[user_id].get("field") == "logo" and is_owner(user_id):
        edit = admin_bot_edit_state.pop(user_id)
        bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(edit["bot_id"])), None)
        if bot:
            bot_dir = _child_bot_dir(bot["id"])
            try:
                import shutil
                tg_file = await context.bot.get_file(update.message.photo[-1].file_id)
                await tg_file.download_to_drive(custom_path=str(bot_dir / "start.jpg"))
                png = bot_dir / "start.png"
                if png.exists(): png.unlink()
                save_db(); await _restart_created_bot(bot["id"])
                await update.message.reply_text("✅ Logo updated and applied.")
            except Exception:
                await update.message.reply_text("❌ Logo update failed.")
        return

    # Create-own-bot image step (main bot only).
    if not IS_CHILD_BOT and user_id in create_bot_state:
        st = create_bot_state[user_id]
        if st.get("step") == "image":
            st["photo_file_id"] = update.message.photo[-1].file_id
            st["step"] = "channel_link"
            await update.message.reply_text(
                "╭━━〔 7️⃣ 𝗦𝗧𝗘𝗣 𝗦𝗘𝗩𝗘𝗡 〕━━┈⊷\n"
                "┃ 📢 sᴇɴᴅ ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴍ ᴄʜᴀɴɴᴇʟ ʟɪɴᴋ.\n"
                "┃ 🔗 ᴇxᴀᴍᴘʟᴇ : https://t.me/aliwinc\n"
                "╰━━━━━━━━━━━━━━━━━━━━━┈⊷"
            )
            return

    if awaiting_payment.get(user_id):
        awaiting_payment[user_id] = False
        kb = [
            [InlineKeyboardButton("✅ Approve 1 Month", callback_data=f"pay_app_{user_id}")],
            [InlineKeyboardButton("❌ Decline", callback_data=f"pay_dec_{user_id}")]
        ]
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=update.message.photo[-1].file_id,
            caption=f"💳 **𝗡𝗘𝗪 𝗣𝗔𝗬𝗠𝗘𝗡𝗧 𝗥𝗘𝗖𝗘𝗜𝗩𝗘𝗗**\n👤 User ID: `{user_id}`\n🗣 Name: {update.effective_user.first_name}",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ Screenshot sent to Admin for verification. Please wait for approval.")


def _telegram_url(value):
    value = (value or "").strip()
    if value.startswith("http://") or value.startswith("https://"): return value
    if value.startswith("@"): return "https://t.me/" + value[1:]
    return "https://t.me/" + value.lstrip("@")

def _normalize_link(value):
    value = value.strip()
    if value.startswith("@"): return "https://t.me/" + value[1:]
    if value.startswith("https://t.me/") or value.startswith("http://t.me/"): return value
    return None

def _small_caps(text):
    mapping = str.maketrans({
        "a":"ᴀ","b":"ʙ","c":"ᴄ","d":"ᴅ","e":"ᴇ","f":"ғ","g":"ɢ","h":"ʜ","i":"ɪ","j":"ᴊ","k":"ᴋ","l":"ʟ","m":"ᴍ","n":"ɴ","o":"ᴏ","p":"ᴘ","q":"ǫ","r":"ʀ","s":"s","t":"ᴛ","u":"ᴜ","v":"ᴠ","w":"ᴡ","x":"x","y":"ʏ","z":"ᴢ",
        "A":"ᴀ","B":"ʙ","C":"ᴄ","D":"ᴅ","E":"ᴇ","F":"ғ","G":"ɢ","H":"ʜ","I":"ɪ","J":"ᴊ","K":"ᴋ","L":"ʟ","M":"ᴍ","N":"ɴ","O":"ᴏ","P":"ᴘ","Q":"ǫ","R":"ʀ","S":"s","T":"ᴛ","U":"ᴜ","V":"ᴠ","W":"ᴡ","X":"x","Y":"ʏ","Z":"ᴢ"})
    return str(text).translate(mapping)

def _key_prefix(text):
    # The user's Step-5 Key Name is used literally as the generated-key prefix.
    # Referral-link text is unrelated and remains unchanged (e.g. "ʏᴏᴜʀ ʟɪɴᴋ").
    value = ' '.join(str(text).strip().split())
    value = ''.join(ch for ch in value if ch.isalnum() or ch in (' ', '_', '-'))
    return value[:32].strip() or "ALIWBANBOT"

def _child_admin_ids(bot):
    ids = bot.get("admin_ids") or bot.get("chat_ids") or [bot.get("chat_id")]
    return [int(x) for x in ids if x is not None and str(x).lstrip('-').isdigit()]

def _child_bot_dir(bot_id):
    return DATA_DIR / "created_bots" / str(bot_id)

async def createownbot_command(update: Update, context: CallbackContext):
    if IS_CHILD_BOT or await maintenance_guard(update, context): return
    uid = update.effective_user.id

    # One user = one active created bot. They can create another only after deleting it.
    existing = next((b for b in db.get("created_bots", []) if b.get("creator_id") == uid and b.get("status") != "deleted"), None)
    if existing:
        status = existing.get("status", "unknown")
        kb = [[InlineKeyboardButton(f"🤖 {existing.get('name', 'BAN BOT')}", callback_data=f"mybot_view_{existing['id']}", style="primary")]]
        await update.message.reply_text(
            "╭━━〔 🤖 𝗬𝗢𝗨𝗥 𝗕𝗢𝗧 〕━━┈⊷\n"
            f"┃ 🟢 Status: {status.upper()}\n"
            "┃\n"
            "┃ ʏᴏᴜ ᴀʟʀᴇᴀᴅʏ ᴄʀᴇᴀᴛᴇᴅ ᴏɴᴇ ʙᴏᴛ\n"
            "┃ ᴅᴇʟᴇᴛᴇ ɪᴛ ғɪʀsᴛ ɪғ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ\n"
            "┃ ᴀ ɴᴇᴡ ʙᴏᴛ.\n"
            "╰━━━━━━━━━━━━━━━━━━━━━┈⊷",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    create_bot_state[uid] = {"step": "token"}
    await update.message.reply_text(
        "╭━━〔 🤖 𝗖𝗥𝗘𝗔𝗧𝗘 𝗢𝗪𝗡 𝗕𝗢𝗧 〕━━┈⊷\n"
        "┃ 🎬 𝗡𝗘𝗘𝗗 𝗛𝗘𝗟𝗣?\n"
        "┃ ɪғ ʏᴏᴜ ᴅᴏɴᴛ ᴋɴᴏᴡ ʜᴏᴡ ᴛᴏ ᴍᴀᴋᴇ ʙᴏᴛ,,\n"
        "┃ ᴡᴀᴛᴄʜ ᴛʜɪs ᴠɪᴅᴇᴏ\n"
        f"┃ 🔗 𝗩𝗜𝗗𝗘𝗢 : {db['settings'].get('create_video_url', 'https://youtu.be/pK-nEabN_MM?si=muPPBzbpgAuH_BcM/')}\n"
        "┃\n"
        "┃ 1️⃣ 𝗦𝗧𝗘𝗣 𝗢𝗡𝗘\n"
        "┃ 🤖 ɢᴏ ᴛᴏ @BotFather ᴀɴᴅ ᴄʀᴇᴀᴛᴇ ʏᴏᴜʀ ʙᴏᴛ.\n"
        "┃ 🔑 ᴛʜᴇɴ sᴇɴᴅ ᴍᴇ ʏᴏᴜʀ ʙᴏᴛ ᴛᴏᴋᴇɴ.\n"
        "╰━━━━━━━━━━━━━━━━━━━━━┈⊷\n\n"
        "❌ sᴇɴᴅ /cancel ᴀɴʏᴛɪᴍᴇ ᴛᴏ sᴛᴏᴘ.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤖 Create Your Own Ban Bot", callback_data="createown_start", style="success")]]),
        disable_web_page_preview=True
    )

async def _announce_new_clone(update, context, bot_username, bot_id=None):
    """Announce every successfully created clone in the ALIW updates channel."""
    main_username = (await context.bot.get_me()).username or ""
    deep_link = f"https://t.me/{main_username}?start=createownbot" if main_username else "https://t.me/"
    user = update.effective_user
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Karachi")).strftime("%I:%M %p")
    except Exception:
        now = datetime.now().strftime("%I:%M %p")

    # Keep the announcement compact: no bot username line.
    text = (
        "<blockquote>"
        "☠️ ɴᴇᴡ ʙᴀɴ ʙᴏᴛ ᴄʟᴏɴᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ\n\n"
        f"👤 ᴜsᴇʀ : {html.escape(user.full_name)}\n"
        f"🆔 ᴛɢ ɪᴅ : {user.id}\n"
        f"🕐 ᴛɪᴍᴇ : {now}\n\n"
        "☠️ ᴘᴏᴡᴇʀᴇᴅ ʙʏ 𝝙𝗟𝝞𝗪 ᴛᴇᴄʜ ᴛᴇᴀᴍ"
        "</blockquote>"
    )
    kb = [[InlineKeyboardButton("🤖 ᴄʀᴇᴀᴛᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴀɴ ʙᴏᴛ", url=deep_link, style="success")]]
    markup = InlineKeyboardMarkup(kb)
    # Use a separate bundled image for clone announcements.
    # Replace bot.png to change only the announcement image; start.png stays unchanged.
    announcement_logo_path = Path("bot.png")
    logo_path = announcement_logo_path if announcement_logo_path.exists() else None
    try:
        if logo_path:
            with open(logo_path, "rb") as logo_file:
                await context.bot.send_photo(
                    chat_id=ANNOUNCEMENT_CHANNEL,
                    photo=logo_file,
                    caption=text,
                    reply_markup=markup,
                    parse_mode=ParseMode.HTML
                )
        else:
            await context.bot.send_message(chat_id=ANNOUNCEMENT_CHANNEL, text=text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        print(f"⚠️ Clone announcement first attempt failed: {e}")
        try:
            if logo_path:
                with open(logo_path, "rb") as logo_file:
                    await context.bot.send_photo(
                        chat_id=ANNOUNCEMENT_CHANNEL,
                        photo=logo_file,
                        caption=text,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
            else:
                await context.bot.send_message(chat_id=ANNOUNCEMENT_CHANNEL, text=text, reply_markup=markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return True
        except Exception as e2:
            print(f"⚠️ Clone announcement retry failed: {e2}")
            return False

async def _launch_child_process(bot_id, bot_dir, env):
    """Start a child bot and verify that it stays alive briefly. Keep a per-bot log for startup errors."""
    bot_id = str(bot_id)
    log_path = Path(bot_dir) / "runtime.log"
    log_file = open(log_path, "ab", buffering=0)
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "app.py", cwd=str(bot_dir), env=env,
            stdout=log_file, stderr=log_file
        )
        child_processes[bot_id] = proc
        child_log_files[bot_id] = log_file
        # Give python-telegram-bot a moment to initialize so an immediate crash
        # is reported as a real startup error instead of a false RUNNING state.
        await asyncio.sleep(1.2)
        if proc.returncode is not None:
            child_processes.pop(bot_id, None)
            log_file.close()
            child_log_files.pop(bot_id, None)
            try:
                details = log_path.read_text(errors="replace")[-1200:].strip()
            except Exception:
                details = ""
            raise RuntimeError(details or f"Child process exited with code {proc.returncode}")
        return proc
    except Exception:
        if bot_id not in child_processes:
            try: log_file.close()
            except Exception: pass
        raise

async def _finish_created_bot(uid, update, context):
    state = create_bot_state.pop(uid)
    bot_id = str(int(time.time() * 1000))
    bot_dir = _child_bot_dir(bot_id)
    bot_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(Path(__file__), bot_dir / "app.py")

    # Use the exact photo selected by the user for this child bot.
    photo_file_id = state.get("photo_file_id")
    if photo_file_id:
        try:
            tg_file = await context.bot.get_file(photo_file_id)
            await tg_file.download_to_drive(custom_path=str(bot_dir / "start.jpg"))
        except Exception:
            if IMG_PATH.exists(): shutil.copy2(IMG_PATH, bot_dir / "start.png")
    elif IMG_PATH.exists():
        shutil.copy2(IMG_PATH, bot_dir / "start.png")

    name = state["name"].strip() or "BAN BOT"
    channel_link = state["channel_link"]
    username_link = state["username_link"]
    chat_id = int(state["chat_id"])
    record = {
        "id": bot_id,
        "bot_token": state["token"],
        "chat_id": chat_id,
        "chat_ids": [chat_id],
        "name": name,
        "ban_name": _small_caps(state.get("ban_name", name)),
        "key_name": state.get("key_name", "ALIWBANBOT"),
        "admin_ids": [chat_id],
        "bot_username": state.get("bot_username", ""),
        "channel_link": channel_link,
        "username_link": username_link,
        "creator_id": uid,
        "creator_username": update.effective_user.username or "@" + str(update.effective_user.id),
        "created_at": int(time.time()),
        "status": "starting",
    }
    db.setdefault("created_bots", []).append(record)
    save_db()

    env = os.environ.copy()
    env.update({
        "ALIW_CHILD_BOT": "1",
        "TELEGRAM_TOKEN": state["token"],
        "OWNER_ID": str(chat_id),
        "ADMIN_CHAT_ID": str(chat_id),
        "ADMIN_CHAT_IDS": ",".join(str(x) for x in record.get("admin_ids", [chat_id])),
        "SUPER_OWNER_ID": str(chat_id),
        "OWNER_USERNAME": username_link,
        "BOT_DISPLAY_NAME": name,
        "CHILD_BAN_NAME": state.get("ban_name", name),
        "CHILD_KEY_NAME": state.get("key_name", "ALIWBANBOT"),
        "CHILD_CHANNEL_URL": channel_link,
        "CHILD_CHANNEL_ID": channel_link.split("/")[-1].split("?")[0] if channel_link else "",
        "IMG_PATH": "start.jpg",
    })
    try:
        proc = await _launch_child_process(bot_id, bot_dir, env)
        record["status"] = "running"
        record["pid"] = proc.pid
        save_db()
        bot_username = state.get("bot_username", "unknown")
        await update.message.reply_text(
            "╭━━〔 ✅ 𝗕𝗢𝗧 𝗜𝗦 𝗥𝗘𝗔𝗗𝗬 〕━━┈⊷\n"
            f"┃ 🤖 ɴᴀᴍᴇ : {name}\n"
            f"┃ 🔗 ᴜsᴇʀɴᴀᴍᴇ : @{bot_username}\n"
            f"┃ 🟢 sᴛᴀᴛᴜs: RUNNING\n"
            "┃\n"
            "┃ ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ʏᴏᴜʀ ʙᴏᴛ.\n"
            "╰━━━━━━━━━━━━━━━━━━━━━┈⊷",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🚀 Open @{bot_username}", url=f"https://t.me/{bot_username}", style="success")]])
        )
        await _announce_new_clone(update, context, bot_username, bot_id)
    except Exception as e:
        record["status"] = "failed"
        record["error"] = str(e)[:200]
        save_db()
        err = record.get("error", "Unknown startup error")
        await update.message.reply_text(
            "❌ Bot create ho gaya, lekin startup fail hua.\n"
            "🛠️ Startup log save ho gaya hai; admin panel se bot dobara start kiya ja sakta hai.\n\n"
            f"⚠️ {err[:500]}"
        )

async def _delete_created_bot(bot_id):
    bot = next((b for b in db.get("created_bots", []) if b.get("id") == bot_id), None)
    if not bot:
        return False
    proc = child_processes.pop(bot_id, None)
    if proc:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            try: proc.kill()
            except Exception: pass
    log_file = child_log_files.pop(str(bot_id), None)
    if log_file:
        try: log_file.close()
        except Exception: pass
    bot["status"] = "deleted"
    bot["deleted_at"] = int(time.time())
    save_db()
    import shutil
    try: shutil.rmtree(_child_bot_dir(bot_id), ignore_errors=True)
    except Exception: pass
    return True


async def _stop_created_bot(bot_id):
    bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(bot_id)), None)
    if not bot: return False
    proc = child_processes.pop(str(bot_id), None)
    if proc:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            try: proc.kill()
            except Exception: pass
    log_file = child_log_files.pop(str(bot_id), None)
    if log_file:
        try: log_file.close()
        except Exception: pass
    bot["status"] = "stopped"
    bot.pop("pid", None)
    save_db()
    return True

def _sync_child_app(bot_id):
    bot_dir = _child_bot_dir(bot_id)
    bot_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(Path(__file__), bot_dir / "app.py")


async def _start_created_bot(bot_id):
    bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(bot_id) and b.get("status") != "deleted"), None)
    if not bot: return False
    bot_dir = _child_bot_dir(bot_id)
    if not bot_dir.exists() or not (bot_dir / "app.py").exists():
        bot["status"] = "missing"; save_db(); return False
    if str(bot_id) in child_processes:
        return True
    _sync_child_app(bot_id)
    chat_ids = bot.get("chat_ids") or [bot.get("chat_id")]
    env = os.environ.copy()
    env.update({
        "ALIW_CHILD_BOT": "1",
        "TELEGRAM_TOKEN": bot.get("bot_token", ""),
        "OWNER_ID": str(chat_ids[0] or ""),
        "ADMIN_CHAT_ID": str(chat_ids[0] or ""),
        "ADMIN_CHAT_IDS": ",".join(str(x) for x in (bot.get("admin_ids") or chat_ids) if x is not None),
        "SUPER_OWNER_ID": str(chat_ids[0] or ""),
        "OWNER_USERNAME": bot.get("username_link", ""),
        "BOT_DISPLAY_NAME": bot.get("name", "BAN BOT"),
        "CHILD_BAN_NAME": bot.get("ban_name", bot.get("name", "BAN BOT")),
        "CHILD_KEY_NAME": bot.get("key_name", "ALIWBANBOT"),
        "CHILD_CHANNEL_URL": bot.get("channel_link", ""),
        "CHILD_CHANNEL_ID": (bot.get("channel_link", "").split("/")[-1].split("?")[0] if bot.get("channel_link") else ""),
        "IMG_PATH": "start.jpg" if (bot_dir / "start.jpg").exists() else "start.png",
    })
    try:
        proc = await _launch_child_process(bot_id, bot_dir, env)
        bot["status"] = "running"; bot["pid"] = proc.pid
        save_db(); return True
    except Exception as e:
        bot["status"] = "failed"; bot["error"] = str(e)[:200]; save_db(); return False

async def _restart_created_bot(bot_id):
    await _stop_created_bot(bot_id)
    return await _start_created_bot(bot_id)

def _bot_admin_keyboard(bot_id, status):
    kb = []
    if status == "running":
        kb.append([InlineKeyboardButton("⏹️ Stop Bot", callback_data=f"bot_stop_{bot_id}", style="danger"), InlineKeyboardButton("🗑️ Delete", callback_data=f"bot_delete_{bot_id}", style="danger")])
    else:
        kb.append([InlineKeyboardButton("▶️ Start Bot", callback_data=f"bot_start_{bot_id}", style="success"), InlineKeyboardButton("🗑️ Delete", callback_data=f"bot_delete_{bot_id}", style="danger")])
    kb += [
        [InlineKeyboardButton("✏️ Change Name", callback_data=f"bot_edit_name_{bot_id}", style="primary"), InlineKeyboardButton("🏷️ Ban Name", callback_data=f"bot_edit_ban_name_{bot_id}", style="primary")],
        [InlineKeyboardButton("🔑 Key Name", callback_data=f"bot_edit_key_name_{bot_id}", style="primary"), InlineKeyboardButton("🆔 Replace Chat ID", callback_data=f"bot_edit_chat_{bot_id}", style="primary")],
        [InlineKeyboardButton("🔄 Replace Extra ID", callback_data=f"bot_replace_chat_{bot_id}", style="success"), InlineKeyboardButton("➕ Add Admin ID", callback_data=f"bot_add_admin_{bot_id}", style="success")],
        [InlineKeyboardButton("📢 Change Channel", callback_data=f"bot_edit_channel_{bot_id}", style="primary"), InlineKeyboardButton("👑 Admin IDs", callback_data=f"bot_admins_{bot_id}", style="primary")],
        [InlineKeyboardButton("👤 Change Username", callback_data=f"bot_edit_username_{bot_id}", style="primary"), InlineKeyboardButton("🖼️ Change Logo", callback_data=f"bot_edit_logo_{bot_id}", style="primary")],
        [InlineKeyboardButton("🔑 Change Token", callback_data=f"bot_edit_token_{bot_id}", style="danger"), InlineKeyboardButton("🔙 Back", callback_data="allbots_back", style="primary")]
    ]
    return kb

def _bot_details_text(bot):
    ids = bot.get("chat_ids") or [bot.get("chat_id")]
    return (f"╭━━〔 🤖 𝗕𝗢𝗧 𝗗𝗘𝗧𝗔𝗜𝗟𝗦 〕━━┈⊷\n"
            f"┃ 🏷️ Name: {bot.get('name')}\n"
            f"┃ 🏷️ Ban/Unban Name: {bot.get('ban_name', bot.get('name'))}\n"
            f"┃ 🔑 Key Name: {bot.get('key_name', 'ALIWBANBOT')}\n"
            f"┃ 🤖 Username: @{str(bot.get('bot_username','')).lstrip('@')}\n"
            f"┃ 🔑 Token: `{bot.get('bot_token') or 'Not set'}`\n"
            f"┃ 🆔 Chat IDs: {', '.join(str(x) for x in ids if x is not None)}\n"
            f"┃ 👑 Admin IDs: {', '.join(str(x) for x in _child_admin_ids(bot)) or 'None'}\n"
            f"┃ 📢 Channel: {bot.get('channel_link') or 'Not set'}\n"
            f"┃ 👤 Username Link: {bot.get('username_link') or 'Not set'}\n"
            f"┃ 👨‍💻 Created By: @{str(bot.get('creator_username','')).lstrip('@')}\n"
            f"┃ 🟢 Status: {bot.get('status','unknown')}\n"
            f"╰━━━━━━━━━━━━━━━━━━━━━┈⊷")

async def allbots_command(update: Update, context: CallbackContext):
    # /allbots is MAIN-BOT-ONLY. Child bots never expose or execute it.
    if IS_CHILD_BOT:
        return
    uid = update.effective_user.id if update.effective_user else 0
    # Use the same owner/admin IDs used by the main admin panel, including
    # explicit OWNER_ID/ADMIN_CHAT_ID values, so the command cannot silently
    # fail when the database owner list is empty or customized.
    allowed_ids = {SUPER_OWNER_ID, OWNER_ID, ADMIN_CHAT_ID, *ADMIN_CHAT_IDS}
    allowed_ids.update(
        int(x) for x in db.get("owners", [])
        if str(x).lstrip("-").isdigit()
    )
    if uid not in allowed_ids and not is_owner(uid):
        return

    try:
        bots = db.get("created_bots", [])
        if not isinstance(bots, list):
            bots = []
        bots = [b for b in bots if isinstance(b, dict) and b.get("id")]

        if not bots:
            await update.message.reply_text(
                "╭━━〔 🤖 𝗔𝗟𝗟 𝗕𝗢𝗧𝗦 〕━━┈⊷\n"
                "┃ No created bots yet.\n"
                "╰━━━━━━━━━━━━━━━━━━━━━┈⊷"
            )
            return

        # Send compact pages to stay below Telegram's text/button limits and
        # avoid Markdown parsing failures from user-provided bot names.
        for page_start in range(0, len(bots), 20):
            page = bots[page_start:page_start + 20]
            page_no = page_start // 20 + 1
            page_count = (len(bots) + 19) // 20
            lines = [f"🤖 ALL BOTS — {len(bots)} total (page {page_no}/{page_count})"]
            kb = []
            for i, b in enumerate(page, page_start + 1):
                status = "🟢" if b.get("status") == "running" else "🔴"
                bot_user = str(b.get("bot_username") or "unknown").lstrip("@")
                bot_id = str(b["id"])
                name = str(b.get("name") or "BAN BOT")
                lines.append(f"{status} {i}. {name} | @{bot_user} | Chat ID: {b.get('chat_id', 'N/A')}")
                button_text = f"{status} {name} • @{bot_user}"
                if len(button_text) > 60:
                    button_text = button_text[:57] + "..."
                kb.append([InlineKeyboardButton(
                    button_text,
                    callback_data=f"bot_view_{bot_id}",
                    style=("success" if b.get("status") == "running" else "danger")
                )])
            await update.message.reply_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(kb) if kb else None
            )
    except Exception as e:
        print(f"❌ /allbots failed: {e}")
        traceback.print_exc()
        await update.message.reply_text(
            "⚠️ ᴀʟʟ ʙᴏᴛs ᴄᴏᴍᴍᴀɴᴅ ᴇʀʀᴏʀ. ᴘʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ᴛʜᴇ ʙᴏᴛ ʟᴏɢ."
        )

async def referral_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = update.effective_user.id
    if str(user_id) not in db["referral_codes"]:
        db["referral_codes"][str(user_id)] = generate_referral_code(user_id)
        save_db()
    
    code = db["referral_codes"][str(user_id)]
    ref_count = db["referrals"].get(str(user_id), 0)
    target = db["settings"]["ref_target"]
    hours = db["settings"]["ref_reward_hours"]
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{code}"
    
    msg = f"""╭━━〔 𝗥𝗘𝗙𝗘𝗥𝗥𝗔𝗟 𝗦𝗬𝗦𝗧𝗘𝗠 〕━━┈⊷
┃ 👤 ᴜꜱᴇʀ: {update.effective_user.first_name[:15]}
┃ 📊 ʀᴇꜰᴇʀʀᴀʟꜱ: {ref_count}/{target}
┃
┃ 📋 ʏᴏᴜʀ ʟɪɴᴋ:
┃ `{link}`
┃
┃ 💰 ʀᴇᴡᴀʀᴅ:
┃ ⭐ {target} ʀᴇꜰᴇʀʀᴀʟꜱ = {hours} ʜᴏᴜʀ(ꜱ) ᴘʀᴇᴍɪᴜᴍ
╰━━━━━━━━━━━━━━━━━━━━━┈⊷"""
    await update.message.reply_text(msg, parse_mode="Markdown")

async def redeem_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("╭━━〔 𝗘𝗥𝗥𝗢𝗥 〕━━┈⊷\n┃ ⚠️ ᴜꜱᴀɢᴇ: `/redeem <key>`\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
        return
    key = context.args[0]
    if key in db.get("redeem_keys", {}) and not db["redeem_keys"][key]["used"]:
        hrs = db["redeem_keys"][key]["hours"]
        db["redeem_keys"][key]["used"] = True
        db.setdefault("temp_premium", {})[str(user_id)] = time.time() + (hrs * 3600)
        save_db()
        await update.message.reply_text(f"╭━━〔 𝗥𝗘𝗗𝗘𝗘𝗠 𝗦𝗨𝗖𝗖𝗘𝗦𝗦 〕━━┈⊷\n┃ 🎉 ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴛɪᴠᴀᴛᴇᴅ ꜰᴏʀ {hrs} ʜᴏᴜʀꜱ!\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
    else:
        await update.message.reply_text("╭━━〔 𝗘𝗥𝗥𝗢𝗥 〕━━┈⊷\n┃ ❌ ɪɴᴠᴀʟɪᴅ ᴏʀ ᴜꜱᴇᴅ ᴋᴇʏ!\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")

async def check_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_premium(update.effective_user.id):
        await send_denied_message(update)
        return
    if not context.args:
        await update.message.reply_text("╭━━〔 𝗘𝗥𝗥𝗢𝗥 〕━━┈⊷\n┃ ⚠️ ᴜꜱᴀɢᴇ: `/check <+92...>`\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
        return
    target = normalize_number(context.args[0])
    await update.message.reply_text(f"╭━━〔 𝗪𝗛𝗔𝗧𝗦𝗔𝗣𝗣 𝗖𝗛𝗘𝗖𝗞 〕━━┈⊷\n┃ 📞 ɴᴜᴍʙᴇʀ: `{target}`\n┃ ✅ ꜱᴛᴀᴛᴜꜱ: ᴀᴄᴛɪᴠᴇ\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")

# ===== PREMIUM ACTIONS =====
async def ban_perm_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await send_denied_message(update)
        return
    
    if not context.args:
        await update.message.reply_text("╭━━〔 𝗘𝗥𝗥𝗢𝗥 〕━━┈⊷\n┃ ⚠️ ᴜꜱᴀɢᴇ: `/ban_perm <ɴᴜᴍʙᴇʀ>`\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
        return
        
    is_cd, time_left = check_cooldown(user_id)
    if is_cd:
        await update.message.reply_text(f"⏳ ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ {time_left}ꜱ...")
        return
        
    target = context.args[0]
    if is_anti_number(target):
        await update.message.reply_text(anti_number_message(normalize_number(target)), parse_mode="Markdown")
        return
    target = normalize_number(target)
    msg = await update.message.reply_text(f"╭━━〔 𝗣𝗘𝗥𝗠𝗔𝗡𝗘𝗡𝗧 𝗕𝗔𝗡 〕━━┈⊷\n┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*\n┃ ⚠️ {get_progress_bar(0, 5)} ɪɴɪᴛɪᴀʟɪᴢɪɴɢ...\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
    
    stages = [
        ("📧 ᴇᴍᴀɪʟ ʀᴇᴘᴏʀᴛɪɴɢ...", 1),
        ("👤 ᴍᴀɴᴜᴀʟ ʀᴇᴘᴏʀᴛɪɴɢ...", 2),
        ("🤖 ᴍᴀꜱꜱ ᴀᴘɪ ʀᴇᴘᴏʀᴛɪɴɢ...", 3),
        ("🔄 ꜱᴘᴀᴍ ʙʟᴏᴄᴋ ɪɴᴊᴇᴄᴛɪᴏɴ...", 4),
        ("⚠️ ꜰɪɴᴀʟ ʙᴀɴ ᴇxᴇᴄᴜᴛɪᴏɴ...", 5)
    ]
    for text, step in stages:
        await asyncio.sleep(4)
        await msg.edit_text(f"╭━━〔 𝗣𝗘𝗥𝗠𝗔𝗡𝗘𝗡𝗧 𝗕𝗔𝗡 〕━━┈⊷\n┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*\n┃ 🔄 {get_progress_bar(step, 5)}\n┃ ⚡ {text}\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")

    db["stats"]["total_bans"] += 1
    save_db()
    final_msg = f"""╭━━〔 𝗕𝗔𝗡 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 〕━━┈⊷
┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*
┃ ☠️ ʙᴀɴ ᴅᴏɴᴇ ʙʏ {CHILD_BAN_NAME}
┃
┃ 🩸 𝗤𝘂𝗼𝘁𝗲: "ᴛʜᴇ ᴡᴇᴀᴋ ᴀʀᴇ ᴍᴇᴀᴛ, ᴀɴᴅ ᴛʜᴇ ꜱᴛʀᴏɴɢ ᴅᴏ ᴇᴀᴛ."
┃
┃ 📌 𝗡𝗼𝘁𝗲: ɪꜰ ʏᴏᴜʀ ɴᴜᴍʙᴇʀ ɪꜱ ɴᴏᴛ ʙᴀɴɴᴇᴅ, 
┃ ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ᴡɪᴛʜɪɴ 24-48 ʜᴏᴜʀꜱ.
╰━━━━━━━━━━━━━━━━━━━━━┈⊷"""
    await msg.edit_text(final_msg, parse_mode="Markdown")

async def ban_temp_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await send_denied_message(update)
        return
        
    if not context.args:
        await update.message.reply_text("╭━━〔 𝗘𝗥𝗥𝗢𝗥 〕━━┈⊷\n┃ ⚠️ ᴜꜱᴀɢᴇ: `/ban_temp <ɴᴜᴍʙᴇʀ>`\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
        return
        
    is_cd, time_left = check_cooldown(user_id)
    if is_cd:
        await update.message.reply_text(f"⏳ ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ {time_left}ꜱ...")
        return
        
    target = context.args[0]
    if is_anti_number(target):
        await update.message.reply_text(anti_number_message(normalize_number(target)), parse_mode="Markdown")
        return
    target = normalize_number(target)
    msg = await update.message.reply_text(f"╭━━〔 𝗧𝗘𝗠𝗣𝗢𝗥𝗔𝗥𝗬 𝗕𝗔𝗡 〕━━┈⊷\n┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*\n┃ ⚠️ {get_progress_bar(0, 5)} ɪɴɪᴛɪᴀʟɪᴢɪɴɢ...\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
    
    stages = [
        ("📧 ᴇᴍᴀɪʟ ʀᴇᴘᴏʀᴛɪɴɢ (ᴛᴇᴍᴘ ꜱᴄʀɪᴘᴛꜱ)...", 1),
        ("👤 ᴍᴀɴᴜᴀʟ ʀᴇᴘᴏʀᴛɪɴɢ ᴠɪᴀ 3 ᴀᴄᴄᴏᴜɴᴛꜱ...", 2),
        ("🤖 ᴍᴀꜱꜱ ʀᴇᴘᴏʀᴛɪɴɢ ꜰʀᴏᴍ ᴀᴘɪ...", 3),
        ("🔄 ꜱᴘᴀᴍ ʙʟᴏᴄᴋɪɴɢ & ᴜɴʙʟᴏᴄᴋɪɴɢ...", 4),
        ("⚠️ ꜱᴇɴᴅɪɴɢ ᴛᴇᴍᴘ-ʙᴀɴ ʀᴇQᴜᴇꜱᴛꜱ...", 5)
    ]
    for text, step in stages:
        await asyncio.sleep(4)
        await msg.edit_text(f"╭━━〔 𝗧𝗘𝗠𝗣𝗢𝗥𝗔𝗥𝗬 𝗕𝗔𝗡 〕━━┈⊷\n┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*\n┃ 🔄 {get_progress_bar(step, 5)}\n┃ ⚡ {text}\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")

    db["stats"]["total_bans"] += 1
    save_db()
    final_msg = f"""╭━━〔 𝗧𝗘𝗠𝗣 𝗕𝗔𝗡 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 〕━━┈⊷
┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*
┃ ⏳ ʙᴀɴ ᴅᴏɴᴇ ʙʏ {CHILD_BAN_NAME}
┃
┃ 🩸 𝗤𝘂𝗼𝘁𝗲: "ᴛɪᴍᴇ ɪꜱ ᴀɴ ɪʟʟᴜꜱɪᴏɴ, ʙᴜᴛ ᴛʜᴇ ʙᴀɴ ɪꜱ ʀᴇᴀʟ."
┃
┃ 📌 𝗡𝗼𝘁𝗲: ɪꜰ ʏᴏᴜʀ ɴᴜᴍʙᴇʀ ɪꜱ ɴᴏᴛ ʙᴀɴɴᴇᴅ, 
┃ ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ᴡɪᴛʜɪɴ 24-48 ʜᴏᴜʀꜱ.
╰━━━━━━━━━━━━━━━━━━━━━┈⊷"""
    await msg.edit_text(final_msg, parse_mode="Markdown")

async def unban_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await send_denied_message(update)
        return
        
    if not context.args:
        await update.message.reply_text("╭━━〔 𝗘𝗥𝗥𝗢𝗥 〕━━┈⊷\n┃ ⚠️ ᴜꜱᴀɢᴇ: `/unban <ɴᴜᴍʙᴇʀ>`\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
        return
        
    is_cd, time_left = check_cooldown(user_id)
    if is_cd:
        await update.message.reply_text(f"⏳ ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ {time_left}ꜱ...")
        return
        
    target = context.args[0]
    if is_anti_number(target):
        await update.message.reply_text(anti_number_message(normalize_number(target)), parse_mode="Markdown")
        return
    target = normalize_number(target)
    msg = await update.message.reply_text(f"╭━━〔 𝗨𝗡𝗕𝗔𝗡 𝗥𝗘𝗤𝗨𝗘𝗦𝗧 〕━━┈⊷\n┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*\n┃ ⚠️ {get_progress_bar(0, 5)} ɪɴɪᴛɪᴀʟɪᴢɪɴɢ...\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")
    
    stages = [
        ("📧 ᴇᴍᴀɪʟɪɴɢ ꜰʀᴏᴍ 100+ ᴀᴄᴛɪᴠᴇ ᴇᴍᴀɪʟꜱ...", 1),
        ("👤 ʀᴇQᴜᴇꜱᴛɪɴɢ ᴠɪᴀ 5+ ʟɪɴᴋᴇᴅ ᴀᴄᴄᴏᴜɴᴛꜱ...", 2),
        ("🌐 ʙʏᴘᴀꜱꜱɪɴɢ ᴀɪ ꜱᴜᴘᴘᴏʀᴛ...", 3),
        ("🛡️ ɪɴᴊᴇᴄᴛɪɴɢ ᴀᴘᴘᴇᴀʟ ʀᴇQᴜᴇꜱᴛꜱ...", 4),
        ("🕊️ ꜰɪɴᴀʟ ᴀᴘᴘᴇᴀʟ ꜱᴜʙᴍɪꜱꜱɪᴏɴ...", 5)
    ]
    for text, step in stages:
        await asyncio.sleep(4)
        await msg.edit_text(f"╭━━〔 𝗨𝗡𝗕𝗔𝗡 𝗥𝗘𝗤𝗨𝗘𝗦𝗧 〕━━┈⊷\n┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*\n┃ 🔄 {get_progress_bar(step, 5)}\n┃ ⚡ {text}\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown")

    db["stats"]["total_unbans"] += 1
    save_db()
    final_msg = f"""╭━━〔 𝗨𝗡𝗕𝗔𝗡 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 〕━━┈⊷
┃ 📞 ᴛᴀʀɢᴇᴛ: *{target}*
┃ 🕊️ ᴜɴʙᴀɴ ᴅᴏɴᴇ ʙʏ {CHILD_BAN_NAME}
┃
┃ 🌟 𝗤𝘂𝗼𝘁𝗲: "ᴇᴠᴇʀʏ ꜱᴇᴛʙᴀᴄᴋ ɪꜱ ᴀ ꜱᴇᴛᴜᴘ ꜰᴏʀ ᴀ ᴄᴏᴍᴇʙᴀᴄᴋ."
┃
┃ 📌 𝗡𝗼𝘁𝗲: ɪꜰ ʏᴏᴜʀ ɴᴜᴍʙᴇʀ ɪꜱ ɴᴏᴛ ᴜɴʙᴀɴɴᴇᴅ, 
┃ ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ᴡɪᴛʜɪɴ 24-48 ʜᴏᴜʀꜱ.
╰━━━━━━━━━━━━━━━━━━━━━┈⊷"""
    await msg.edit_text(final_msg, parse_mode="Markdown")

# ===== NEW ADVANCED ADMIN & OWNER COMMANDS =====

async def addprem_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    try:
        uid = context.args[0]
        days = int(context.args[1])
        db.setdefault("temp_premium", {})[str(uid)] = time.time() + (days * 86400)
        save_db()
        await update.message.reply_text(f"✅ Added {days} Days Premium to `{uid}`", parse_mode="Markdown")
        try: await context.bot.send_message(chat_id=uid, text=f"🎉 **CONGRATULATIONS!**\nYou have been granted {days} Days Premium by Admin.")
        except: pass
    except: await update.message.reply_text("⚠️ Usage: `/addprem <user_id> <days>`")

async def delprem_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    try:
        uid = context.args[0]
        if uid in db["temp_premium"]: del db["temp_premium"][uid]
        if int(uid) in db["premium"]: db["premium"].remove(int(uid))
        save_db()
        await update.message.reply_text(f"✅ Premium removed from `{uid}`", parse_mode="Markdown")
    except: await update.message.reply_text("⚠️ Usage: `/delprem <user_id>`")

async def addowner_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_super_owner(update.effective_user.id): 
        await update.message.reply_text("❌ Only Super Owner can use this command.")
        return
    try:
        uid = context.args[0]
        days = int(context.args[1])
        db.setdefault("temp_owners", {})[str(uid)] = time.time() + (days * 86400)
        save_db()
        await update.message.reply_text(f"✅ User `{uid}` is now an Owner for {days} days.", parse_mode="Markdown")
    except: await update.message.reply_text("⚠️ Usage: `/addowner <user_id> <days>`")

async def delowner_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_super_owner(update.effective_user.id): return
    try:
        uid = context.args[0]
        if uid in db["temp_owners"]: del db["temp_owners"][uid]
        if int(uid) in db["owners"]: db["owners"].remove(int(uid))
        save_db()
        await update.message.reply_text(f"✅ Ownership revoked for `{uid}`", parse_mode="Markdown")
    except: await update.message.reply_text("⚠️ Usage: `/delowner <user_id>`")

async def banuser_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    try:
        uid = context.args[0]
        if uid not in db["banned_users"]: db["banned_users"].append(uid)
        save_db()
        await update.message.reply_text(f"🚫 User `{uid}` banned from bot.", parse_mode="Markdown")
    except: await update.message.reply_text("⚠️ Usage: `/banuser <user_id>`")

async def unbanuser_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    try:
        uid = context.args[0]
        if uid in db["banned_users"]: db["banned_users"].remove(uid)
        save_db()
        await update.message.reply_text(f"✅ User `{uid}` unbanned.", parse_mode="Markdown")
    except: await update.message.reply_text("⚠️ Usage: `/unbanuser <user_id>`")

async def userinfo_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    try:
        uid = context.args[0]
        ref = db["referrals"].get(uid, 0)
        prem = "Yes" if is_premium(int(uid)) else "No"
        ban = "Yes" if is_banned(uid) else "No"
        await update.message.reply_text(f"👤 **USER INFO:**\nID: `{uid}`\nPremium: {prem}\nBanned: {ban}\nReferrals: {ref}", parse_mode="Markdown")
    except: await update.message.reply_text("⚠️ Usage: `/userinfo <user_id>`")

async def genkey_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    try:
        if not context.args:
            raise Exception
        duration_text = context.args[0].strip().lower()
        if len(context.args) > 1 and context.args[1].strip().lower() in ("h", "d"):
            duration_text += context.args[1].strip().lower()
        if duration_text.endswith("d"):
            amount = int(duration_text[:-1])
            hours = amount * 24
            duration_label = f"{amount} Days"
        elif duration_text.endswith("h"):
            amount = int(duration_text[:-1])
            hours = amount
            duration_label = f"{amount} Hours"
        else:
            raise Exception
        if amount <= 0:
            raise Exception
        key = f"{_key_prefix(CHILD_KEY_NAME)}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
        db["redeem_keys"][key] = {"hours": hours, "used": False}
        save_db()
        await update.message.reply_text(f"🔑 **NEW KEY GENERATED**\nKey: `{key}`\nDuration: {duration_label}", parse_mode="Markdown")
    except:
        await update.message.reply_text("⚠️ Usage: `/genkey <number>h` or `/genkey <number>d`\nExample: `/genkey 30d`", parse_mode="Markdown")


async def render_anti_numbers(reply_func):
    numbers = db.get("anti_numbers", [])
    if not numbers:
        text = "╭━━〔 𝗔𝗡𝗧𝗜 𝗡𝗨𝗠𝗕𝗘𝗥𝗦 〕━━┈⊷\n┃ 🚫 ɴᴏ ᴏᴡɴᴇʀ ɴᴜᴍʙᴇʀs ᴀᴅᴅᴇᴅ.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷"
        kb = []
    else:
        text = "╭━━〔 𝗔𝗡𝗧𝗜 𝗡𝗨𝗠𝗕𝗘𝗥𝗦 〕━━┈⊷\n┃ 👑 ᴄʟɪᴄᴋ ᴀ ɴᴜᴍʙᴇʀ ᴛᴏ ʀᴇᴍᴏᴠᴇ ɪᴛ.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷"
        kb = [[InlineKeyboardButton(f"📞 {number}", callback_data=f"anti_view_{index}", style="primary")] for index, number in enumerate(numbers)]
    await reply_func(text, reply_markup=InlineKeyboardMarkup(kb) if kb else None)

async def antinum_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    if context.args:
        number = normalize_number(context.args[0])
        if not number:
            return
        numbers = db.setdefault("anti_numbers", [])
        if not is_anti_number(number):
            numbers.append(number)
            save_db()
            await update.message.reply_text(f"✅ Owner number added: `{number}`", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ Owner number already exists: `{number}`", parse_mode="Markdown")
    await render_anti_numbers(update.message.reply_text)

async def render_channels(reply_func):
    channels = db["settings"].get("channels", [])
    if not channels:
        text = "╭━━〔 𝗙𝗢𝗥𝗖𝗘 𝗝𝗢𝗜𝗡 𝗖𝗛𝗔𝗡𝗡𝗘𝗟𝗦 〕━━┈⊷\n┃ 🚫 ɴᴏ ᴄʜᴀɴɴᴇʟs ᴀᴅᴅᴇᴅ.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷"
        kb = [[InlineKeyboardButton("➕ 𝗔𝗱𝗱 𝗖ʜᴀɴɴᴇʟ", callback_data="ch_add_info", style="primary")]]
    else:
        lines = ["╭━━〔 𝗙𝗢𝗥𝗖𝗘 𝗝𝗢𝗜𝗡 𝗖𝗛𝗔𝗡𝗡𝗘𝗟𝗦 〕━━┈⊷"]
        kb = []
        for index, channel in enumerate(channels):
            lines.append(f"┃ {index + 1}. {channel['name']}\n┃    ID: {channel['id']}\n┃    Link: {channel['url']}")
            kb.append([InlineKeyboardButton(f"{index + 1}. {channel['name']}", callback_data=f"ch_view_{index}")])
        lines.append("╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
        text = "\n".join(lines)
        kb.append([InlineKeyboardButton("➕ 𝗔𝗱𝗱 𝗖ʜᴀɴɴᴇʟ", callback_data="ch_add_info", style="primary")])
    await reply_func(text, reply_markup=InlineKeyboardMarkup(kb))


async def channel_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    await render_channels(update.message.reply_text)


async def addchannel_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    try:
        data = " ".join(context.args).split("|")
        if len(data) != 3: raise Exception
        name, cid, url = data[0].strip(), data[1].strip(), data[2].strip()
        db["settings"]["channels"].append({"name": name, "id": cid, "url": url})
        save_db()
        await update.message.reply_text(f"╭━━〔 𝗖𝗛𝗔𝗡𝗡𝗘𝗟 𝗔𝗗𝗗𝗘𝗗 〕━━┈⊷\n┃ ✅ {name} ᴀᴅᴅᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ!\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
    except:
        await update.message.reply_text("⚠️ ᴜꜱᴀɢᴇ:\n`/addchannel Name | @channelID | https://t.me/link`", parse_mode="Markdown")

async def delchannel_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    if not is_owner(update.effective_user.id): return
    if not context.args: return
    cid = context.args[0]
    db["settings"]["channels"] = [ch for ch in db["settings"]["channels"] if ch["id"] != cid]
    save_db()
    await update.message.reply_text(f"╭━━〔 𝗖𝗛𝗔𝗡𝗡𝗘𝗟 𝗥𝗘𝗠𝗢𝗩𝗘𝗗 〕━━┈⊷\n┃ 🗑️ ᴄʜᴀɴɴᴇʟ ʀᴇᴍᴏᴠᴇᴅ ꜰʀᴏᴍ ᴅᴀᴛᴀʙᴀꜱᴇ.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")

async def admin_panel(update: Update, context: CallbackContext):
    if not is_owner(update.effective_user.id): return
    await render_admin_menu(update.message.reply_text)

async def render_admin_menu(reply_func):
    target = db["settings"]["ref_target"]
    reward = db["settings"]["ref_reward_hours"]
    maint = "🔴 ᴏꜰꜰ" if not db["settings"]["maintenance"] else "🟢 ᴏɴ"
    
    total_users = len(db["all_users"])
    total_premium = len(db["premium"]) + len(db.get("temp_premium", {}))
    total_owners = len(db["owners"]) + len(db.get("temp_owners", {})) + 1 # +1 for Super Owner
    normal_users = total_users - total_premium
    
    allbots_line = "┃ • /allbots    ➡️ sʜᴏᴡ ᴀʟʟ ʙᴏᴛs\n" if not IS_CHILD_BOT else ""

    text = f"""╭━━〔 𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟 〕━━┈⊷
┃ 👑 ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ!
┃ 
┃ 📊 𝗔𝗡𝗔𝗟𝗬𝗧𝗜𝗖𝗦:
┃ • ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ: {total_users}
┃ • ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ: {total_premium}
┃ • ɴᴏʀᴍᴀʟ ᴜꜱᴇʀꜱ: {max(0, normal_users)}
┃ • ᴏᴡɴᴇʀꜱ/ᴀᴅᴍɪɴꜱ: {total_owners}
┃ • ʙᴀɴꜱ/ᴜɴʙᴀɴꜱ: {db["stats"]["total_bans"]}/{db["stats"]["total_unbans"]}
┃
┃ ⚙️ 𝗥𝗘𝗙𝗘𝗥𝗥𝗔𝗟 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦:
┃ • ᴛᴀʀɢᴇᴛ: {target} ɪɴᴠɪᴛᴇꜱ
┃ • ʀᴇᴡᴀʀᴅ: {reward} ʜᴏᴜʀ(ꜱ)
┃
┃ 🚀 𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗠𝗠𝗔𝗠𝗗𝗦:
┃ • /userinfo   ➡️ ᴜsᴇʀ ᴅᴇᴛᴀɪʟs 
┃ • /banuser    ➡️ ʙᴀɴ ᴜsᴇʀ
┃ • /unbanuser  ➡️ ᴜɴʙᴀɴ ᴜsᴇʀ 
┃ • /addprem    ➡️ ᴍᴀᴋᴇ ᴘʀᴇᴍᴜɪᴍ
┃ • /delprem     ➡️ ʀᴇᴍᴏᴠᴇ ᴘʀᴇᴍɪᴜᴍ
┃ • /channel     ➡️ ᴀᴅᴅ/ʀᴇᴍᴏᴠᴇ ᴄʜᴀɴɴᴇʟ
┃ • /antinum     ➡️ ᴀᴅᴅ ᴏᴡɴᴇʀ ɴᴜᴍʙᴇʀ
┃ • /genkey     ➡️ ɢᴇɴᴇʀᴀᴛᴇ ᴋᴇʏ
┃ • /payset     ➡️ ᴜᴘᴅᴀᴛᴇ ᴘᴀʏᴍᴇɴᴛ ᴍᴇᴛʜᴏᴅ
┃ • /broadcast ➡️ ᴍᴇssᴀɢᴇ ᴀʟʟ ᴜsᴇʀs
┃ • /setvideo ➡️ ᴠɪᴅᴇᴏ ʟɪɴᴋ ᴄʜᴀɴɢᴇ (ɢʀᴀɴᴅ ᴏᴡɴᴇʀ)
┃ • /addowner   ➡️ ᴀᴅᴅ ɴᴇᴡ ᴏᴡɴᴇʀ/ᴀᴅᴍɪɴ
┃ • /delowner   ➡️ ʀᴇᴍᴏᴠᴇ ᴏᴡɴᴇʀ/ᴀᴅᴍɪɴ
┃ • /cancel     ➡️ ᴄᴀɴᴄᴇʟ ᴀᴅᴍɪɴ ɪɴᴘᴜᴛ
{("┃ • /promot    ➡️ ᴘʀᴏᴍᴏᴛᴇ ᴄʜɪʟᴅ ʙᴏᴛ ᴜsᴇʀs\n" if not IS_CHILD_BOT else "")}
{allbots_line}┃
┃ 📢 𝗖𝗛𝗔𝗡𝗡𝗘𝗟𝗦: {len(db["settings"]["channels"])} ᴀᴄᴛɪᴠᴇ
╰━━━━━━━━━━━━━━━━━━━━━┈⊷"""
    
    kb = [
        [InlineKeyboardButton("➖", callback_data="adm_targ_down", style="primary"), InlineKeyboardButton(f"🎯 ᴛᴀʀɢᴇᴛ: {target}", callback_data="none", style="danger"), InlineKeyboardButton("➕", callback_data="adm_targ_up", style="primary")],
        [InlineKeyboardButton("➖", callback_data="adm_rew_down", style="primary"), InlineKeyboardButton(f"⏳ ʀᴇᴡᴀʀᴅ: {reward}ʜ", callback_data="none", style="danger"), InlineKeyboardButton("➕", callback_data="adm_rew_up", style="primary")],
        [InlineKeyboardButton("💾 ʙᴀᴄᴋᴜᴘ", callback_data="adm_backup", style="success"), InlineKeyboardButton("🔑 ɢᴇɴ 24ʜ ᴋᴇʏ", callback_data="adm_genkey", style="success")],
        [InlineKeyboardButton("📢 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧", callback_data="adm_broadcast", style="danger")], 
        [InlineKeyboardButton(f"🆓 ғʀᴇᴇ ʙᴏᴛ : {'🟢 ᴏɴ' if db['settings'].get('free_bot', False) else '🔴 ᴏғғ'}", callback_data="adm_freebot", style="danger")],
        [InlineKeyboardButton(f"🛠️ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ: {maint}", callback_data="adm_maint", style="danger")],
        [InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="adm_close", style="primary")]
    ]
    await reply_func(text, reply_markup=InlineKeyboardMarkup(kb))

async def broadcast_command(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not is_owner(uid):
        return
    replied = update.message.reply_to_message
    if replied:
        await _broadcast_source(context, update.effective_chat.id, replied.message_id, uid)
    else:
        broadcast_state[uid] = True
        await update.message.reply_text("Broadcast mode on hai. Ab koi bhi text, photo, video, sticker, document, voice ya doosra media bhejein; woh tamam users ko copy hoga. Band karne ke liye /cancel bhejein.")

async def _broadcast_source(context, from_chat_id, message_id, uid):
    users = list(dict.fromkeys(db.get("all_users", [])))
    status = await context.bot.send_message(uid, f"Broadcast {len(users)} users ko bheja ja raha hai...")
    success = failed = 0
    for user_id in users:
        try:
            await context.bot.copy_message(chat_id=int(user_id), from_chat_id=from_chat_id, message_id=message_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await status.edit_text(f"Broadcast mukammal. Kamyab: {success}; fail/blocked: {failed}.")

async def promot_command(update: Update, context: CallbackContext):
    if IS_CHILD_BOT or not is_super_owner(update.effective_user.id):
        return
    try:
        me = await context.bot.get_me()
        start_url = f"https://t.me/{me.username}?start=createownbot"
        users = set()
        for record in db.get("created_bots", []):
            if record.get("status") in ("deleted", "failed", "missing"):
                continue
            child_db = _child_bot_dir(record.get("id")) / "bot_data" / "database.json"
            try:
                child_data = json.loads(child_db.read_text(encoding="utf-8"))
                users.update(str(x) for x in child_data.get("all_users", []))
            except Exception:
                continue
            token = record.get("bot_token")
            if not token:
                continue
            child_bot = Bot(token)
            promo_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Create Your Own Ban Bot", url=start_url, style="success")]])
            for child_uid in child_data.get("all_users", []):
                try:
                    if Path("bot.png").exists():
                        with open("bot.png", "rb") as photo:
                            await child_bot.send_photo(chat_id=int(child_uid), photo=photo, caption="Make own ban bot in thirty seconds", reply_markup=promo_kb)
                    else:
                        await child_bot.send_message(chat_id=int(child_uid), text="Make own ban bot in thirty seconds", reply_markup=promo_kb)
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
        await update.message.reply_text(f"Promotion bhej di gayi. Child-bot users ka unique count: {len(users)}.")
    except Exception as exc:
        await update.message.reply_text(f"Promotion mein masla aya: {str(exc)[:250]}")

async def setvideo_command(update: Update, context: CallbackContext):
    if not is_super_owner(update.effective_user.id):
        return
    if context.args:
        url = " ".join(context.args).strip()
        if not url.startswith(("https://", "http://")):
            await update.message.reply_text("Valid http(s) video link bhejein.")
            return
        db.setdefault("settings", {})["create_video_url"] = url
        save_db()
        await update.message.reply_text("Create-own-bot video link update ho gaya.")
    else:
        video_link_state[update.effective_user.id] = True
        await update.message.reply_text("Naya video URL bhejein; cancel karne ke liye /cancel.")

async def cancel_command(update: Update, context: CallbackContext):
    if await maintenance_guard(update, context): return
    user_id = update.effective_user.id
    create_bot_state.pop(user_id, None)
    admin_bot_edit_state.pop(user_id, None)
    video_link_state.pop(user_id, None)

    if user_id == ADMIN_CHAT_ID and user_id in payset_state:
        db["settings"]["payment_method"] = payset_state.pop(user_id)
        save_db()
        await update.message.reply_text("❌ Payment method update cancelled. The previous payment method remains active.")
        return

    if broadcast_state.get(user_id):
        broadcast_state[user_id] = False
        await update.message.reply_text("❌ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ.")
    else:
        await update.message.reply_text("⚠️ ɴᴏᴛʜɪɴɢ ᴛᴏ ᴄᴀɴᴄᴇʟ.")

async def broadcast_message_handler(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    # Admin created-bot edit wizard
    if user_id in admin_bot_edit_state and is_owner(user_id) and update.message and update.message.text and not update.message.text.startswith("/cancel"):
        edit = admin_bot_edit_state[user_id]
        bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(edit["bot_id"])), None)
        if not bot:
            admin_bot_edit_state.pop(user_id, None); await update.message.reply_text("❌ Bot not found."); return
        field = edit["field"]; value = update.message.text.strip()
        try:
            if field == "name": bot["name"] = value[:64]
            elif field == "ban_name": bot["ban_name"] = _small_caps(value[:64] or bot.get("name", "BAN BOT"))
            elif field == "key_name": bot["key_name"] = _key_prefix(value)
            elif field == "add_admin":
                cid = int(value)
                admins = _child_admin_ids(bot)
                if cid not in admins: admins.append(cid)
                bot["admin_ids"] = admins
                bot["chat_ids"] = admins
                bot["chat_id"] = admins[0] if admins else cid
            elif field in ("chat", "add_chat", "replace_chat"):
                cid = int(value)
                ids = bot.setdefault("chat_ids", [bot.get("chat_id")])
                ids = [int(x) for x in ids if x is not None]
                if field == "chat":
                    bot["chat_id"] = cid
                    bot["chat_ids"] = [cid] + [x for x in ids[1:] if x != cid]
                    admins = _child_admin_ids(bot)
                    bot["admin_ids"] = [cid] + [x for x in admins[1:] if x != cid]
                elif field == "replace_chat":
                    if len(ids) > 1:
                        ids[1] = cid
                    else:
                        ids.append(cid)
                    bot["chat_ids"] = ids
                    admins = _child_admin_ids(bot)
                    if len(admins) > 1:
                        admins[1] = cid
                    elif admins:
                        admins.append(cid)
                    else:
                        admins = [cid]
                    bot["admin_ids"] = admins
                else:
                    if cid not in ids: ids.append(cid)
                    bot["chat_ids"] = ids
                    admins = _child_admin_ids(bot)
                    if cid not in admins: admins.append(cid)
                    bot["admin_ids"] = admins
            elif field == "channel":
                bot["channel_link"] = "" if value.upper() == "NONE" else (_normalize_link(value) or (_ for _ in ()).throw(ValueError()))
            elif field == "username":
                bot["username_link"] = "" if value.upper() == "NONE" else (_normalize_link(value) or (_ for _ in ()).throw(ValueError()))
            elif field == "token":
                me = await Bot(value).get_me()
                bot["bot_token"] = value; bot["bot_username"] = me.username
            else:
                raise ValueError("Unsupported field")
            admin_bot_edit_state.pop(user_id, None); save_db()
            await _restart_created_bot(bot["id"])
            await update.message.reply_text("✅ Updated and applied to the child bot.")
        except Exception:
            await update.message.reply_text("❌ Invalid value. Nothing was changed.")
        return

    # Create-own-bot wizard (main bot only)
    if not IS_CHILD_BOT and user_id in create_bot_state and update.message and update.message.text and not update.message.text.startswith("/cancel"):
        st = create_bot_state[user_id]
        if st["step"] == "token" and update.message.text:
            token = update.message.text.strip()
            try:
                me = await Bot(token).get_me()
                st["token"] = token
                st["step"] = "chat_id"
                st["bot_username"] = me.username
                await update.message.reply_text("╭━━〔 2️⃣ 𝗦𝗧𝗘𝗣 𝗧𝗪𝗢 〕━━┈⊷\n┃ 🆔 sᴇɴᴅ ᴍᴇ ʏᴏᴜʀ cʜᴀᴛ ɪᴅ.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
            except Exception:
                await update.message.reply_text("❌ Invalid bot token. Please send a valid BotFather token.")
            return
        if st["step"] == "chat_id" and update.message.text:
            try:
                st["chat_id"] = int(update.message.text.strip())
                st["step"] = "name"
                await update.message.reply_text("╭━━〔 3️⃣ 𝗦𝗧𝗘𝗣 𝗧𝗛𝗥𝗘𝗘 〕━━┈⊷\n┃ 🏷️ sᴇɴᴅ ᴍᴇ ʏᴏᴜʀ ʙᴏᴛ ɴᴀᴍᴇ.\n┃ ᴇxᴀᴍᴘʟᴇ : : 𝝙𝗟𝝞𝗪 𝘽𝘼𝙉 𝘽𝙊𝙏\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
            except ValueError:
                await update.message.reply_text("❌ Chat ID must be a number.")
            return
        if st["step"] == "name" and update.message.text:
            st["name"] = update.message.text.strip()[:64]
            st["step"] = "ban_name"
            await update.message.reply_text("╭━━〔 4️⃣ 𝗦𝗧𝗘𝗣 𝗙𝗢𝗨𝗥 〕━━┈⊷\n┃ ✏️ sᴇɴᴅ ᴛʜᴇ ɴᴀᴍᴇ ᴜsᴇᴅ ᴀғᴛᴇʀ ʙᴀɴ/ᴜɴʙᴀɴ ʙᴏɴᴇ.\n┃ ᴇxᴀᴍᴘʟᴇ : 𝝙𝗟𝝞𝗪 ʙᴀɴ ʙᴏᴛ\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
            return
        if st["step"] == "ban_name" and update.message.text:
            st["ban_name"] = _small_caps(update.message.text.strip()[:64] or st.get("name", "BAN BOT"))
            st["step"] = "key_name"
            await update.message.reply_text("╭━━〔 5️⃣ 𝗦𝗧𝗘𝗣 𝗙𝗜𝗩𝗘 〕━━┈⊷\n┃ 🔑 sᴇɴᴅ ʏᴏᴜʀ ᴋᴇʏ ɴᴀᴍᴇ.\n┃ ᴇxᴀᴍᴘʟᴇ : ALIWBANBOT\n┃ ᴛʜɪs ɴᴀᴍᴇ ᴡɪʟʟ ʀᴇᴘʟᴀᴄᴇ ᴛʜᴇ ᴋᴇʏ ᴘʀᴇғɪx.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
            return
        if st["step"] == "key_name" and update.message.text:
            st["key_name"] = _key_prefix(update.message.text)
            st["step"] = "image"
            await update.message.reply_text("╭━━〔 6️⃣ 𝗦𝗧𝗘𝗣 𝗦𝗜𝗫 〕━━┈⊷\n┃ 🖼️ sᴇɴᴅ ᴛʜᴇ ɪᴍᴀɢᴇ ғᴏʀ ʏᴏᴜʀ ʙᴏᴛ.\n┃ ᴛʜɪs ɪᴍᴀɢᴇ ᴡɪʟʟ ʀᴇᴘʟᴀᴄᴇ ᴛʜᴇ ᴅᴇғᴀᴜʟᴛ ʙᴏᴛ ɪᴍᴀɢᴇ.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
            return
        if st["step"] == "channel_link" and update.message.text:
            link = _normalize_link(update.message.text)
            if not link:
                await update.message.reply_text("❌ Please send a valid Telegram channel link.")
                return
            st["channel_link"] = link
            st["step"] = "username_link"
            await update.message.reply_text("╭━━〔 8️⃣ 𝗦𝗧𝗘𝗣 𝗘𝗜𝗚𝗛𝗧 〕━━┈⊷\n┃ 👤 sᴇɴᴅ ᴍᴇ ʏᴏᴜʀ ᴜsᴇʀɴᴀᴍᴇ ʟɪɴᴋ..\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
            return
        if st["step"] == "username_link" and update.message.text:
            link = _normalize_link(update.message.text)
            if not link:
                await update.message.reply_text("❌ Please send a valid Telegram username link.")
                return
            st["username_link"] = link
            await _finish_created_bot(user_id, update, context)
            return

    if user_id in channel_edit_state and is_owner(user_id) and update.message.text:
        edit = channel_edit_state.pop(user_id)
        index = edit["index"]
        channels = db["settings"].get("channels", [])
        if index < len(channels):
            value = update.message.text.strip()
            if edit["action"] == "rename":
                channels[index]["name"] = value
                result = "✅ ᴄʜᴀɴɴᴇʟ ʙᴜᴛᴛᴏɴ ɴᴀᴍᴇ ᴜᴘᴅᴀᴛᴇᴅ."
            else:
                channels[index]["url"] = value
                result = "✅ ᴄʜᴀɴɴᴇʟ ʟɪɴᴋ ᴜᴘᴅᴀᴛᴇᴅ."
            save_db()
            await update.message.reply_text(result)
            await render_channels(update.message.reply_text)
        return

    if user_id in video_link_state and is_super_owner(user_id) and update.message.text:
        url = update.message.text.strip()
        if not url.startswith(("https://", "http://")):
            await update.message.reply_text("Valid http(s) video link bhejein ya /cancel.")
            return
        db.setdefault("settings", {})["create_video_url"] = url
        video_link_state.pop(user_id, None)
        save_db()
        await update.message.reply_text("Create-own-bot video link update ho gaya.")
        return

    if user_id == ADMIN_CHAT_ID and user_id in payset_state:
        if update.message.text:
            db["settings"]["payment_method"] = update.message.text
            payset_state.pop(user_id)
            save_db()
            await update.message.reply_text("✅ Payment method updated successfully. It will now be shown by /buy.")
        return

    if broadcast_state.get(user_id):
        if update.message.text and update.message.text.startswith('/'):
            return
        broadcast_state[user_id] = False
        await _broadcast_source(context, update.effective_chat.id, update.message.message_id, user_id)

# ===== CALLBACKS =====
async def main_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    d = query.data
    uid = query.from_user.id
    
    if d == "createown_start" and not IS_CHILD_BOT:
        create_bot_state[uid] = {"step": "token"}
        await query.message.reply_text("BotFather se banaya hua bot token bhejein. Cancel ke liye /cancel bhejein.")
        await query.answer()
        return
    if d == "show_profile":
        if db["settings"]["maintenance"] and not is_owner(uid):
            await query.answer("🛠️ ʙᴏᴛ ɪꜱ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ.", show_alert=True)
            return
        await profile_command(update, context)
    elif d == "back_start":
        await start_command(update, context)
    elif d == "ch_add_info" and is_owner(uid):
        await query.answer()
        await query.message.reply_text("➕ Usage: `/addchannel Button Name | @channelID | https://t.me/channel`", parse_mode="Markdown")
        return
    elif d.startswith("ch_view_") and is_owner(uid):
        index = int(d.replace("ch_view_", ""))
        channels = db["settings"].get("channels", [])
        if index >= len(channels):
            await query.answer("Channel not found.", show_alert=True)
            return
        channel = channels[index]
        text = f"╭━━〔 𝗖𝗛𝗔𝗡𝗡𝗘𝗟 𝗗𝗘𝗧𝗔𝗜𝗟𝗦 〕━━┈⊷\n┃ 🔘 ɴᴀᴍᴇ: {channel['name']}\n┃ 🆔 ɪᴅ: {channel['id']}\n┃ 🔗 ʟɪɴᴋ: {channel['url']}\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷"
        kb = [
            [InlineKeyboardButton("✏️ 𝗥ᴇɴᴀᴍᴇ 𝗕ᴜᴛᴛᴏɴ", callback_data=f"ch_rename_{index}")],
            [InlineKeyboardButton("🔗 𝗖ʜᴀɴɢᴇ 𝗟ɪɴᴋ", callback_data=f"ch_link_{index}")],
            [InlineKeyboardButton("🗑️ 𝗗ᴇʟᴇᴛᴇ", callback_data=f"ch_delete_{index}", style="danger")],
            [InlineKeyboardButton("🔙 𝗕ᴀᴄᴋ", callback_data="ch_back")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
        await query.answer()
        return
    elif d in ("ch_rename_", "ch_link_") or d.startswith("ch_rename_") or d.startswith("ch_link_"):
        if not is_owner(uid): return
        action = "rename" if d.startswith("ch_rename_") else "link"
        index = int(d.rsplit("_", 1)[1])
        channel_edit_state[uid] = {"action": action, "index": index}
        prompt = "✏️ नया button name भेजें:" if action == "rename" else "🔗 नया channel link भेजें:"
        await query.answer()
        await query.message.reply_text(prompt)
        return
    elif d.startswith("ch_delete_") and is_owner(uid):
        index = int(d.replace("ch_delete_", ""))
        channels = db["settings"].get("channels", [])
        if index < len(channels):
            removed = channels.pop(index)
            save_db()
            await query.answer(f"Deleted: {removed['name']}", show_alert=True)
            await render_channels(query.message.edit_text)
        else:
            await query.answer("Channel not found.", show_alert=True)
        return
    elif d == "ch_back" and is_owner(uid):
        await render_channels(query.message.edit_text)
        await query.answer()
        return
    elif d == "verify_joined":
        joined, _ = await check_all_channels(uid, context)
        if joined:
            await query.answer("✅ ᴠᴇʀɪꜰɪᴇᴅ!", show_alert=True)
            await start_command(update, context) 
        else:
            await query.answer("❌ You haven't joined all channels yet!", show_alert=True)
            
    # Payment Approvals
    elif d.startswith("pay_app_") and is_owner(uid):
        target_id = d.replace("pay_app_", "")
        db.setdefault("temp_premium", {})[target_id] = time.time() + (30 * 86400) # Give 30 Days Standard
        save_db()
        await query.message.edit_caption(caption=query.message.caption + "\n\n✅ **APPROVED:** 30 Days Premium Granted.", parse_mode="Markdown")
        try: await context.bot.send_message(chat_id=target_id, text="🎉 **Payment Approved!**\nYour account has been upgraded to Premium for 30 Days.")
        except: pass
        
    elif d.startswith("pay_dec_") and is_owner(uid):
        target_id = d.replace("pay_dec_", "")
        await query.message.edit_caption(caption=query.message.caption + "\n\n❌ **DECLINED**", parse_mode="Markdown")
        try: await context.bot.send_message(chat_id=target_id, text="❌ **Payment Declined!**\nYour payment verification failed. Contact admin if you think this is a mistake.")
        except: pass

    elif d.startswith("anti_view_") and is_owner(uid):
        index = int(d.replace("anti_view_", ""))
        numbers = db.get("anti_numbers", [])
        if index >= len(numbers):
            await query.answer("Number not found.", show_alert=True)
            return
        number = numbers[index]
        kb = [
            [InlineKeyboardButton("🗑️ 𝗥𝗘𝗠𝗢𝗩𝗘 𝗡𝗨𝗠𝗕𝗘𝗥", callback_data=f"anti_remove_{index}", style="danger")],
            [InlineKeyboardButton("🔙 𝗕𝗔𝗖𝗞", callback_data="anti_back")]
        ]
        await query.message.edit_text(f"╭━━〔 𝗢𝗪𝗡𝗘𝗥 𝗡𝗨𝗠𝗕𝗘𝗥 〕━━┈⊷\n┃ 📞 `{number}`\n┃ ⚠️ ʀᴇᴍᴏᴠᴇ ᴛʜɪs ɴᴜᴍʙᴇʀ ғʀᴏᴍ ᴘʀᴏᴛᴇᴄᴛɪᴏɴ?\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        await query.answer()
        return
    elif d.startswith("anti_remove_") and is_owner(uid):
        index = int(d.replace("anti_remove_", ""))
        numbers = db.get("anti_numbers", [])
        if index >= len(numbers):
            await query.answer("Number not found.", show_alert=True)
            return
        removed = numbers.pop(index)
        save_db()
        await query.answer(f"Removed: {removed}", show_alert=True)
        await render_anti_numbers(query.message.edit_text)
        return
    elif d == "anti_back" and is_owner(uid):
        await render_anti_numbers(query.message.edit_text)
        await query.answer()
        return
    elif d.startswith("mybot_view_") and not IS_CHILD_BOT:
        bot_id = d.replace("mybot_view_", "")
        bot = next((b for b in db.get("created_bots", []) if b.get("id") == bot_id and b.get("creator_id") == uid and b.get("status") != "deleted"), None)
        if not bot:
            await query.answer("Bot not found.", show_alert=True); return
        if bot.get("status") == "running":
            kb = [[InlineKeyboardButton("⏹️ Stop Bot", callback_data=f"mybot_stop_{bot_id}", style="danger"),
                   InlineKeyboardButton("🗑️ Delete Now", callback_data=f"mybot_delete_{bot_id}", style="danger")]]
        else:
            kb = [[InlineKeyboardButton("▶️ Start Again", callback_data=f"mybot_start_{bot_id}", style="success"),
                   InlineKeyboardButton("🗑️ Delete Now", callback_data=f"mybot_delete_{bot_id}", style="danger")]]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="mybot_back", style="primary")])
        await query.message.edit_text(
            f"╭━━〔 🤖 𝗬𝗢𝗨𝗥 𝗕𝗢𝗧 〕━━┈⊷\n"
            f"┃ 🏷️ Name: {bot.get('name')}\n"
            f"┃ 🟢 Status: {bot.get('status','unknown')}\n"
            f"┃ 👤 Username: {bot.get('username_link')}\n"
            f"╰━━━━━━━━━━━━━━━━━━━━━┈⊷",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        await query.answer()
        return
    elif d.startswith("mybot_stop_") and not IS_CHILD_BOT:
        bot_id = d.replace("mybot_stop_", "")
        bot = next((b for b in db.get("created_bots", []) if b.get("id") == bot_id and b.get("creator_id") == uid and b.get("status") != "deleted"), None)
        if not bot:
            await query.answer("Bot not found.", show_alert=True); return
        await _stop_created_bot(bot_id)
        await query.answer("Bot stopped.", show_alert=True)
        bot = next((b for b in db.get("created_bots", []) if b.get("id") == bot_id), bot)
        kb = [[InlineKeyboardButton("▶️ Start Again", callback_data=f"mybot_start_{bot_id}", style="success"),
               InlineKeyboardButton("🗑️ Delete Now", callback_data=f"mybot_delete_{bot_id}", style="danger")],
              [InlineKeyboardButton("🔙 Back", callback_data="mybot_back", style="primary")]]
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return
    elif d.startswith("mybot_start_") and not IS_CHILD_BOT:
        bot_id = d.replace("mybot_start_", "")
        bot = next((b for b in db.get("created_bots", []) if b.get("id") == bot_id and b.get("creator_id") == uid and b.get("status") != "deleted"), None)
        if not bot:
            await query.answer("Bot not found.", show_alert=True); return
        await _start_created_bot(bot_id)
        await query.answer("Bot started again.", show_alert=True)
        kb = [[InlineKeyboardButton("⏹️ Stop Bot", callback_data=f"mybot_stop_{bot_id}", style="danger"),
               InlineKeyboardButton("🗑️ Delete Now", callback_data=f"mybot_delete_{bot_id}", style="danger")],
              [InlineKeyboardButton("🔙 Back", callback_data="mybot_back", style="primary")]]
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return
    elif d.startswith("mybot_delete_") and not IS_CHILD_BOT:
        bot_id = d.replace("mybot_delete_", "")
        bot = next((b for b in db.get("created_bots", []) if b.get("id") == bot_id and b.get("creator_id") == uid and b.get("status") != "deleted"), None)
        if not bot:
            await query.answer("Bot not found.", show_alert=True); return
        kb = [[InlineKeyboardButton("✅ Yes, Delete", callback_data=f"mybot_confirm_delete_{bot_id}", style="danger")],
              [InlineKeyboardButton("❌ Cancel", callback_data=f"mybot_view_{bot_id}", style="primary")]]
        await query.message.edit_text("⚠️ Are you sure you want to delete your bot?\n\nAfter deletion you can create a new one.", reply_markup=InlineKeyboardMarkup(kb))
        await query.answer()
        return
    elif d.startswith("mybot_confirm_delete_") and not IS_CHILD_BOT:
        bot_id = d.replace("mybot_confirm_delete_", "")
        bot = next((b for b in db.get("created_bots", []) if b.get("id") == bot_id and b.get("creator_id") == uid and b.get("status") != "deleted"), None)
        if not bot:
            await query.answer("Bot not found.", show_alert=True); return
        await _delete_created_bot(bot_id)
        await query.message.edit_text("╭━━〔 🗑️ 𝗕𝗢𝗧 𝗗𝗘𝗟𝗘𝗧𝗘𝗗 〕━━┈⊷\n┃ Your bot has been deleted successfully.\n┃ You can now use /createownbot again.\n╰━━━━━━━━━━━━━━━━━━━━━┈⊷")
        await query.answer("Bot deleted")
        return
    elif d == "mybot_back" and not IS_CHILD_BOT:
        await query.message.delete()
        await query.answer()
        return
    elif d.startswith("bot_view_") and is_owner(uid):
        bot_id = d.replace("bot_view_", "")
        bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(bot_id)), None)
        if not bot:
            await query.answer("Bot not found.", show_alert=True); return
        await query.message.edit_text(_bot_details_text(bot), reply_markup=InlineKeyboardMarkup(_bot_admin_keyboard(bot_id, bot.get("status", "unknown"))))
        await query.answer()
        return
    elif d == "allbots_back" and is_owner(uid):
        await query.message.delete(); await query.answer(); return
    elif d.startswith("bot_stop_") and is_owner(uid):
        bot_id = d.replace("bot_stop_", "")
        ok = await _stop_created_bot(bot_id)
        await query.answer("Bot stopped." if ok else "Bot not found.", show_alert=True)
        bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(bot_id)), None)
        if bot: await query.message.edit_text(_bot_details_text(bot), reply_markup=InlineKeyboardMarkup(_bot_admin_keyboard(bot_id, bot.get("status", "unknown"))))
        return
    elif d.startswith("bot_start_") and is_owner(uid):
        bot_id = d.replace("bot_start_", "")
        ok = await _start_created_bot(bot_id)
        await query.answer("Bot started." if ok else "Bot could not be started.", show_alert=True)
        bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(bot_id)), None)
        if bot: await query.message.edit_text(_bot_details_text(bot), reply_markup=InlineKeyboardMarkup(_bot_admin_keyboard(bot_id, bot.get("status", "unknown"))))
        return
    elif d.startswith("bot_delete_") and is_owner(uid):
        bot_id = d.replace("bot_delete_", "")
        bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(bot_id)), None)
        if not bot: await query.answer("Bot not found.", show_alert=True); return
        kb = [[InlineKeyboardButton("✅ Yes, Delete", callback_data=f"bot_confirm_delete_{bot_id}", style="danger")], [InlineKeyboardButton("❌ Cancel", callback_data=f"bot_view_{bot_id}")]]
        await query.message.edit_text("⚠️ Delete this created bot?\n\nThis will stop it and remove its child files.", reply_markup=InlineKeyboardMarkup(kb)); await query.answer(); return
    elif d.startswith("bot_confirm_delete_") and is_owner(uid):
        bot_id = d.replace("bot_confirm_delete_", "")
        ok = await _delete_created_bot(bot_id)
        await query.answer("Bot deleted." if ok else "Bot not found.", show_alert=True)
        await query.message.edit_text("🗑️ Bot deleted successfully.")
        return
    elif d.startswith("bot_edit_") or d.startswith("bot_add_chat_") or d.startswith("bot_replace_chat_") or d.startswith("bot_add_admin_") or d.startswith("bot_admins_"):
        if not is_owner(uid): return
        parts = d.split("_")
        bot_id = parts[-1]
        action = "_".join(parts[2:-1])
        bot = next((b for b in db.get("created_bots", []) if str(b.get("id")) == str(bot_id)), None)
        if not bot:
            await query.answer("Bot not found.", show_alert=True); return
        if d.startswith("bot_admins_"):
            admins = _child_admin_ids(bot)
            text = "👑 Current Admin IDs\n\n" + ("\n".join(f"• `{x}`" for x in admins) if admins else "No admin IDs set.")
            await query.answer(); await query.message.reply_text(text, parse_mode="Markdown"); return
        if d.startswith("bot_add_admin_"):
            admin_bot_edit_state[uid] = {"bot_id": bot_id, "field": "add_admin"}
            await query.answer(); await query.message.reply_text("👑 Send the Telegram Chat ID you want to make an admin of this bot.")
            return
        current_ids = bot.get("chat_ids") or [bot.get("chat_id")]
        prompts = {
            "name": f"✏️ Current name: {bot.get('name', 'Not set')}\n\nSend the new bot name.",
            "ban_name": f"🏷️ Current Ban/Unban name: {bot.get('ban_name', bot.get('name', 'Not set'))}\n\nSend the new name.",
            "key_name": f"🔑 Current Key Name: {bot.get('key_name', 'ALIWBANBOT')}\n\nSend the new Key Name.",
            "chat": f"🆔 Current primary Chat ID: {bot.get('chat_id', 'Not set')}\n\nSend the new primary Chat ID.",
            "add_admin": f"👑 Current Admin IDs: {', '.join(str(x) for x in _child_admin_ids(bot)) or 'None'}\n\nSend the Telegram Chat ID to add as admin.\n\n",
            "add_chat": f"➕ Current extra Chat IDs: {', '.join(str(x) for x in current_ids[1:]) if len(current_ids) > 1 else 'None'}\n\nSend the extra Chat ID to add.",
            "replace_chat": f"🔄 Current extra Chat ID: {current_ids[1] if len(current_ids) > 1 else 'None'}\n\nSend the new extra Chat ID to replace it.",
            "channel": f"📢 Current Force Join channel: {bot.get('channel_link') or 'Not set'}\n\nSend the new channel link, or type NONE to remove it.",
            "username": f"👤 Current username/profile link: {bot.get('username_link') or 'Not set'}\n\nSend the new Telegram username/profile link, or type NONE to remove it.",
            "token": f"🔑 Current Bot Token: {bot.get('bot_token') or 'Not set'}\n\nSend the new BotFather token.",
        }
        field = action
        if d.startswith("bot_add_chat_"): field = "add_chat"
        if d.startswith("bot_replace_chat_"): field = "replace_chat"
        if field == "logo":
            admin_bot_edit_state[uid] = {"bot_id": bot_id, "field": "logo"}
            await query.answer(); await query.message.reply_text("🖼️ Send the new bot logo/photo now."); return
        if field not in prompts: return
        admin_bot_edit_state[uid] = {"bot_id": bot_id, "field": field}
        await query.answer(); await query.message.reply_text(prompts[field]); return
    elif d.startswith("adm_") and is_owner(uid):
        s = db["settings"]
        if d == "adm_maint": s["maintenance"] = not s["maintenance"]
        elif d == "adm_targ_up": s["ref_target"] += 1
        elif d == "adm_targ_down": s["ref_target"] = max(1, s["ref_target"] - 1)
        elif d == "adm_rew_up": s["ref_reward_hours"] += 1
        elif d == "adm_rew_down": s["ref_reward_hours"] = max(1, s["ref_reward_hours"] - 1)
        elif d == "adm_freebot":
            s["free_bot"] = not s.get("free_bot", False)
            await query.answer(f"FREE BOT {'ON' if s['free_bot'] else 'OFF'}", show_alert=True)
        elif d == "adm_broadcast":
            broadcast_state[uid] = True
            await query.answer()
            await query.message.reply_text("📢 **𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗠𝗢𝗗𝗘 𝗔𝗖𝗧𝗜𝗩𝗔𝗧𝗘𝗗**\n\nSend the message (Text, Photo, Video) you want to broadcast to all bot users.\n\nSend `/cancel` to abort.", parse_mode="Markdown")
            return
        elif d == "adm_genkey":
            key = f"{_key_prefix(CHILD_KEY_NAME)}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
            db["redeem_keys"][key] = {"hours": 24, "used": False}
            await query.answer(f"🔑 ᴋᴇʏ: {key}\n(Copied to logs)", show_alert=True)
            await context.bot.send_message(uid, f"`{key}`", parse_mode="Markdown")
        elif d == "adm_backup":
            await query.message.reply_document(document=open(DB_FILE, 'rb'))
        elif d == "adm_close":
            await query.message.delete()
            return
        
        save_db()
        await render_admin_menu(query.message.edit_text)
    await query.answer()

async def restore_created_bots():
    """Restart all non-deleted child bots when the main bot starts again."""
    if IS_CHILD_BOT:
        return
    for bot in db.get("created_bots", []):
        if bot.get("status") in ("deleted", "stopped"):
            continue
        bot_id = str(bot.get("id"))
        bot_dir = _child_bot_dir(bot_id)
        if not bot_dir.exists() or not (bot_dir / "app.py").exists():
            bot["status"] = "missing"
            continue
        _sync_child_app(bot_id)
        env = os.environ.copy()
        env.update({
            "ALIW_CHILD_BOT": "1",
            "TELEGRAM_TOKEN": bot.get("bot_token", ""),
            "OWNER_ID": str(bot.get("chat_id", "")),
            "ADMIN_CHAT_ID": str(bot.get("chat_id", "")),
            "ADMIN_CHAT_IDS": ",".join(str(x) for x in (bot.get("admin_ids") or bot.get("chat_ids", [bot.get("chat_id", "")]))) ,
            "SUPER_OWNER_ID": str(bot.get("chat_id", "")),
            "OWNER_USERNAME": bot.get("username_link", ""),
            "BOT_DISPLAY_NAME": bot.get("name", "BAN BOT"),
            "CHILD_BAN_NAME": bot.get("ban_name", bot.get("name", "BAN BOT")),
            "CHILD_KEY_NAME": bot.get("key_name", "ALIWBANBOT"),
            "CHILD_CHANNEL_URL": bot.get("channel_link", ""),
            "CHILD_CHANNEL_ID": (bot.get("channel_link", "").split("/")[-1].split("?")[0] if bot.get("channel_link") else ""),
            "IMG_PATH": "start.jpg" if (bot_dir / "start.jpg").exists() else "start.png",
        })
        try:
            proc = await _launch_child_process(bot_id, bot_dir, env)
            bot["status"] = "running"
            bot["pid"] = proc.pid
        except Exception as e:
            bot["status"] = "failed"
            bot["error"] = str(e)[:200]
    save_db()

async def main():
    save_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    if not IS_CHILD_BOT:
        app.add_handler(CommandHandler("createownbot", createownbot_command))
        app.add_handler(CommandHandler("allbots", allbots_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    if not IS_CHILD_BOT:
        app.add_handler(CommandHandler("promot", promot_command))
        app.add_handler(CommandHandler("setvideo", setvideo_command))
    
    app.add_handler(CommandHandler("addchannel", addchannel_command))
    app.add_handler(CommandHandler("delchannel", delchannel_command))
    app.add_handler(CommandHandler("channel", channel_command))
    app.add_handler(CommandHandler("antinum", antinum_command))
    
    app.add_handler(CommandHandler("referral", referral_command))   
    app.add_handler(CommandHandler("redeem", redeem_command))       
    app.add_handler(CommandHandler("check", check_command))         
    
    # NEW USER COMMANDS
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("payset", payset_command))

    # VIP COMMANDS
    app.add_handler(CommandHandler("ban_perm", ban_perm_command))
    app.add_handler(CommandHandler("ban_temp", ban_temp_command))
    app.add_handler(CommandHandler("unban", unban_command))
    
    # NEW ADMIN/OWNER COMMANDS
    app.add_handler(CommandHandler("addprem", addprem_command))
    app.add_handler(CommandHandler("delprem", delprem_command))
    app.add_handler(CommandHandler("banuser", banuser_command))
    app.add_handler(CommandHandler("unbanuser", unbanuser_command))
    app.add_handler(CommandHandler("userinfo", userinfo_command))
    app.add_handler(CommandHandler("genkey", genkey_command))
    
    # SUPER OWNER COMMANDS
    app.add_handler(CommandHandler("addowner", addowner_command))
    app.add_handler(CommandHandler("delowner", delowner_command))
    
    app.add_handler(CommandHandler("cancel", cancel_command))

    # Process inline button updates before regular message handlers.
    app.add_handler(CallbackQueryHandler(main_callback), group=-1)
    
    # Handlers for text & photo (Broadcast & Payment Screenshot)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_message_handler))
    
    print("🤖 Bot Running With Enterprise UI, Dashboard & Enhanced Admin System...")
    await app.initialize()
    try:
        _main_username = (await app.bot.get_me()).username or ""
        if _main_username:
            os.environ["MAIN_BOT_USERNAME"] = _main_username
    except Exception:
        pass
    # Do not call set_my_name(): the official Telegram/BotFather name must remain unchanged.
    try:
        # Command menu is intentionally disabled for both the main bot and all child bots.
        # This removes the command list from Telegram's Menu button while keeping
        # the slash commands themselves fully functional when typed manually.
        from telegram import BotCommandScopeChat
        await app.bot.delete_my_commands()

        # Remove any previously-created per-admin command menu from the main bot too.
        # This prevents old /allbots or other admin commands from remaining visible.
        admin_ids = set([SUPER_OWNER_ID, OWNER_ID, *ADMIN_CHAT_IDS, *[int(x) for x in db.get("owners", []) if str(x).lstrip("-").isdigit()]])
        if not IS_CHILD_BOT:
            for admin_id in admin_ids:
                try:
                    await app.bot.delete_my_commands(
                        scope=BotCommandScopeChat(chat_id=admin_id)
                    )
                except Exception as e:
                    print(f"⚠️ Could not clear admin command menu for {admin_id}: {e}")
    except Exception as e:
        print(f"⚠️ Could not clear command menu: {e}")
    # This bot uses long polling. Telegram does not allow getUpdates while a
    # webhook is configured; remove it but keep any queued updates intact.
    await app.bot.delete_webhook(drop_pending_updates=False)
    await app.start()
    await restore_created_bots()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
