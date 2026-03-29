# 🤖 Telegram Forwarder Bot

Telegram bot that forwards messages from source channels (or groups) to target channels based on precise keyword matching. 


You manage the bot entirely through its own Telegram chat interface. It allows you to create workspaces, link source channels, add keywords, and set target channels without ever needing to touch a database.

## 🧩 Project Structure

```text
repost-bot/
├── admin_bot.py        # Main bot logic and UI
├── database.py         # SQLite database handler
├── requirements.txt
├── .env
└── processed.db        # SQLite database (created automatically)
```

## ⚙️ Setup

1️⃣ **Create a `.env` file in the root of the project:**

Copy the provided `.env.example` to `.env` and fill in the values:

```env


# --- ADMIN BOT CONFIG ---
# Bot token created via @BotFather
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11

# Path to the database file (created automatically if not present)
DB_PATH=processed.db
```

⚠️ **Do not publish your `.env` file!** It contains sensitive tokens.

## 🚀 How to Run

### Running Natively
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the bot:
   ```bash
python admin_bot.py 
   ```


## 💬 Commands

The bot is fully controlled via Telegram messaging. Once your bot is running, open a chat with it and use:

- `/start` — Register yourself and open the main menu to manage workspaces.

Using the intuitive inline button menus, you can:
- **Create workspaces:** Logical groupings of sources and targets.
- **Add Sources:** Link channels or groups where the bot will listen for new posts.
- **Add Keywords:** Set the keywords that determine whether a message is forwarded.
- **Set Target Channel:** Define where matched messages should be forwarded.

## 💡 How it Works & Permissions

1. **Add the Bot to Sources:** For the bot to read messages, it must be added to your source channels or groups.
2. **Add the Bot to Targets:** The bot must be an administrator in the target channels with the "Post Messages" permission.
3. Every time a new message appears in a linked source, the bot text is checked against the keywords.
4. If a keyword matches, the bot immediately copies or forwards the message to the configured target channel.
5. Messages are recorded in the `processed.db` SQLite database so they are never forwarded twice.

## ❓Useful Tips

- **Source Limitations:** By default, you're limited to 3 workspaces, 10 sources per workspace, and 20 keywords per workspace. This ensures the bot stays performant. 
- **Security:** Ensure `processed.db` and `.env` have restrictive permissions on your deployment server (`chmod 600`).
