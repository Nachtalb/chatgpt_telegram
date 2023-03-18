from collections import defaultdict

import openai
from telegram import BotCommand, Update
from telegram.constants import ChatAction
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from bots.applications._base import ApplicationWrapper


class GPT(ApplicationWrapper):
    conversation_histories = defaultdict(list[dict[str, str]])

    async def setup(
        self,
        openai_api_key: str = "",
        gpt_name: str = r"GPT\-3\.5",
        gpt_model: str = "gpt-3.5-turbo",
        gpt_version: int | float = 3.5,
    ):
        if openai_api_key:
            openai.api_key = openai_api_key

        self.gpt_name = gpt_name
        self.gpt_model = gpt_model
        self.gpt_version = gpt_version

        self.application.add_handler(CommandHandler("start", self.start, filters=filters.ChatType.PRIVATE))
        self.application.add_handler(CommandHandler("start", self.start_not_private, filters=~filters.ChatType.PRIVATE))
        self.application.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, self.handle_text)
        )
        self.application.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, self.not_supported))
        self.application.add_handler(CommandHandler("new_thread", self.new_thread, filters=filters.ChatType.PRIVATE))

        if self.application.job_queue:
            self.application.job_queue.run_once(self.on_startup, 0.0)

    async def on_startup(self, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.set_my_commands(
            [
                BotCommand(
                    "start",
                    f"Start a conversation with the {self.gpt_name} bot in a private chat.",
                ),
                BotCommand("new_thread", "Start a new conversation."),
            ]
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start a conversation with the ChatGPT bot in a private chat."""
        if not update.effective_user or not update.message:
            return
        user = update.effective_user
        self._reset_thread(update.effective_user.id)
        newline = "\n\n"
        await update.message.reply_markdown_v2(
            rf"Hi {user.mention_markdown_v2()}\!, I am a {self.gpt_name} bot\. Send me a message and I'll"
            r" generate a"
            rf" response\.{newline}[Source Code](https://github.com/Nachtalb/chatgpt_telegram) \|"
            r" [Author](https://t.me/Nachtalb)",
            disable_web_page_preview=True,
        )

    async def start_not_private(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inform the user that the ChatGPT bot only works in private messages."""
        if not update.effective_user or not update.message or not update.effective_chat:
            return
        user = update.effective_user
        newline = "\n\n"
        await update.message.reply_markdown_v2(
            rf"Hi {user.mention_markdown_v2()}\!, I am a {self.gpt_name} bot\. I only work in private"
            r" messages and"
            r" not in groups or"
            rf" channels\.{newline}[Source Code](https://github.com/Nachtalb/chatgpt_telegram) \|"
            r" [Author](https://t.me/Nachtalb)",
            disable_web_page_preview=True,
        )

    async def _generate_response(self, conversation_history) -> str:
        """
        Generate a response using the ChatGPT API based on the conversation history.

        Args:
            conversation_history (list[dict]): A list of dictionaries containing the conversation history.

        Returns:
            str: The generated response from the ChatGPT API.
        """
        response = await openai.ChatCompletion.acreate(model=self.gpt_model, messages=conversation_history)
        return response.choices[0].message.content

    def _reset_thread(self, user_id: int):
        """
        Reset the conversation history for a given user.

        Args:
            user_id (int): The unique identifier of the user.
        """
        self.conversation_histories[user_id] = [
            {
                "role": "system",
                "content": (
                    "You are Telegram bot. You are a helpful assistant. Provide short, concise, and relevant answers to"
                    " save API costs and improve user experience."
                ),
            }
        ]

    async def new_thread(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start a new conversation thread by clearing the existing conversation history."""
        if not update.effective_user or not update.message:
            return
        self._reset_thread(update.effective_user.id)
        await update.message.reply_text("New thread started. Your conversation history has been cleared.")

    conversation_histories = defaultdict(list[dict[str, str]])

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages and generate a response using the ChatGPT API."""
        if not update.effective_user or not update.message or not update.message.text:
            return
        user = update.effective_user
        user_input = update.message.text
        await user.send_chat_action(ChatAction.TYPING)

        self.conversation_histories[user.id].append({"role": "user", "content": user_input})

        response = await self._generate_response(self.conversation_histories[user.id])
        self.conversation_histories[user.id].append({"role": "assistant", "content": response})

        await update.message.reply_text(response)

    async def not_supported(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages and generate a response using the ChatGPT API."""
        if not update.message:
            return
        await update.message.reply_text("I currently do not support this type of message.")


Application = GPT
