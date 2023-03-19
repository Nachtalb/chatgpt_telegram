# Telegram GPT Chatbots

This bot manages multiple different GPT chatbots for Telegram. They provide
a ChatGPT and BingChat like experience directly in Telegram.

## Install

1. Get the necessary api keys via [BotFather][botfather_docs] and your [OpenAI dashboard][openai_docs].
2. Install [Poetry dependency manager][pm_docs] if you don't have already.
3. Clone the repo to your host then.
4. Install it via poetry
5. Run `start-bots`:

```bash
git clone https://github.com/Nachtalb/chatgpt_telegram
cd chatgpt_telegram
poetry install
cp config.example.json config.json  # Adjust config.json file
mv /path/to/cookies.json .  # Retrieve and move the cookies.json here as per
                            # EdgeGPT documentation:
                            # https://github.com/acheong08/EdgeGPT#getting-authentication-required
poetry run start-bots
```

## Developing

### Base

Create a new module in `bots.applications`:

```text
bots
├── ...
└── applications
   ├── ...
   └── my_app.py

```

Create and application in `my_app.py`:

```python
from bots.applications._base import ApplicationWrapper

class MyApp(ApplicationWrapper):
    pass

Application = MyApp
```

Adjust `config.json` to use your new app.

```json
{
  ...,
  "app_configs": [
    {
      "id": "my-app",
      "telegram_token": "123....",
      "auto_start": true,
      "module_name": "my_app"
    }
  ]
}
```

### Setup

Now your bot is already configured and working. But of course you want some
functionality. For this you can simply adjust the `setup()` method to configure
your application.

```python
class MyApplication(ApplicationWrapper):
    async def setup(self):
        self.application.add_handler(MessageHandler(filters.TEXT, self.echo))

    async def echo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message:
            await update.message.reply_markdown_v2(update.message.text_markdown_v2_urled)
```

### Custom Config

Maybe you want to run multiple telegram bots of the same type to decrease
rate limits in channels or something alike. So you need a way to pass custom
arguments to your bot. You can do so by defining "Arguments".

First add your arguments to the class:

```python
from pathlib import Path
from bots.applications._base import ApplicationWrapper

class MyApplication(ApplicationWrapper):
    class Arguments(ApplicationWrapper.Arguments):
        custom_arg_1: int
        custom_arg_2: Path

    arguments: "MyApplication.Arguments"  # Make sure type hinting works

    async def setup(self):
        ...
        do_stuff_with(self.arguments.custom_arg_1, self.arguments.custom_arg_2)
```

Then add the arguments to your `config.json`. In this example I now create
two bots of the same kind with different arguments (also make sure the `id` is
unique):

```json
{
  ...,
  "app_configs": [
    {
      "id": "my-app-1",
      "telegram_token": "123....",
      "auto_start": true,
      "module_name": "my_app",
      "arguments": {
        "custom_arg_1": "Some text",
        "custom_arg_2": "path/to/a/file.txt"
      }
    },
    {
      "id": "my-app-2",
      "telegram_token": "456....",
      "auto_start": true,
      "module_name": "my_app",
      "arguments": {
        "custom_arg_1": "Another text",
        "custom_arg_2": "path/to/a/different/file.txt"
      }
    }
  ]
}

```

## Usage

After you have started the manager with `poetry run start-bots` you can open
the shown url `https://localhost:8000` and manage your bots.

## Credits

This bot was developed by [Nachtalb][author] using the [Python Telegram Bot
library][library] and [OpenAI's][openai] GPT 3.5 and 4 models and
[EdgeGPT][edgegpt] for the BingChat integration.

## Source Code

The source code for this bot is available on [Github][source_code].

[pm_docs]: https://python-poetry.org/docs/ "Python packaging and dependency management made easy"
[openai_docs]: https://beta.openai.com/docs/api-reference/authentication "OpenAI Documentation"
[botfather_docs]: https://core.telegram.org/bots#creating-a-new-bot "Telegram Bots: An introduction for developers"
[author]: https://t.me/Nachtalb "Nachtalb"
[library]: https://python-telegram-bot.org/ "Python Telegram Bot library"
[openai]: https://openai.com/ "OpenAI"
[source_code]: https://github.com/Nachtalb/chatgpt_telegram "Github Repository"
[edgegpt]: https://github.com/acheong08/EdgeGPT "Unofficial  Bing Chat API"
