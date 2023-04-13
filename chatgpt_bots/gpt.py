import json
from functools import reduce
from collections import defaultdict
from pathlib import Path

import openai
from bots.applications._base import Application
from bots.utils import stabelise_string
from openai.error import APIConnectionError
from telegram import BotCommand, BotCommandScopeChat, MessageEntity, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from telegram.helpers import escape_markdown

SET_BEHAVIOUR = 0


class GPT(Application):
    class Arguments(Application.Arguments):
        openai_api_key: str

        gpt_model: str = r"gpt-3.5-turbo"
        gpt_instructions: str = (
            "You are a Telegram bot. You are a helpful assistant. Provide short, concise, and relevant answers to"
            " save API costs and improve user experience."
        )

        name: str = "GPT-3.5"

        data_storage: Path | None = None
        enable_custom_behaviour: bool = True

        whitelist: list[str | int] = []

    arguments: "GPT.Arguments"

    conversation_histories = defaultdict(list[dict[str, str]])

    @property
    def gpt_name(self):
        return self.arguments.name

    # =========
    # LIFECYCLE
    # =========

    async def on_initialize(self):
        await super().on_initialize()

        if key := getattr(self.arguments, "openai_api_key", None):
            openai.api_key = key

        if self.arguments.whitelist:
            user_filter = lambda user: filters.User(user) if isinstance(user, int) else filters.User(username=user)
            user_filters = reduce(
                lambda filter, user: filter | user_filter(user),
                self.arguments.whitelist[1:],
                user_filter(self.arguments.whitelist[0]),
            )
            self.application.add_handler(
                MessageHandler(
                    filters.ALL & (~user_filters),
                    self.msg_handle_disallowed,
                )
            )

        if self.arguments.enable_custom_behaviour:
            self.application.add_handler(
                ConversationHandler(
                    entry_points=[
                        CommandHandler("behaviour", self.conv_behaviour_start, filters=filters.ChatType.PRIVATE)
                    ],
                    states={SET_BEHAVIOUR: [MessageHandler(filters.TEXT, self.conv_behaviour_set)]},
                    fallbacks=[
                        CommandHandler("cancel", self.conv_behaviour_cancel),
                        MessageHandler(filters.ALL, self.conv_noop),
                    ],
                )
            )
        self.application.add_handler(CommandHandler("start", self.cmd_start, filters=filters.ChatType.PRIVATE))
        self.application.add_handler(
            CommandHandler("start", self.cmd_start_not_private, filters=~filters.ChatType.PRIVATE)
        )
        self.application.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, self.msg_handle_text)
        )
        self.application.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, self.msg_not_supported))
        self.application.add_handler(
            CommandHandler(("new", "clear", "new_thread"), self.cmd_new, filters=filters.ChatType.PRIVATE)
        )
        await self._set_commands()
        self._load_conversation_history()

    async def _set_commands(self, chat_id: int | None = None, with_cancel: bool = False):
        commands = [
            BotCommand(
                "start",
                f"Start a conversation with the {self.gpt_name} bot in a private chat.",
            ),
            BotCommand("new", "Start a new conversation."),
        ]

        if self.arguments.enable_custom_behaviour:
            commands.append(BotCommand("behaviour", "Define ChatGPT behavior instructions"))

        if with_cancel:
            commands.append(BotCommand("/cancel", "Cancel current operation"))

        await self.application.bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id) if chat_id else None)

    async def on_shutdown(self):
        await super().on_shutdown()
        self._save_conversation_history()

    def _load_conversation_history(self):
        if self.arguments.data_storage:
            self.arguments.data_storage.parent.mkdir(parents=True, exist_ok=True)

            if not self.arguments.data_storage.exists():
                self.arguments.data_storage.touch()

            history = {
                int(id_): history
                for id_, history in json.loads(self.arguments.data_storage.read_text() or "{}").items()
            }
            self.conversation_histories.update(history)

    def _save_conversation_history(self):
        if self.arguments.data_storage:
            self.arguments.data_storage.write_text(
                json.dumps(self.conversation_histories, ensure_ascii=False, sort_keys=True, indent=2)
            )

    # ========
    # HANDLERS
    # ========

    async def handle_error(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Error handler"""
        self.logger.error(msg="Exception while handling an update:", exc_info=context.error)
        if not update.message:
            return
        await update.message.reply_text("An error occurred. Restarting conversation...")
        await self.cmd_new(update, context)

    async def cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Start a conversation with the ChatGPT bot in a private chat."""
        if not update.effective_user or not update.message:
            return
        user = update.effective_user
        await self._reset_thread(update.effective_user.id)
        newline = "\n\n"

        await update.message.reply_markdown_v2(
            rf"Hi {user.mention_markdown_v2()}\!, I am a {stabelise_string(self.gpt_name)} bot\. Send me a message and"
            rf" I'll generate a response\.{newline}[Source Code](https://github.com/Nachtalb/chatgpt_telegram) \|"
            r" [Author](https://t.me/Nachtalb)",
            disable_web_page_preview=True,
            reply_markup=ReplyKeyboardRemove(),
        )

    async def cmd_start_not_private(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Inform the user that the ChatGPT bot only works in private messages."""
        if not update.effective_user or not update.message or not update.effective_chat:
            return
        user = update.effective_user
        newline = "\n\n"
        await update.message.reply_markdown_v2(
            rf"Hi {user.mention_markdown_v2()}\!, I am a {stabelise_string(self.gpt_name)} bot\. I only work in private"
            rf" messages and not in groups or channels\.{newline}[Source"
            r" Code](https://github.com/Nachtalb/chatgpt_telegram) \| [Author](https://t.me/Nachtalb)",
            disable_web_page_preview=True,
            reply_markup=ReplyKeyboardRemove(),
        )

    async def cmd_new(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Start a new conversation thread by clearing the existing conversation history."""
        if not update.effective_user or not update.message:
            return
        await self._reset_thread(update.effective_user.id)
        await update.message.reply_text(
            "No problem, I’m glad you enjoyed our previous conversation. Let’s move on to a new topic. Ask me"
            " anything..."
        )

    async def conv_behaviour_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation to set a custom system message"""
        if not update.effective_user or not update.message:
            return ConversationHandler.END
        await update.message.reply_text(
            'Provide instructions for how ChatGTP should act during the conversation. For example "Talk in the way H.P.'
            ' Lovecraft wrote his books." \nEnter your instructions now or use /cancel to abort the operation.'
        )

        await self._set_commands(update.effective_user.id, with_cancel=True)

        return SET_BEHAVIOUR

    async def conv_behaviour_set(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
        """Set a custom system message"""
        if not update.effective_user or not update.message or not update.message.text:
            return SET_BEHAVIOUR

        await self._reset_thread(update.effective_user.id, update.message.text)
        safe_behaviour = escape_markdown(update.message.text, 2, MessageEntity.CODE)
        await update.message.reply_markdown_v2(
            rf"Your ChatGPT behaviour is set to `{safe_behaviour}`\. To reset the instructions use \/new\.You can"
            r" start talking now\."
        )
        await self._set_commands(update.effective_user.id)
        return ConversationHandler.END

    async def conv_behaviour_cancel(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the behaviour setting"""
        if not update.effective_user or not update.message:
            return SET_BEHAVIOUR
        await update.message.reply_text(
            "The operation has been canceled, and no changes have been made to the ChatGPT behaviour instructions. If"
            " you wish to set or update the instructions in the future, use the /behaviour command."
        )

        await self._set_commands(update.effective_user.id)
        return ConversationHandler.END

    async def conv_noop(self, _: Update, __: ContextTypes.DEFAULT_TYPE):
        """Do nothing"""
        return

    async def msg_handle_disallowed(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Inform non whitelisted users that they can't use the bot"""
        if not update.message:
            return

        await update.message.reply_markdown(
            "You currently have no access to this bot.\n\nThis bot uses the paid OpenAI API. To keep the costs down"
            " this bot is currently only usable for invited users.\nHowever this bot is open source on"
            " [Github](https://github.com/Nachtalb/chatgpt_telegram). So you can deploy your own instance. For any"
            " questions you can contact @Nachtalb."
        )

    async def msg_handle_text(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages and generate a response using the ChatGPT API."""
        if not update.effective_user or not update.message or not update.message.text:
            return
        user = update.effective_user
        user_input = update.message.text

        message = await update.message.reply_text("Getting an answer...")
        await user.send_chat_action(ChatAction.TYPING)

        self.conversation_histories[user.id].append({"role": "user", "content": user_input})
        try:
            response = await self._generate_response(self.conversation_histories[user.id])
        except openai.InvalidRequestError:
            await message.edit_text(
                "Your message could not be processed. It may have been too long. Please try again with a different"
                " message."
            )
            return

        if not response:
            await update.message.reply_text(
                f"An error occurred, please try again or use /new to start a new conversation."
            )
            self.conversation_histories[user.id].pop()
            return

        self.conversation_histories[user.id].append({"role": "assistant", "content": response})

        try:
            await message.edit_text(stabelise_string(response), parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest:
            await message.edit_text(response)
        self._save_conversation_history()

    async def msg_not_supported(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages and generate a response using the ChatGPT API."""
        if not update.message:
            return
        await update.message.reply_text("I currently do not support this type of message.")

    # ===
    # GPT
    # ===

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
        return response.choices[0].message.content  # pyright: ignore[reportUnboundVariable, reportGeneralTypeIssues]

    async def _reset_thread(self, user_id: int, system_message: str = ""):
        """
        Reset the conversation history for a given user.

        Args:
            user_id (int): The unique identifier of the user.
        """
        self.conversation_histories[user_id] = [
            {
                "role": "system",
                "content": system_message or self.arguments.gpt_instructions,
            }
        ]
        self._save_conversation_history()


Application = GPT
