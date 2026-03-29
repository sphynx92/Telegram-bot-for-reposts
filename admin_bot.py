#=========admin_bot.py==============

#!/usr/bin/env python3

import os
import logging
import asyncio
import re
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram import error, constants
import html
from telegram.helpers import escape_markdown

import database as db

#----------------- config -----------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ----------------- logging -----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("admin_bot")

# Helper for safe text
def safe_text(text):
    return html.escape(text) if text else ""

# ----------------- UI -----------------
def build_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Create workspace", callback_data="create_ws")],
        [InlineKeyboardButton("📂 My workspaces", callback_data="my_ws")],
        [InlineKeyboardButton("🆘 Support", url="https://t.me/ #your username")]
    ])

def build_workspaces_list(workspaces):
    keyboard = []

    for ws in workspaces:
        keyboard.append([
            InlineKeyboardButton(
                f"📁 {ws['name']} (#{ws['id']})",
                callback_data=f"open_ws:{ws['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")
    ])

    return InlineKeyboardMarkup(keyboard)

def build_workspace_menu(workspace):
    wid = workspace["id"]
    paused = bool(workspace["paused"])

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Sources", callback_data=f"sources:{wid}")],
        [InlineKeyboardButton("🔑 Keywords", callback_data=f"keywords:{wid}")],
        [InlineKeyboardButton("🎯 Target channel", callback_data=f"set_target:{wid}")],
        [InlineKeyboardButton(
            "▶️ Resume" if paused else "⏸ Pause",
            callback_data=f"resume_ws:{wid}" if paused else f"pause_ws:{wid}")
        ],
        [InlineKeyboardButton("❌ Delete workspace", callback_data=f"delete_ws:{wid}")],
        [InlineKeyboardButton( "❌ Delete target channel",callback_data=f"remove_target:{workspace['id']}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="my_ws")]
    ])


def extract_username(text: str) -> str:
    ### Extracts username from text, supporting formats:
    ## - @username
   ## - username
   ## - https://t.me/username
   ## - t.me/username
   ## Returns None if invalid.
    
    text = text.strip()
    
    # Try simpler cases first
    if text.startswith("@"):
        return text.lstrip("@")
    
    # Regex for t.me links
    # Matches: t.me/USERNAME or telegram.me/USERNAME
    match = re.search(r"(?:t(?:elegram)?\.me|telegram\.org)/(?P<username>[a-zA-Z0-9_]{5,32})", text)
    if match:
        return match.group("username")

    # Fallback: assume it's a bare username if no spaces/slashes
    if re.match(r"^[a-zA-Z0-9_]{5,32}$", text):
        return text

    return None

# ----------------- handlers -----------------
#start

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # user registration

    if not await db.user_exists(user_id):
        await db.create_user(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name
        )
    workspaces = await db.get_user_workspaces(user_id)

    if workspaces:
        text = "👋 Welcome back!\n\nChoose an action:"
    else:
        text = (
            "👋 Welcome!\n\n"
            "I will help you set up keyword-based reposts to your target channel.\n"
            "Let's start by creating a workspace 👇"
    )
    await update.message.reply_text(
        text, 
        reply_markup=build_main_menu())



#-------------callbacks--------------  

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not query.message:
        return

    user_id = update.effective_user.id

#workspaces 

    if query.data == "my_ws":
        context.user_data.pop("pending", None)

        workspaces = await db.get_user_workspaces(user_id)

        if not workspaces:
            await query.message.edit_text(
                "📂 You don't have workspaces yet.\n\nCreate the first one 👇",
                reply_markup=build_main_menu()
            )
            return

        await query.message.edit_text(
            "📂 Your workspaces:",
            reply_markup=build_workspaces_list(workspaces)
        )
        return

#create workspace
    
    if query.data == "create_ws":
        context.user_data.pop("pending", None)

        if not await db.can_create_workspace(user_id):
            await query.message.edit_text(
                "❌ Workspaces limit reached (max 3).\n"
                "Delete an old workspace to create a new one.",
                reply_markup=build_main_menu()
            )
            return

        context.user_data["pending"] = {
            "action": "create_ws"
        }

        await query.message.edit_text(
            "➕ Create workspace\n\n"
            "Enter the name for your workspace:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]
            ])
        )
        return


#open workspace 

    if query.data.startswith("open_ws:"):
        context.user_data.pop("pending", None)

        wid = int(query.data.split(":")[1])

        workspace = await db.get_workspace(wid)
        if not workspace:
            await query.message.edit_text(
            "❌ Workspace not found",
            reply_markup=build_main_menu()
        )
            return

#access: owner only
 
        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have access to this workspace")
            return

        await query.message.edit_text(
            f"📂 Workspace: <b>{safe_text(workspace['name'])}</b>",
            reply_markup=build_workspace_menu(workspace),
            parse_mode=constants.ParseMode.HTML
        )
        return

#Sources

    # -------- sources --------
    if query.data.startswith("sources:"):
        context.user_data.pop("pending", None)

        wid = int(query.data.split(":")[1])
        workspace = await db.get_workspace(wid)

        if not workspace or workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        sources = await db.get_sources(wid)

# ---- TEXT ----

        text = "📡 Sources:\n\n"
        text += "\n".join(f"• @{s}" for s in sources) if sources else "No sources yet."

        buttons = [
            [InlineKeyboardButton(f"❌ @{s}", callback_data=f"remove_source:{wid}:{s}")]
            for s in sources
        ]

        buttons.append([InlineKeyboardButton("➕ Add source", callback_data=f"add_source:{wid}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"open_ws:{wid}")])

        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

#add source  

    if query.data.startswith("add_source:"):

        wid = int(query.data.split(":")[1])

        workspace = await db.get_workspace(wid)
        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        if not await db.can_add_source(wid):
            await query.message.edit_text(
                "❌ Sources limit reached (max 10)",
                reply_markup=build_workspace_menu(workspace)
            )
            return


        context.user_data["pending"] = {
        "action": "add_source",
        "wid": wid
        }

        await query.message.edit_text(
        f"➕ Add source\n\n"
        f"Workspace: <b>{safe_text(workspace['name'])}</b>\n\n"
        f"Send the @username of the channel or group:",
        parse_mode=constants.ParseMode.HTML
        )

        buttons = [
            [InlineKeyboardButton(f"❌ @{s}", callback_data=f"remove_source:{wid}:{s}")]
            for s in sources
        ]

        buttons.append([InlineKeyboardButton("➕ Add source", callback_data=f"add_source:{wid}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"open_ws:{wid}")])

        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return
        

#remove source  

    if query.data.startswith("remove_source:"):
        context.user_data.pop("pending", None)

        _, wid, source = query.data.split(":", 2)
        wid = int(wid)

        workspace = await db.get_workspace(wid)
        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        await db.remove_source(wid, source)

        sources = await db.get_sources(wid)

        text = "🔑 Sources:\n\n"
        if sources:
            text += "\n".join(f"• @{s}" for s in sources) 
        else:
            text += "No sources yet."

        buttons = []
        for s in sources:
            buttons.append([
                InlineKeyboardButton(
                    f"❌ @{s}",
                    callback_data=f"remove_source:{wid}:{s}"
                )
            ])

        buttons.append([
            InlineKeyboardButton("➕ Add source", callback_data=f"add_source:{wid}")
        ])
        buttons.append([
            InlineKeyboardButton("⬅️ Back", callback_data=f"open_ws:{wid}")
        ])

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

   
#keywords

    if query.data.startswith("keywords:"):
        context.user_data.pop("pending", None)

        wid = int(query.data.split(":")[1])
        workspace = await db.get_workspace(wid)

        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return
        keywords = await db.get_keywords(wid)

# ---- TEXT ----

        text = "🔑 Keywords:\n\n"
        if keywords:
            text += "\n".join(f"• {k}" for k in keywords)   
        else:
            text += "No keywords yet."

# ---- BUTTONS ----
        buttons = []

        for k in keywords:
            buttons.append([InlineKeyboardButton(f"❌ {k}",callback_data=f"remove_keyword:{wid}:{k}")])      

        buttons.append([InlineKeyboardButton("➕ Add keyword", callback_data=f"add_keyword:{wid}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"open_ws:{wid}")])
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons))
                
        return

#add keyword

    if query.data.startswith("add_keyword:"):

        wid = int(query.data.split(":")[1])

        workspace = await db.get_workspace(wid)
        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        context.user_data["pending"] = {
            "action": "add_keyword",
            "wid": wid
        }

        await query.message.edit_text(
            "🔑 Enter a keyword (as a single message):",

        )
        buttons = [] 

        buttons.append([InlineKeyboardButton("➕ Add keyword", callback_data=f"add_keyword:{wid}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"open_ws:{wid}")])
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons))
                
        return
        
    
#remove keyword
    if query.data.startswith("remove_keyword:"):
        context.user_data.pop("pending", None)

        _, wid, keyword = query.data.split(":", 2)
        wid = int(wid)

        workspace = await db.get_workspace(wid)
        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        await db.remove_keyword(wid, keyword)

        keywords = await db.get_keywords(wid)

        text = "🔑 Keywords:\n\n"
        if keywords:
            text += "\n".join(f"• {k}" for k in keywords) 
        else:
            text += "No keywords yet."

        buttons = []
        for k in keywords:
            buttons.append([
                InlineKeyboardButton(
                    f"❌ {k}",
                    callback_data=f"remove_keyword:{wid}:{k}"
                )
            ])

        buttons.append([
            InlineKeyboardButton("➕ Add keyword", callback_data=f"add_keyword:{wid}")
        ])
        buttons.append([
            InlineKeyboardButton("⬅️ Back", callback_data=f"open_ws:{wid}")
        ])

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return
    
    
#target channel
  
    if query.data.startswith("set_target:"):

        wid = int(query.data.split(":")[1])
        workspace = await db.get_workspace(wid)

        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        current = workspace["target_channel"]
        text = (
            "🎯 Target channel\n\n"
            f"Current: {current or 'not set'}\n\n"
            "Send the @username of the channel where the bot will forward messages:"
        )

        context.user_data["pending"] = {
            "action": "set_target",
            "wid": wid
        }

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data=f"open_ws:{wid}")]
            ])
        )
        return
    
    #remove target channel 

    if query.data.startswith("remove_target:"):
        context.user_data.pop("pending", None)

        wid = int(query.data.split(":")[1])

        workspace = await db.get_workspace(wid)
        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        await db.remove_target(wid)

        await query.message.edit_text(
            "✅ Target channel removed",
            reply_markup=build_workspace_menu(workspace)
        )
        return


        #pause 
    
    if query.data.startswith("pause_ws:") or query.data.startswith("resume_ws:"):
        context.user_data.pop("pending", None)

        action, wid = query.data.split(":")
        wid = int(wid)

        workspace = await db.get_workspace(wid)
        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        paused = (action == "pause_ws")
        await db.set_workspace_paused(wid, paused)

        workspace = await db.get_workspace(wid)  # update state

        await query.message.edit_text(
            f"📂 Workspace: <b>{safe_text(workspace['name'])}</b>",
            reply_markup=build_workspace_menu(workspace),
            parse_mode=constants.ParseMode.HTML
        )
        return
    

    #delete workspace
    if query.data.startswith("delete_ws:"):
        context.user_data.pop("pending", None)

        wid = int(query.data.split(":")[1])

        workspace = await db.get_workspace(wid)
        if not workspace:
            await query.message.edit_text("❌ Workspace not found")
            return

        if workspace["owner_id"] != user_id:
            await query.message.edit_text("❌ You don't have permission")
            return

        context.user_data["pending"] = {
            "action": "delete_ws",
            "wid": wid
        }

        await query.message.edit_text(
            f"⚠️ Delete workspace\n\n"
            f"Name: <b>{safe_text(workspace['name'])}</b>\n\n"
            f"❗ This action is irreversible.\n\n"
            f"Send the word <b>delete</b> to confirm.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Cancel", callback_data=f"open_ws:{wid}")]
            ]),
            parse_mode=constants.ParseMode.HTML
    )   
        return
    

    #back to main menu 
    
    if query.data == "back_to_main":
        context.user_data.pop("pending", None)

        await query.message.edit_text(
        "Main menu",
        reply_markup=build_main_menu()
    )
        return

    # fallback
    logger.warning(f"Unknown callback: {query.data}")

# ----------------- forwarding handler -----------------

async def forward_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ## Handles new messages in channels/groups, checks against workspaces/keywords, and forwards to target channels if matched.
    
    # 1. Inspect the message
    msg = update.effective_message
    if not msg:
        return

    chat = update.effective_chat
    # Source identifier: username (without @) or string ID if private
    chat_identifier = (chat.username or str(chat.id)).lstrip("@")
    
    # 2. Find matching workspaces
    workspaces = await db.get_workspaces_by_source(chat_identifier)
    if not workspaces:
        return

    # Text content (text or caption)
    text = (msg.text or msg.caption or "").lower().strip()

    # 3. Process each workspace
    for w in workspaces:
        w_id = w["id"]
        w_name = w["name"]
        w_target = w["target_channel"]
        paused = bool(w["paused"])

        if paused:
            continue

        # Prevent duplicate processing
        if await db.is_processed(chat.id, msg.message_id, w_id):
            continue

        if not w_target:
            logger.debug("Workspace '%s' skipped (no target)", w_name)
            continue

        # Check keywords
        keywords = await db.get_keywords(w_id)
        if keywords:
            # If keywords are defined, at least one must be present
            if not any(k in text for k in keywords):
                continue
     
            
        if not keywords:
             continue

        # 4. Forward
        try:
        
            await context.bot.forward_message(
                chat_id=f"@{w_target}" if not w_target.startswith("-") and not w_target.startswith("@") else w_target,
                from_chat_id=chat.id,
                message_id=msg.message_id
            )
            # Mark processed
            await db.mark_processed(chat.id, msg.message_id, w_id)
            logger.info(f"Forwarded msg {msg.message_id} from {chat_identifier} to {w_target} (WS: {w_name})")

        except error.BadRequest as e:
            logger.error(f"Failed to forward to {w_target}: {e}")
        except error.Forbidden:
            logger.error(f"Bot has no rights to send to {w_target}")
        except Exception as e:
            logger.exception(f"Error forwarding: {e}")


#-------------------pending text-------------

async def pending_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = context.user_data.get("pending")
    if not pending:
        return
    if not update.message:
        return


    user_id = update.effective_user.id
    text = update.message.text.strip()

#create workspace

    if pending["action"] == "create_ws":
        name = text.strip()

        if not name:
            await update.message.reply_text("❌ Name cannot be empty")
            return

        if len(name) > 64:
            await update.message.reply_text("❌ Name is too long")
            return

        if not await db.can_create_workspace(user_id):
            await update.message.reply_text(
                "❌ Workspaces limit reached (max 3)"
            )
            context.user_data.pop("pending", None)
            return

        wid = await db.create_workspace(name, user_id)

        context.user_data.pop("pending", None)

        await update.message.reply_text(
            f"✅ Workspace \"<b>{safe_text(name)}</b>\" created",
            reply_markup=build_main_menu(),
            parse_mode=constants.ParseMode.HTML
        )
        return


#add source 

    if pending["action"] == "add_source":
        wid = pending["wid"]

        workspace = await db.get_workspace(wid)
        if not workspace:
            await update.message.reply_text("❌ Workspace not found")
            context.user_data.pop("pending", None)
            return

        if workspace["owner_id"] != user_id:
            await update.message.reply_text("❌ You don't have permission")
            context.user_data.pop("pending", None)
            return
        
        if not await db.can_add_source(wid):
            await update.message.reply_text(
                "❌ Sources limit reached (max 10)"
            )
            context.user_data.pop("pending", None)
            return


        source_input = text.strip()
        source = extract_username(source_input)

        if not source:
            await update.message.reply_text(
                "❌ Invalid source format.\n"
                "Send @username or a link (t.me/username)."
            )
            return
        
        # Check source length again just in case, though extract_username limits it
        if len(source) > 64:
            await update.message.reply_text("❌ Name is too long")
            return
        if any(c in source for c in ["\n", "\t", " "]):
            await update.message.reply_text("❌ Invalid format")
            return

        workspace = await db.get_workspace(wid)

        ok = await db.add_source(wid, source)
        if not ok:
             await update.message.reply_text("❌ This source is already added")
             return

        await update.message.reply_text(
            f"✅ Source @{safe_text(source)} added",
            reply_markup=build_workspace_menu(workspace),
            parse_mode=constants.ParseMode.HTML
        )

        context.user_data.pop("pending", None)
        return

#add keyword 

    if pending["action"] == "add_keyword":
        wid = pending["wid"]

        workspace = await db.get_workspace(wid)
        if not workspace:
            await update.message.reply_text("❌ Workspace not found")
            context.user_data.pop("pending", None)
            return

        if workspace["owner_id"] != user_id:
            await update.message.reply_text("❌ You don't have permission")
            context.user_data.pop("pending", None)
            return
        
        if not await db.can_add_keyword(wid):
            await update.message.reply_text(
                "❌ Keywords limit reached (max 20)"
            )
            context.user_data.pop("pending", None)
            return


        keyword = text.lower().strip()
        if not keyword:
            await update.message.reply_text("❌ Keyword cannot be empty")
            return
        
        if len(keyword) > 64:
            await update.message.reply_text("❌ Keyword is too long")
            return
        if any(c in keyword for c in ["\n", "\t", " "]):
            await update.message.reply_text("❌ Invalid format")
            return

        ok = await db.add_keyword(wid, keyword)
        if not ok:
            await update.message.reply_text("❌ This keyword already exists")
            context.user_data.pop("pending", None)
            return


        await update.message.reply_text(
            f"✅ Keyword \"<b>{safe_text(keyword)}</b>\" added",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 To keywords", callback_data=f"keywords:{wid}")],
                [InlineKeyboardButton("⬅️ Back to workspace", callback_data=f"open_ws:{wid}")]
            ]),
            parse_mode=constants.ParseMode.HTML

        )

        context.user_data.pop("pending", None)
        return

#set target channel 

    if pending["action"] == "set_target":
        wid = pending["wid"]

        workspace = await db.get_workspace(wid)
        if not workspace:
            await update.message.reply_text("❌ Workspace not found")
            context.user_data.pop("pending", None)
            return

        if workspace["owner_id"] != user_id:
            await update.message.reply_text("❌ You don't have permission")
            context.user_data.pop("pending", None)
            return

        target_input = text.strip()
        target = extract_username(target_input)

        if not target:
            await update.message.reply_text(
                "❌ Invalid channel format.\n"
                "Send @username or a link (t.me/username)."
            )
            return
        
        if len(target) > 64:
            await update.message.reply_text("❌ Name is too long")
            return
        if any(c in target for c in ["\n", "\t", " "]):
            await update.message.reply_text("❌ Invalid format")
            return
        
        workspace = await db.get_workspace(wid)
        await db.set_target_channel(wid, target)

        await update.message.reply_text(
            f"✅ Target channel set: @{safe_text(target)}",
            reply_markup=build_workspace_menu(workspace),
            parse_mode=constants.ParseMode.HTML
        )

        context.user_data.pop("pending", None)
        return

#delete workspace 
  
    if pending["action"] == "delete_ws":
        wid = pending["wid"]

        workspace = await db.get_workspace(wid)
        if not workspace:
            await update.message.reply_text("❌ Workspace is already deleted")
            context.user_data.pop("pending", None)
            return

        if workspace["owner_id"] != user_id:
            await update.message.reply_text("❌ You don't have permission")
            context.user_data.pop("pending", None)
            return

        if text.lower() != "delete":
            await update.message.reply_text("❌ Deletion cancelled")
            context.user_data.pop("pending", None)
            return

        await db.delete_workspace(wid)

        context.user_data.pop("pending", None)

        await update.message.reply_text(
            "✅ Workspace deleted",
            reply_markup=build_main_menu()
        )
        return



# ----------------- main -----------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Handler for channel posts 

    app.add_handler(MessageHandler(
        filters.ChatType.CHANNEL | filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP, 
        forward_post_handler
    ))

    # Text handler for user settings (private chats)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, pending_text_handler))


    logger.info("Admin bot started")
    app.run_polling()

async def on_startup(app):
    await db.init_db()

if __name__ == "__main__":
    main()
