"""Testy TelegramNotifier — fallback Markdown → plain text."""

from adhd_briefing.notify import TelegramNotifier


class _FakeBot:
    def __init__(self, fail_markdown: bool = False):
        self.fail_markdown = fail_markdown
        self.calls: list[dict] = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.calls.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        if parse_mode == "Markdown" and self.fail_markdown:
            raise ValueError("can't parse entities")


async def test_send_uses_markdown_when_ok():
    bot = _FakeBot(fail_markdown=False)
    await TelegramNotifier(bot).send("123", "*hej*")
    assert len(bot.calls) == 1
    assert bot.calls[0]["parse_mode"] == "Markdown"


async def test_send_falls_back_to_plain_on_markdown_error():
    bot = _FakeBot(fail_markdown=True)
    await TelegramNotifier(bot).send("123", "*hej* https://a_b.com/x_y")
    # pierwsza próba Markdown (rzuca), druga plain (przechodzi)
    assert len(bot.calls) == 2
    assert bot.calls[0]["parse_mode"] == "Markdown"
    assert bot.calls[1]["parse_mode"] is None
    assert bot.calls[1]["text"] == "*hej* https://a_b.com/x_y"
