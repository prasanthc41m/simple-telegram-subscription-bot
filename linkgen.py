import logging
import json
import time
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import TelegramError
from config import BOT_TOKEN_B, DEBUG_CHAT_ID, ADMIN_USER_IDS, GROUP_CHAT_ID, LINK_EXPIRE_HOURS, LINK_MEMBER_LIMIT
import os

# Set environment variable to reduce HTTP logging
os.environ["HTTPX_LOG_LEVEL"] = "warning"

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress verbose HTTP loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class TelegramGroupManagerBot:

    def __init__(self):
        self.data_file = 'invite_links.json'
        self.link_data = self.load_data()
        self.pending_confirmations = {}  # Store user IDs waiting for confirmation
        self.pending_revokes = {}  # Store user IDs waiting for link input

    def load_data(self):
        """Load invite link data from JSON file"""
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("No existing data file found, starting fresh")
            return {}

    def save_data(self):
        """Save invite link data to JSON file"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.link_data, f, indent=2, ensure_ascii=False)
            logger.info("Data saved successfully")
        except Exception as e:
            logger.error("Error saving data: %s", e)

    def is_admin(self, user_id):
        """Check if user is an admin"""
        return str(user_id) in ADMIN_USER_IDS

    async def generate_invite_link(self, update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
        """Generate a one-time use invite link"""
        try:
            # Check if user is admin
            if not self.is_admin(update.effective_user.id):
                await update.message.reply_text(
                    "❌ Only admin can use this command")
                return

            # Create one-time invite link
            expire_date = int(time.time()) + (LINK_EXPIRE_HOURS * 3600)
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=GROUP_CHAT_ID,
                member_limit=LINK_MEMBER_LIMIT,
                expire_date=expire_date,
                name=f"one-time-{datetime.now().strftime('%Y%m%d-%H%M%S')}")

            # Store link information
            link_info = {
                "created_at": datetime.now().isoformat(),
                "created_by": update.effective_user.id,
                "expires_at": expire_date,
                "uses": 0,
                "max_uses": LINK_MEMBER_LIMIT
            }

            self.link_data[invite_link.invite_link] = link_info
            self.save_data()

            # Send the link to the user
            await update.message.reply_text(
                f"🔗 One-time invite link generated:\n\n"
                f"{invite_link.invite_link}\n\n"
                f"• Expires in: {LINK_EXPIRE_HOURS} hours\n"
                f"• Can be used by: {LINK_MEMBER_LIMIT} user(s)\n")

            logger.info("Generated one-time link: %s", invite_link.invite_link)

        except Exception as e:
            logger.error("Error generating invite link: %s", e)
            await update.message.reply_text("❌ Error generating invite link")

    async def clean_system_messages(self, update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
        """Delete system messages (user joins/leaves, etc.)"""
        try:
            # Check if the message is a system message
            if (update.message.new_chat_members
                    or update.message.left_chat_member
                    or update.message.group_chat_created
                    or update.message.migrate_to_chat_id
                    or update.message.migrate_from_chat_id
                    or update.message.pinned_message
                    or update.message.delete_chat_photo
                    or update.message.new_chat_title
                    or update.message.new_chat_photo):

                await update.message.delete()
                logger.info("Deleted system message in chat %s",
                            update.effective_chat.id)

        except Exception as e:
            logger.error("Error deleting system message: %s", e)

    async def delete_command_messages(self, update: Update,
                                      context: ContextTypes.DEFAULT_TYPE):
        """Delete messages that start with a slash (command messages)"""
        try:
            # Check if the message starts with a slash and is not from an admin
            if (update.message.text and update.message.text.startswith('/')
                    and not self.is_admin(update.effective_user.id)):

                await update.message.delete()
                logger.info("Deleted command message from user %s: %s",
                            update.effective_user.id, update.message.text)

        except Exception as e:
            logger.error("Error deleting command message: %s", e)

    async def list_links(self, update: Update,
                         context: ContextTypes.DEFAULT_TYPE):
        """List all active invite links"""
        try:
            if not self.is_admin(update.effective_user.id):
                await update.message.reply_text(
                    "❌ Only admin can use this command")
                return

            active_links = []
            current_time = time.time()

            for link, info in self.link_data.items():
                if info['expires_at'] > current_time and info['uses'] < info[
                        'max_uses']:
                    active_links.append(
                        f"• {link}\n  Uses: {info['uses']}/{info['max_uses']}\n  Expires: {datetime.fromtimestamp(info['expires_at']).strftime('%Y-%m-%d %H:%M')}"
                    )

            if active_links:
                await update.message.reply_text("🔗 Active Invite Links:\n\n" +
                                                "\n\n".join(active_links))
            else:
                await update.message.reply_text("No active invite links found."
                                                )

        except Exception as e:
            logger.error("Error listing links: %s", e)
            await update.message.reply_text("❌ Error listing links")

    async def revoke_link(self, update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
        """Initiate the process to revoke a specific invite link"""
        try:
            if not self.is_admin(update.effective_user.id):
                await update.message.reply_text(
                    "❌ Only admin can use this command")
                return

            # If a link was provided as an argument, process it immediately
            if context.args:
                link = context.args[0]
                await self.process_revoke_request(update, context, link)
                return

            # Otherwise, ask for the link
            self.pending_revokes[update.effective_user.id] = True
            await update.message.reply_text(
                "Please send the invite link you want to revoke."
            )

        except Exception as e:
            logger.error("Error initiating revoke: %s", e)
            await update.message.reply_text("❌ Error initiating revoke")

    async def process_revoke_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE, link: str):
        """Process a revoke request for a specific link"""
        try:
            if link in self.link_data:
                # Try to revoke via API
                try:
                    await context.bot.revoke_chat_invite_link(
                        GROUP_CHAT_ID, link)
                except:
                    pass  # Link might already be expired or invalid

                # Remove from our tracking
                del self.link_data[link]
                self.save_data()

                await update.message.reply_text("✅ Link revoked successfully")
                logger.info("Revoked link: %s", link)
            else:
                await update.message.reply_text("❌ Link not found in database")

        except Exception as e:
            logger.error("Error revoking link: %s", e)
            await update.message.reply_text("❌ Error revoking link")

    async def revoke_all_links(self, update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
        """Initiate the process to revoke all active links with confirmation"""
        try:
            if not self.is_admin(update.effective_user.id):
                await update.message.reply_text(
                    "❌ Only admin can use this command")
                return

            # Check if there are active links
            current_time = time.time()
            active_links = [
                link for link, info in self.link_data.items()
                if info['expires_at'] > current_time and info['uses'] < info['max_uses']
            ]

            if not active_links:
                await update.message.reply_text("No active links to revoke.")
                return

            # Ask for confirmation
            self.pending_confirmations[update.effective_user.id] = True
            await update.message.reply_text(
                f"⚠️ This will revoke ALL {len(active_links)} active invite links.\n\n"
                "Type 'yes' to confirm or anything else to cancel."
            )

        except Exception as e:
            logger.error("Error initiating revoke all: %s", e)
            await update.message.reply_text("❌ Error initiating revoke all")

    async def handle_pending_actions(self, update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
        """Handle pending actions (confirmations and link inputs)"""
        try:
            user_id = update.effective_user.id
            
            # Handle revoke_all confirmation
            if user_id in self.pending_confirmations:
                # Remove the pending confirmation regardless of response
                del self.pending_confirmations[user_id]
                
                # Check if the response is 'yes'
                if update.message.text.lower() == 'yes':
                    # Revoke all active links
                    current_time = time.time()
                    revoked_count = 0
                    
                    for link, info in list(self.link_data.items()):
                        if info['expires_at'] > current_time and info['uses'] < info['max_uses']:
                            try:
                                await context.bot.revoke_chat_invite_link(GROUP_CHAT_ID, link)
                                revoked_count += 1
                            except TelegramError as e:
                                logger.error("Error revoking link %s: %s", link, e)
                            # Remove from our data regardless of API success
                            del self.link_data[link]
                    
                    self.save_data()
                    await update.message.reply_text(f"✅ Successfully revoked {revoked_count} active invite links.")
                    logger.info("Revoked %d active links by user %s", revoked_count, user_id)
                else:
                    await update.message.reply_text("❌ Operation cancelled.")
                return
            
            # Handle revoke link input
            if user_id in self.pending_revokes:
                # Remove the pending revoke regardless of response
                del self.pending_revokes[user_id]
                
                # Process the link
                link = update.message.text.strip()
                await self.process_revoke_request(update, context, link)
                
        except Exception as e:
            logger.error("Error handling pending action: %s", e)
            await update.message.reply_text("❌ Error processing your request")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        await update.message.reply_text(
            "🤖 Group Manager Bot\n\n"
            "Available commands:\n"
            "/link - Generate a one-time invite link\n"
            "/list_links - List all active invite links\n"
            "/revoke - Revoke a specific invite link\n"
            "/revoke_all - Revoke all active invite links\n\n"
            "Note: This bot also automatically cleans system messages and command messages."
        )


def main():
    """Start the bot"""
    # Initialize bot
    bot = TelegramGroupManagerBot()

    # Create application
    application = Application.builder().token(BOT_TOKEN_B).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("link", bot.generate_invite_link))
    application.add_handler(CommandHandler("list_links", bot.list_links))
    application.add_handler(CommandHandler("revoke", bot.revoke_link))
    application.add_handler(CommandHandler("revoke_all", bot.revoke_all_links))

    # Add handler for pending actions (confirmations and link inputs)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_pending_actions))

    # Add handler for cleaning system messages
    application.add_handler(
        MessageHandler(filters.ALL, bot.clean_system_messages))

    # Add handler for deleting command messages (except from admin)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND,
                       bot.delete_command_messages))

    # Start bot
    logger.info("Starting bot...")
    application.run_polling()


if __name__ == "__main__":
    main()