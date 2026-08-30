"""BriefingScheduler — automatyczny codzienny briefing o godzinie użytkownika (M5).

Decyzja architektoniczna (odejście od `docs/architecture.md`): **MemoryJobStore**,
nie SQLAlchemyJobStore. Harmonogram już ma trwałe źródło prawdy — kolumny
`users.briefing_time` / `users.timezone`. Trwały jobstore byłby drugą kopią tego
stanu (do synchronizacji przy każdej zmianie godziny) i wymuszałby joby jako
funkcje modułowe z globalnym rejestrem zależności, zamiast domknięć na `db`.
Zamiast tego joby są **odtwarzane z bazy** przy starcie (`sync_all`) i aktualizowane
punktowo (`sync_user`) po `/start`, `/time` i zmianach źródeł.

Trwałość, którą naprawdę potrzebujemy, daje tabela `briefing_runs`:
  * **idempotencja** — jeden dostarczony briefing per użytkownik per dzień,
  * **catch-up** — briefing pominięty przy wyłączonym bocie jest dostarczany
    przy najbliższym starcie (self-hosting: laptop/RPi/restart kontenera).

`briefing_runs` to wyłącznie rejestr schedulera. Ręczny `/briefing` go nie zapisuje —
nie chcemy, by podglądnięcie briefingu o 6:00 skasowało ten zaplanowany na 7:30.
Powtórzeniom treści i tak zapobiega `seen_articles`.
"""

import asyncio
import logging
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from adhd_briefing.config import settings
from adhd_briefing.db import Database

logger = logging.getLogger("adhd_briefing.scheduler")

_JOB_PREFIX = "briefing_"

# Callback dostarczający briefing: (chat_id, late=bool) -> None.
DeliverFn = Callable[..., Awaitable[None]]


def job_id(chat_id: str) -> str:
    return f"{_JOB_PREFIX}{chat_id}"


def parse_hhmm(value: str, default: tuple[int, int] = (8, 0)) -> tuple[int, int]:
    """'07:30' → (7, 30). Odporny na śmieci w bazie — fallback do `default`."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not match:
        return default
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return hour, minute


def resolve_timezone(name: str | None) -> ZoneInfo:
    """IANA name → ZoneInfo, z fallbackiem do DEFAULT_TIMEZONE (nigdy nie rzuca)."""
    for candidate in (name, settings.default_timezone):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("Nieznana strefa czasowa %r — fallback.", candidate)
    return ZoneInfo("UTC")


def now_in(tz: tzinfo) -> datetime:
    """Wstrzykiwalny zegar (testy podmieniają go w konstruktorze)."""
    return datetime.now(tz)


class BriefingScheduler:
    """Utrzymuje jeden cron-job per użytkownik, zbudowany z jego wiersza w `users`."""

    def __init__(
        self,
        db: Database,
        deliver: DeliverFn,
        *,
        clock: Callable[[tzinfo], datetime] = now_in,
        misfire_grace_time: int = 3600,
        catch_up: bool = True,
    ) -> None:
        self.db = db
        self._deliver = deliver
        self._clock = clock
        self._misfire_grace_time = misfire_grace_time
        self._catch_up = catch_up
        self.scheduler = AsyncIOScheduler()
        # Jeden briefing naraz per użytkownik — bez tego catch-up przy starcie
        # mógłby zbiec się z cronem wypadającym w tej samej minucie.
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # --- cykl życia ---

    async def start(self) -> None:
        """Startuje scheduler, odtwarza joby z bazy i nadrabia pominięty dzień.

        Musi być wywołane z działającej pętli asyncio — `AsyncIOScheduler.start()`
        wiąże się z `asyncio.get_running_loop()` (u nas: `post_init` bota).
        """
        self.scheduler.start()
        await self.sync_all()
        if self._catch_up:
            await self.catch_up()

    async def shutdown(self) -> None:
        """Zatrzymuje scheduler i czeka, aż faktycznie się zamknie.

        `AsyncIOScheduler.shutdown()` tylko planuje właściwe zamknięcie przez
        `call_soon_threadsafe`, więc zaraz po powrocie scheduler wciąż działa.
        Bez oddania sterowania pętli PTB zamknąłby ją przed dokończeniem.
        """
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            await asyncio.sleep(0)

    # --- synchronizacja jobów z bazą ---

    async def sync_all(self) -> int:
        """Odtwarza joby wszystkich użytkowników. Zwraca liczbę zaplanowanych."""
        scheduled = 0
        for row in await self.db.list_users():
            if await self.sync_user(row["chat_id"]):
                scheduled += 1
        logger.info("Scheduler: %d zaplanowanych briefingów.", scheduled)
        return scheduled

    async def sync_user(self, chat_id: str) -> bool:
        """Tworzy/aktualizuje job użytkownika wg bazy. False = nic do planowania.

        Wołane po `/start`, `/time` i zmianach źródeł, żeby nowa godzina działała
        od razu, bez restartu bota.
        """
        user = await self.db.get_user(chat_id)
        if not user or not user.get("briefing_time") or not user.get("sources"):
            # Bez źródeł briefing byłby pustym „Nothing new today" — nie planuj.
            self.unschedule(chat_id)
            return False

        hour, minute = parse_hhmm(user["briefing_time"])
        tz = resolve_timezone(user.get("timezone"))
        # Usuń przed dodaniem: `replace_existing` działa dopiero, gdy scheduler
        # wystartował. Przedtem joby czekają w `_pending_jobs`, gdzie ten sam id
        # zwyczajnie się dubluje — a dwa joby to dwie dostawy.
        self.unschedule(chat_id)
        self.scheduler.add_job(
            self._fire,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
            args=[chat_id],
            id=job_id(chat_id),
            name=f"Daily briefing {chat_id} @ {hour:02d}:{minute:02d} {tz}",
            replace_existing=True,
            coalesce=True,  # zaległe odpalenia zwijają się w jedno
            max_instances=1,
            misfire_grace_time=self._misfire_grace_time,
        )
        logger.info("Zaplanowano briefing %s na %02d:%02d %s", chat_id, hour, minute, tz)
        return True

    def unschedule(self, chat_id: str) -> None:
        if not self.scheduler.get_job(job_id(chat_id)):
            return
        self.scheduler.remove_job(job_id(chat_id))
        logger.info("Usunięto job briefingu dla %s", chat_id)

    def next_run(self, chat_id: str) -> datetime | None:
        job = self.scheduler.get_job(job_id(chat_id))
        return getattr(job, "next_run_time", None) if job else None

    # --- uruchomienie ---

    async def _fire(self, chat_id: str, *, late: bool = False) -> bool:
        """Dostarcza briefing raz na dzień. Zwraca True, gdy faktycznie wysłano.

        Data runu liczona w strefie **użytkownika**, nie serwera — inaczej briefing
        o 07:30 w Europe/Warsaw dla serwera w UTC potrafiłby wpaść na dwie różne daty.
        """
        async with self._locks[chat_id]:
            user = await self.db.get_user(chat_id)
            if not user:
                self.unschedule(chat_id)
                return False

            run_date = self._clock(resolve_timezone(user.get("timezone"))).date()
            if await self.db.is_run_done(chat_id, run_date):
                logger.info("Briefing %s na %s już dostarczony — pomijam.", chat_id, run_date)
                return False

            await self.db.record_run(chat_id, run_date, "running")
            try:
                await self._deliver(chat_id, late=late)
            except Exception:
                # Status 'failed' ≠ 'completed', więc catch-up spróbuje ponownie
                # przy następnym starcie; wyjątek nie może ubić joba schedulera.
                await self.db.record_run(chat_id, run_date, "failed")
                logger.exception("Briefing %s na %s nie powiódł się.", chat_id, run_date)
                return False
            await self.db.record_run(chat_id, run_date, "completed")
            logger.info("Briefing %s na %s dostarczony%s.", chat_id, run_date,
                        " (z opóźnieniem)" if late else "")
            return True

    async def catch_up(self) -> list[str]:
        """Dostarcza briefingi pominięte, gdy bot nie działał. Zwraca listę chat_id.

        Warunek: godzina użytkownika już minęła (w jego strefie), a dzisiejszego
        runu nie ma w `briefing_runs` jako 'completed'.
        """
        delivered: list[str] = []
        for row in await self.db.list_users():
            chat_id = row["chat_id"]
            user = await self.db.get_user(chat_id)
            if not user or not user.get("briefing_time") or not user.get("sources"):
                continue

            tz = resolve_timezone(user.get("timezone"))
            now = self._clock(tz)
            hour, minute = parse_hhmm(user["briefing_time"])
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now < due:
                continue  # dzisiejsza godzina jeszcze przed nami — zrobi to cron
            if await self.db.is_run_done(chat_id, now.date()):
                continue

            logger.info("Catch-up: briefing %s z %s (termin %s).", chat_id, now.date(), due)
            if await self._fire(chat_id, late=True):
                delivered.append(chat_id)
        return delivered
