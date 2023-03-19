import logging
from pathlib import Path
import re

from telegram.ext import ContextTypes

from EdgeGPT import Chatbot
from telegram import Message, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from yarl import URL

from bots.applications.gpt import GPT
from bots.utils import async_throttled_iterator, stabelise_string


class BingChat(GPT):
    conversation_histories: dict[int, Chatbot] = {}

    class Arguments(GPT.Arguments):
        cookies_file: Path

    arguments: "BingChat.Arguments"

    async def teardown(self):
        return await self.close_connections()

    def get_chatbot(self, user_id: int) -> Chatbot:
        """
        Get or create a new chatbot for the user

        Args:
            user_id (int): The unique Telegram user id
        """
        chatbot = self.conversation_histories.get(user_id)
        if not chatbot:
            if not self.arguments.cookies_file.exists():
                raise ValueError(f"BingChat cookies file {self.arguments.cookies_file.absolute()} does not exist!")
            self.conversation_histories[user_id] = chatbot = Chatbot(str(self.arguments.cookies_file))
        return chatbot

    def _transform_to_tg_text(self, message: dict) -> str:
        text = message.get("text", "")
        attributes = message["sourceAttributions"]

        text = stabelise_string(text)

        matches = tuple(re.finditer(r"\\\[\^(\d+)\^\\\]", text))

        for match in reversed(matches):
            attr = attributes[int(match.group(1)) - 1]
            url = URL(attr["seeMoreUrl"])
            host = url.host.replace(".", r"\.")  # pyright: ignore[reportOptionalMemberAccess]
            link = rf"\[[{host}]({url})\]"

            pre, post = text[: match.start()], text[match.end() :]
            text = pre + link + post

        return text

    async def close_connections(self):
        for bot in self.conversation_histories.values():
            await bot.close()

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages and generate a response using the BingChat API."""
        if not update.effective_user or not update.message or not update.message.text:
            return
        user = update.effective_user
        user_input = update.message.text
        await user.send_chat_action(ChatAction.TYPING)

        message: Message = await update.message.reply_text("Getting an answer...")
        suggestions: list[list[str]] = []
        text = ""

        async for response in async_throttled_iterator(self.get_chatbot(user.id).ask_stream(user_input), 1):
            match response:
                case (bool(_), str(text)):
                    text = stabelise_string(text, replace_brackets=False)
                    split = text.split("\n\n", 1)
                    if len(split) > 1:
                        text = split[1]

                    try:
                        await message.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
                    except BadRequest as error:
                        logging.error(error)
                case (bool(_), dict(response)):
                    new_message: dict = response["item"]["messages"][-1]
                    text = self._transform_to_tg_text(new_message)
                    if "suggestedResponses" in new_message:
                        suggestions = [[item["text"]] for item in new_message["suggestedResponses"]]

                        await message.delete()
                        print(text)
                        await update.message.reply_markdown_v2(
                            text,
                            reply_markup=ReplyKeyboardMarkup(
                                suggestions, one_time_keyboard=True, input_field_placeholder="Ask me anything..."
                            ),
                        )
                    else:
                        await message.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2)
                case _:
                    continue


Application = BingChat
