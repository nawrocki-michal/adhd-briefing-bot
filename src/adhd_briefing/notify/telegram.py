"""TelegramNotifier — dostarczanie przez python-telegram-bot."""

from adhd_briefing.notify.base import NotificationService


class TelegramNotifier(NotificationService):
    """Wysyła wiadomości przez instancję telegram.Bot.

    Próbuje Markdown; przy błędzie parsowania (URL-e z _ / ( ) potrafią wywrócić
    Markdown v1) robi fallback na czysty tekst — wiadomość zawsze dochodzi.
    """

    def __init__(self, bot) -> None:
        self.bot = bot

    async def send(self, chat_id: str, message: str) -> None:
        try:
            await self.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
        except Exception:
            await self.bot.send_message(chat_id=chat_id, text=message)
