"""Abstrakcja dostarczania — wymienny provider (Telegram teraz, WhatsApp później)."""

from abc import ABC, abstractmethod


class NotificationService(ABC):
    """Wysyła wiadomość do użytkownika danym kanałem."""

    @abstractmethod
    async def send(self, chat_id: str, message: str) -> None:
        ...
