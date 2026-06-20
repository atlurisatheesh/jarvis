"""Talk to laptop-Leha from your phone via Telegram — full assistant, anywhere.

Unlike a thin brain wrapper, this routes every phone message through the SAME
pipeline as the voice listener: local reflexes first (media, phone control,
screen, email, files, Windows), then the Groq/Ollama brain with all 80+ tools.
So "read my messages" or "open WhatsApp on my phone" behave identically to
speaking to Leha.

Setup:
  1. Telegram -> @BotFather -> /newbot -> copy the token.
  2. Save token to D:\\jarvis\\.tg_token  (gitignored) or set env JARVIS_TG_TOKEN.
  3. Get your numeric id from @userinfobot -> put in config.TELEGRAM_ALLOWED_USERS.
  4. python -m jarvis_ai.telegram_bot
Text and voice notes both work (voice transcribed by the configured ears).
"""
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (Application, ContextTypes, CommandHandler,
                          MessageHandler, filters)

from . import config
from .assistant_session import AssistantSession
from .brain import Brain
from .ears import Ears

brain = Brain()
ears = Ears()
# One session per bot process; every inbound message is an explicit command,
# so we activate it before handling (no wake word needed over chat).
session = AssistantSession()


def _authorized(update: Update) -> bool:
    allowed = config.TELEGRAM_ALLOWED_USERS
    if not allowed:
        return True
    return bool(update.effective_user and update.effective_user.id in allowed)


def _route(text: str) -> str:
    """Run text through the full reflex+brain pipeline; return the spoken reply."""
    if not text:
        return "I didn't catch that, Sir."
    session.activate()  # chat messages are always intentional commands
    result = session.handle(text, brain.ask)
    if result.ignored_reason and not result.reply:
        # fall back to the brain directly if the session gate ignored it
        return brain.ask(text) or "..."
    return result.reply or "Done, Sir."


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    await update.message.reply_text(
        "Leha here, Sir. Text or send a voice note. Try:\n"
        "- read my messages\n- any new email\n- what's on the screen\n"
        "- open WhatsApp on my phone\n- weather today"
    )


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    reply = _route(update.message.text or "")
    await update.message.reply_text(reply)


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    tg_file = await update.message.voice.get_file()
    with tempfile.TemporaryDirectory() as d:
        ogg = Path(d) / "note.ogg"
        await tg_file.download_to_drive(str(ogg))
        text = ears.transcribe_file(str(ogg))
    if not text:
        await update.message.reply_text("Couldn't transcribe that, Sir.")
        return
    await update.message.reply_text(f"(heard: {text})")
    reply = _route(text)
    await update.message.reply_text(reply)


def main():
    if not config.TELEGRAM_TOKEN:
        print("Set a token first: save it to D:\\jarvis\\.tg_token "
              "or set env JARVIS_TG_TOKEN (from @BotFather).")
        return
    if not config.TELEGRAM_ALLOWED_USERS:
        print("[telegram] WARNING: TELEGRAM_ALLOWED_USERS is empty — anyone who "
              "finds the bot can control this laptop. Add your numeric id.")
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print(f"[telegram] Leha bridge running. Message your bot. "
          f"(ears={ears.engine}, brain ready)")
    app.run_polling()


if __name__ == "__main__":
    main()
