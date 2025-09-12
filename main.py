import logging
import json
import asyncio
from datetime import datetime, timedelta, time
from telegram import Update, ChatMember
from telegram.ext import Application, ContextTypes, CommandHandler, ChatMemberHandler, MessageHandler, filters
from telegram.error import TelegramError
import sys

# Import configuration
try:
    from config import BOT_TOKEN_A, DEBUG_CHAT_ID, ADMIN_USER_IDS
except ImportError:
    logging.error(
        "config.py file not found. Please create it with BOT_TOKEN_A, DEBUG_CHAT_ID, and ADMIN_USER_IDS"
    )
    sys.exit(1)


# Custom Unicode-friendly stream handler for Windows
class UnicodeStreamHandler(logging.StreamHandler):

    def emit(self, record):
        try:
            msg = self.format(record)
            if hasattr(sys.stdout, 'buffer'):
                sys.stdout.buffer.write(
                    msg.encode('utf-8', errors='replace') +
                    self.terminator.encode('utf-8'))
                sys.stdout.buffer.flush()
            else:
                sys.stdout.write(msg + self.terminator)
                sys.stdout.flush()
        except Exception:
            self.handleError(record)


# Initialize logging with Unicode support
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Remove existing handlers if any
logger.handlers.clear()

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Console handler with Unicode support
console_handler = UnicodeStreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# File handler (always uses UTF-8)
file_handler = logging.FileHandler("bot_debug.log", encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class MembershipTrackerBot:

    def __init__(self, token: str):
        self.token = token
        self.data_file = 'member_join_dates.json'
        self.join_data = self.load_data()
        self.debug_chat_id = DEBUG_CHAT_ID
        self.admin_user_ids = ADMIN_USER_IDS

    def load_data(self) -> dict:
        """Load member join dates from JSON file"""
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info("Loaded data for %s chats", len(data))
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("No existing data file found, starting fresh")
            return {}

    def save_data(self):
        """Save member join dates to JSON file"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.join_data, f, indent=2, ensure_ascii=False)
            logger.debug("Data saved successfully for %s chats",
                         len(self.join_data))
        except Exception as e:
            logger.error("Error saving data: %s", e)

    async def track_new_member(self, update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
        """Record join date of new members - FIXED VERSION"""
        try:
            # Check if this is a chat_member update (user joined/left)
            if update.chat_member:
                user = update.chat_member.new_chat_member.user
                chat_id = str(update.chat_member.chat.id)

                # Only track if user became a member (not left, restricted, etc.)
                if update.chat_member.new_chat_member.status == 'member':
                    if chat_id not in self.join_data:
                        self.join_data[chat_id] = {}

                    # Store join date in ISO format
                    join_date = datetime.now().isoformat()
                    self.join_data[chat_id][str(user.id)] = join_date
                    self.save_data()

                    logger.info("Tracked new member: %s in chat %s", user.id,
                                chat_id)
                    await self.send_debug_message(
                        context,
                        f"✅ New member tracked: {user.full_name} (@{user.username}) in chat {chat_id}"
                    )

            # Check if this is a message with new chat members
            elif update.message and update.message.new_chat_members:
                chat_id = str(update.message.chat.id)
                if chat_id not in self.join_data:
                    self.join_data[chat_id] = {}

                for new_member in update.message.new_chat_members:
                    # Skip if the new member is a bot
                    if new_member.is_bot:
                        continue

                    # Store join date in ISO format
                    join_date = datetime.now().isoformat()
                    self.join_data[chat_id][str(new_member.id)] = join_date

                    logger.info("Tracked new member: %s in chat %s",
                                new_member.id, chat_id)
                    await self.send_debug_message(
                        context,
                        f"✅ New member tracked: {new_member.full_name} (@{new_member.username}) in chat {chat_id}"
                    )

                self.save_data()

        except Exception as e:
            logger.error("Error tracking new member: %s", e)
            await self.send_debug_message(context,
                                          f"Error tracking member: {e}")

    async def remove_expired_members(self, context: ContextTypes.DEFAULT_TYPE):
        """Remove members who joined more than 30 days ago"""
        logger.info("Starting expired member removal job")
        await self.send_debug_message(context,
                                      "🔄 Starting expired member removal job")

        try:
            threshold_date = datetime.now() - timedelta(days=30)
            # For testing, use 1 day threshold:
            # threshold_date = datetime.now() - timedelta(days=1)
            logger.info("Threshold date for removal: %s", threshold_date)

            removal_count = 0
            error_count = 0

            for chat_id, members in list(self.join_data.items()):
                logger.info("Checking chat %s with %s members", chat_id,
                            len(members))

                for user_id, join_date_str in list(members.items()):
                    join_date = datetime.fromisoformat(join_date_str)

                    if join_date < threshold_date:
                        logger.info("Member %s expired (joined: %s)", user_id,
                                    join_date)

                        try:
                            # Kick user without ban (ban for 30 seconds then unban)
                            await context.bot.ban_chat_member(
                                chat_id=chat_id,
                                user_id=user_id,
                                until_date=int(
                                    (datetime.now() +
                                     timedelta(seconds=30)).timestamp()))
                            # Unban immediately to allow re-joining
                            await context.bot.unban_chat_member(
                                chat_id, user_id)

                            # Remove from tracking
                            del self.join_data[chat_id][user_id]
                            removal_count += 1

                            logger.info(
                                "Removed expired member: %s from chat %s",
                                user_id, chat_id)
                            await self.send_debug_message(
                                context,
                                f"Removed member {user_id} from chat {chat_id} (joined: {join_date})"
                            )

                        except TelegramError as e:
                            error_count += 1
                            logger.warning("Could not remove user %s: %s",
                                           user_id, e)
                            await self.send_debug_message(
                                context,
                                f"Failed to remove user {user_id}: {e}")

            # Save data after processing all members
            self.save_data()

            # Send summary
            summary = f"✅ Removal job completed: {removal_count} members removed, {error_count} errors"
            logger.info("Removal job completed: %s members removed, %s errors",
                        removal_count, error_count)
            await self.send_debug_message(context, summary)

        except Exception as e:
            logger.error("Error in removal job: %s", e)
            await self.send_debug_message(context, f"Removal job error: {e}")

    async def send_debug_message(self, context: ContextTypes.DEFAULT_TYPE,
                                 message: str):
        """Send debug messages to a specified chat"""
        try:
            await context.bot.send_message(
                chat_id=self.debug_chat_id,
                text=
                f"🐛 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {message}",
                parse_mode='HTML')
        except Exception as e:
            logger.error("Failed to send debug message: %s", e)

    def send_debug_message_sync(self, message: str):
        """Send debug messages synchronously (for use in non-async contexts)"""
        logger.info("SYNC DEBUG: %s", message)

    def is_admin(self, user_id: str) -> bool:
        """Check if a user ID is in the admin list"""
        return str(user_id) in self.admin_user_ids

    async def status_command(self, update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
        """Check bot status and member count"""
        try:
            chat_id = str(update.effective_chat.id)
            member_count = len(self.join_data.get(chat_id, {}))

            # Calculate next cleanup time (2:00 AM next day)
            now = datetime.now()
            next_cleanup = datetime(now.year, now.month, now.day, 2, 0,
                                    0) + timedelta(days=1)

            await update.message.reply_text(
                f"🤖 Bot Status:\n"
                f"• Tracking {member_count} members in this chat\n"
                f"• Next cleanup: {next_cleanup.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"• Data file: {self.data_file}")

            await self.send_debug_message(
                context,
                f"Status command used by {update.effective_user.full_name} in chat {chat_id}"
            )
        except Exception as e:
            logger.error("Status command error: %s", e)
            await self.send_debug_message(context,
                                          f"Status command error: {e}")

    async def manual_remove_command(self, update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
        """Manual command to trigger member removal"""
        # Check if user is admin
        if not self.is_admin(str(update.effective_user.id)):
            await update.message.reply_text("❌ Only admin can use this command"
                                            )
            return

        await update.message.reply_text("🔄 Starting manual member removal...")
        await self.send_debug_message(context,
                                      "🔄 Manual removal triggered by admin")

        # Run removal process
        await self.remove_expired_members(context)

        await update.message.reply_text("✅ Manual removal completed!")

    async def debug_command(self, update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
        """Debug command to check current data"""
        chat_id = str(update.effective_chat.id)
        member_count = len(self.join_data.get(chat_id, {}))

        debug_info = f"📊 Debug Info for Chat {chat_id}:\nMembers tracked: {member_count}\n\n"

        if chat_id in self.join_data and self.join_data[chat_id]:
            for user_id, join_date in list(
                    self.join_data[chat_id].items())[:10]:  # Show first 10
                join_dt = datetime.fromisoformat(join_date)
                days_in_group = (datetime.now() - join_dt).days
                debug_info += f"👤 {user_id}: {join_date} ({days_in_group} days ago)\n"

            if len(self.join_data[chat_id]) > 10:
                debug_info += f"\n... and {len(self.join_data[chat_id]) - 10} more members"
        else:
            debug_info += "No members tracked in this chat yet."

        await update.message.reply_text(debug_info)
        await self.send_debug_message(
            context,
            f"Debug command used by {update.effective_user.full_name} in chat {chat_id}"
        )

    async def start_command(self, update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        await update.message.reply_text(
            "🤖 Membership Tracker Bot is running!\n\n"
            "Commands:\n"
            "/status - Check bot status\n"
            "/debug - Show debug information\n"
            "/remove_now - Manually trigger member removal (admin only)")

    async def init_members(self, update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
        """Initialize by fetching current members - ADMIN ONLY"""
        if not self.is_admin(str(update.effective_user.id)):
            await update.message.reply_text("❌ Only admin can use this command"
                                            )
            return

        try:
            chat_id = str(update.effective_chat.id)
            await update.message.reply_text("🔄 Fetching current members...")

            # Get all chat members
            members = []
            async for member in context.bot.get_chat_members(chat_id):
                members.append(member)

            # Initialize data structure for this chat
            if chat_id not in self.join_data:
                self.join_data[chat_id] = {}

            # Add all current members with current time as join date
            current_time = datetime.now().isoformat()
            for member in members:
                if not member.user.is_bot:  # Skip bots
                    self.join_data[chat_id][str(member.user.id)] = current_time

            self.save_data()

            count = len(self.join_data[chat_id])
            await update.message.reply_text(
                f"✅ Initialized {count} members with current timestamp")
            await self.send_debug_message(
                context, f"Initialized {count} members in chat {chat_id}")

        except Exception as e:
            logger.error("Error initializing members: %s", e)
            await update.message.reply_text(f"❌ Error: {e}")
            await self.send_debug_message(context,
                                          f"Error initializing members: {e}")


def main():
    # Initialize bot with your token
    bot = MembershipTrackerBot(BOT_TOKEN_A)

    # Create application
    application = Application.builder().token(bot.token).build()

    # Add handlers
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("status", bot.status_command))
    application.add_handler(CommandHandler("debug", bot.debug_command))
    application.add_handler(
        CommandHandler("remove_now", bot.manual_remove_command))
    application.add_handler(CommandHandler("init_members", bot.init_members))

    # Handle both chat member updates and new chat member messages
    application.add_handler(ChatMemberHandler(bot.track_new_member))
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS,
                       bot.track_new_member))

    # Create daily cleanup job (runs at 2:00 AM server time)
    job_queue = application.job_queue

    # Schedule daily job at 2:00 AM
    job_queue.run_daily(bot.remove_expired_members,
                        time=time(hour=2, minute=0, second=0),
                        name="daily_member_cleanup")

    # Also run a test job 30 seconds after startup for debugging
    job_queue.run_once(lambda context: asyncio.create_task(
        bot.send_debug_message(context, "🤖 Bot started successfully")),
                       when=30)

    # Start bot
    logger.info("Starting bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
