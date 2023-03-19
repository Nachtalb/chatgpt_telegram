import json
from collections import defaultdict
from pathlib import Path

import openai
from openai.error import APIConnectionError
from telegram import BotCommand, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from bots.applications._base import ApplicationWrapper
from bots.utils import stabelise_string


class GPT(ApplicationWrapper):
    class Arguments(ApplicationWrapper.Arguments):
        openai_api_key: str | None = None

        gpt_model: str = r"gpt-3.5-turbo"
        gpt_name: str = "GPT-3.5"

        data_storage: Path | None = None

    arguments: "GPT.Arguments"

    conversation_histories = defaultdict(list[dict[str, str]])

    async def setup(self):
        if self.arguments.openai_api_key:
            openai.api_key = self.arguments.openai_api_key

        self.application.add_handler(CommandHandler("start", self.start, filters=filters.ChatType.PRIVATE))
        self.application.add_handler(CommandHandler("start", self.start_not_private, filters=~filters.ChatType.PRIVATE))
        self.application.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, self.handle_text)
        )
        self.application.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, self.not_supported))
        self.application.add_handler(
            CommandHandler(("new", "clear", "new_thread"), self.new_thread, filters=filters.ChatType.PRIVATE)
        )

        if self.application.job_queue:
            self.application.job_queue.run_once(self.on_startup, 0.0)

    def _load_conversation_history(self):
        if self.arguments.data_storage:
            if not self.arguments.data_storage.exists():
                self.arguments.data_storage.touch()
            self.conversation_histories.update(json.loads(self.arguments.data_storage.read_text() or "{}"))

    def _save_conversation_history(self):
        if self.arguments.data_storage:
            self.arguments.data_storage.write_text(
                json.dumps(self.conversation_histories, ensure_ascii=False, sort_keys=True, indent=2)
            )

    @property
    def gpt_name(self):
        return self.arguments.gpt_name

    async def on_startup(self, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.set_my_commands(
            [
                BotCommand(
                    "start",
                    f"Start a conversation with the {self.gpt_name} bot in a private chat.",
                ),
                BotCommand("new", "Start a new conversation."),
            ]
        )

    async def startup(self):
        self._load_conversation_history()

    async def shutdown(self):
        self._save_conversation_history()

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

    async def _generate_response(self, conversation_history, retry: bool = True) -> str:
        """
        Generate a response using the ChatGPT API based on the conversation history.

        Args:
            conversation_history (list[dict]): A list of dictionaries containing the conversation history.

        Returns:
            str: The generated response from the ChatGPT API.
        """
        try:
            response = await openai.ChatCompletion.acreate(
                model=self.arguments.gpt_model, messages=conversation_history
            )
        except APIConnectionError:
            if retry:
                return await self._generate_response(conversation_history, retry=False)
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
        if not response:
            await update.message.reply_text(
                f"An error occurred, please use /new_thread and try again or if it still doesn't work contact @Nachtalb"
            )
            self.conversation_histories[user.id].pop()
            return

        self.conversation_histories[user.id].append({"role": "assistant", "content": response})

        try:
            await update.message.reply_markdown_v2(stabelise_string(response))
        except BadRequest:
            await update.message.reply_text(response)

    async def not_supported(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages and generate a response using the ChatGPT API."""
        if not update.message:
            return
        await update.message.reply_text("I currently do not support this type of message.")


Application = GPT
