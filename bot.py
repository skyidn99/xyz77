import os
import logging
import json
import asyncio
import requests
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue

# --- Configuration & Logging (No changes) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
INDIWTF_TOKEN = os.getenv("INDIWTF_TOKEN")
INDIWTF_API_BASE_URL = "https://indiwtf.com/api"
DATA_FILE = Path("domains.json")
PERIODIC_CHECK_INTERVAL = 30 * 60

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Data, API, and Formatting Functions ---
def load_data() -> dict:
    if not DATA_FILE.exists(): return {"chat_id": None, "domains": []}
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            data.setdefault("chat_id", None); data.setdefault("domains", [])
            return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading data from {DATA_FILE}: {e}")
        return {"chat_id": None, "domains": []}

def save_data(data: dict):
    try:
        with open(DATA_FILE, "w") as f:
            unique_domains = sorted(list(set(data.get("domains", []))))
            data["domains"] = unique_domains
            json.dump(data, f, indent=2)
    except IOError as e: logger.error(f"Error saving data to {DATA_FILE}: {e}")

async def check_domain_status(domain: str) -> dict:
    if not INDIWTF_TOKEN: return {"error": "Indiwtf API token is not configured."}
    url = f"{INDIWTF_API_BASE_URL}/check?domain={domain}&token={INDIWTF_TOKEN}"
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: requests.get(url, timeout=10))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API check failed for {domain}: {e}")
        try: return response.json()
        except: return {"error": str(e)}

# --- PERUBAHAN 1: Menambahkan garis miring (/) di akhir domain ---
def format_status_message(result: dict, domain_to_check: str) -> str:
    """Formats the API result into a user-friendly string."""
    if "error" in result:
        return f"❌ **Error checking `{domain_to_check}`:**\n{result['error']}"
    
    status = result.get("status", "unknown").upper()
    ip = result.get("ip", "N/A")
    domain = result.get("domain", domain_to_check)
    emoji = "🔴" if status == "BLOCKED" else "✅"
    status_text = "is *BLOCKED*" if status == "BLOCKED" else "is *OK*"
    
    # Tambahkan "https://", domain, dan "/" di sini
    return f"{emoji} `https://{domain}/` {status_text} (IP: `{ip}`)"

def get_domains_from_message(text: str) -> list[str]:
    parts = text.split(maxsplit=1)
    if len(parts) < 2: return []
    raw_domains = parts[1].split()
    # Logika ini memastikan data yang disimpan selalu bersih (tanpa http dan /)
    cleaned_domains = [
        d.lower().replace("https://", "").replace("http://", "").strip("/")
        for d in raw_domains if d.strip()
    ]
    return cleaned_domains

# --- Job/Check Function (No changes needed here) ---
async def periodic_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The core function that checks all domains and sends a report."""
    logger.info("Running domain check...")
    data = load_data()
    chat_id, domains = data.get("chat_id"), data.get("domains", [])
    if not chat_id:
        logger.warning("Check triggered but no chat_id is configured. Use /start.")
        return
    if not domains:
        await context.bot.send_message(chat_id=chat_id, text="Watchlist is empty. Add domains with `/add`.")
        return

    report_lines = ["🔔 **Domain Status Report**\n"]
    for domain in domains:
        result = await check_domain_status(domain)
        # Fungsi format_status_message yang sudah diubah akan dipanggil di sini
        report_lines.append(format_status_message(result, domain))
        await asyncio.sleep(1) 
    await context.bot.send_message(chat_id=chat_id, text="\n".join(report_lines), parse_mode='Markdown')
    logger.info("Domain check finished and report sent.")


# --- Command Handlers ---

async def check_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔍 On-demand check initiated. I will now check all domains on the watchlist..."
    )
    await periodic_check(context)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    data["chat_id"] = update.effective_chat.id
    save_data(data)
    
    welcome_text = (
        "👋 **Hello, everyone! The Indiwtf Domain Checker is now active in this group.**\n\n"
        "I will send periodic domain reports to this chat. Any member can manage the watchlist.\n\n"
        "**Commands:**\n"
        "`/add domain1.com ...`\n"
        "Adds one or more domains to the watchlist.\n\n"
        "`/remove domain1.com ...`\n"
        "Removes one or more domains.\n\n"
        "`/list`\n"
        "Shows all watched domains.\n\n"
        "`/checknow`\n"
        "Triggers an immediate check of all domains on the watchlist.\n\n"
        "`/check domain.com`\n"
        "Performs a single, one-time check for a specific domain."
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    domains_to_process = get_domains_from_message(update.message.text)
    if not domains_to_process:
        await update.message.reply_text("Usage: `/add domain1.com ...`\nYou can also paste a list of domains on new lines after the command.")
        return
    data = load_data()
    current_domains = set(data.get("domains", []))
    domains_to_add = set(domains_to_process)
    newly_added = sorted(list(domains_to_add - current_domains))
    already_exist = sorted(list(domains_to_add & current_domains))
    response_parts = ["**📝 Bulk Add Report**\n"]
    if newly_added:
        data["domains"].extend(newly_added)
        save_data(data)
        response_parts.append(f"✅ Added *{len(newly_added)}* new domains.")
    if already_exist:
        response_parts.append(f"☑️ Skipped *{len(already_exist)}* domains (already on list).")
    await update.message.reply_text("\n".join(response_parts), parse_mode='Markdown')

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    domains_to_process = get_domains_from_message(update.message.text)
    if not domains_to_process:
        await update.message.reply_text("Usage: `/remove domain1.com ...`\nYou can also paste a list of domains on new lines after the command.")
        return
    data = load_data()
    current_domains = set(data.get("domains", []))
    domains_to_remove = set(domains_to_process)
    successfully_removed = sorted(list(domains_to_remove & current_domains))
    not_found = sorted(list(domains_to_remove - current_domains))
    response_parts = ["**🗑️ Bulk Remove Report**\n"]
    if successfully_removed:
        data["domains"] = [d for d in data["domains"] if d not in successfully_removed]
        save_data(data)
        response_parts.append(f"✅ Removed *{len(successfully_removed)}* domains.")
    if not_found:
        response_parts.append(f"❓ Could not remove *{len(not_found)}* domains (not on list).")
    await update.message.reply_text("\n".join(response_parts), parse_mode='Markdown')

# --- PERUBAHAN 2: Menambahkan garis miring (/) di akhir domain pada /list ---
async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    domains = load_data().get("domains", [])
    if not domains:
        await update.message.reply_text("The watchlist is empty. Use `/add domain.com`.")
        return
    # Tampilkan domain dengan https:// dan / agar konsisten
    message_domains = [f"- https://{d}/" for d in domains]
    message = "📋 **Current Watchlist:**\n```\n" + "\n".join(message_domains) + "\n```"
    await update.message.reply_text(message, parse_mode='Markdown')

# --- PERUBAHAN 3: Menambahkan garis miring (/) di akhir domain pada /check ---
async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    domains_to_check = get_domains_from_message(update.message.text)
    if not domains_to_check:
        await update.message.reply_text("Usage: `/check domain.com`")
        return
    domain_to_check = domains_to_check[0]
    # Ubah pesan "Checking" agar konsisten
    await update.message.reply_text(f"🔍 Checking `https://{domain_to_check}/`...", parse_mode='Markdown')
    result = await check_domain_status(domain_to_check)
    await update.message.reply_text(format_status_message(result, domain_to_check), parse_mode='Markdown')


def main() -> None:
    """Starts the bot."""
    if not TELEGRAM_TOKEN or not INDIWTF_TOKEN:
        logger.critical("Missing TELEGRAM_TOKEN or INDIWTF_TOKEN.")
        return
    
    job_queue = JobQueue()
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .job_queue(job_queue)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("checknow", check_now_command))
    
    application.job_queue.run_repeating(periodic_check, interval=PERIODIC_CHECK_INTERVAL, first=10)

    logger.info("Bot is starting up...")
    application.run_polling()

if __name__ == "__main__":
    main()
