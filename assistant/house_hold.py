"""Spoken hold line for the Discord watch room.

If a turn is still unanswered after eight seconds, speak one resting-voice
line, optionally a second wait line, then leave a short gap before the answer.
A reply that is ready sooner never speaks a hold line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

HOLD_SECONDS = float(os.environ.get("HOUSE_HOLD_SECONDS", "8"))
PAD_SECONDS = float(os.environ.get("HOUSE_HOLD_PAD_SECONDS", "0.75"))
FIRST_LINES = (
    "Let me take a look.",
    "I'm checking on that.",
    "Researching.",
)
WAIT_LINE = "Please wait for the response."
ANNOUNCE_PORT = int(os.environ.get("HOUSE_ANNOUNCE_PORT", "9120"))

Speak = Callable[[str, asyncio.Event], Awaitable[bool]]

_holds: dict[tuple, "HouseHold"] = {}
_announce_started = False
_announce_adapter = None
_loop: Optional[asyncio.AbstractEventLoop] = None


class HouseHold:
    def __init__(self, speak: Speak, *, delay: float = HOLD_SECONDS, pad: float = PAD_SECONDS) -> None:
        self._speak = speak
        self._delay = delay
        self._pad = pad
        self.answer = asyncio.Event()
        self.spoke = False
        self.task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    def answer_ready(self) -> None:
        self.answer.set()

    async def finish(self, *, speak_answer: bool) -> None:
        self.answer_ready()
        if self.task is not None:
            await self.task
        if speak_answer and self.spoke and self._pad > 0:
            await asyncio.sleep(self._pad)

    async def _run(self) -> None:
        try:
            await asyncio.wait_for(self.answer.wait(), self._delay)
            return
        except TimeoutError:
            pass
        if self.answer.is_set():
            return
        played = await self._speak(random.choice(FIRST_LINES), self.answer)
        if not played:
            return
        self.spoke = True
        if self.answer.is_set():
            return
        if await self._speak(WAIT_LINE, self.answer):
            self.spoke = True


def _platform_value(source) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "")


def _discord_adapter(runner):
    adapters = getattr(runner, "adapters", None) or {}
    for key, adapter in adapters.items():
        if str(getattr(key, "value", key) or "") == "discord":
            return adapter
    return None


def _voice_guild(adapter, chat_id: str):
    channels = getattr(adapter, "_voice_text_channels", None) or {}
    is_in = getattr(adapter, "is_in_voice_channel", None)
    for guild_id, text_id in channels.items():
        if str(text_id) != str(chat_id):
            continue
        if callable(is_in) and not is_in(guild_id):
            continue
        return guild_id
    return None


def _hold_key(turn_ctx) -> tuple:
    return (getattr(turn_ctx, "session_key", None), getattr(turn_ctx, "run_generation", None))


def maybe_start_house_hold(runner, turn_ctx) -> None:
    """Start the eight-second clock when this Discord turn can be spoken."""
    source = getattr(turn_ctx, "source", None)
    if source is None or _platform_value(source) != "discord":
        return
    adapter = _discord_adapter(runner)
    if adapter is None:
        return
    guild_id = _voice_guild(adapter, getattr(source, "chat_id", ""))
    if guild_id is None:
        return

    async def speak(phrase: str, cancel: asyncio.Event) -> bool:
        return await speak_phrase(adapter, guild_id, phrase, cancel)

    hold = HouseHold(speak)
    hold.start()
    _holds[_hold_key(turn_ctx)] = hold


async def finish_house_hold(session_key, run_generation, *, speak_answer: bool) -> None:
    hold = _holds.pop((session_key, run_generation), None)
    if hold is None:
        return
    await hold.finish(speak_answer=speak_answer)


async def speak_phrase(adapter, guild_id: int, phrase: str, cancel: asyncio.Event) -> bool:
    """Synthesize and play one line. Return False if the answer arrived first."""
    if cancel.is_set():
        return False
    path = os.path.join(tempfile.gettempdir(), "hermes_voice", f"hold_{uuid.uuid4().hex[:12]}.mp3")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    actual = path
    try:
        from tools.tts_tool import text_to_speech_tool

        raw = await asyncio.to_thread(text_to_speech_tool, text=phrase, output_path=path)
        if cancel.is_set():
            return False
        try:
            result = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return False
        actual = result.get("file_path", path)
        if not result.get("success") or not actual or not os.path.isfile(actual):
            return False
        if cancel.is_set():
            return False
        played = await adapter.play_in_voice_channel(guild_id, actual)
        return bool(played)
    except Exception:
        logger.debug("watch hold line failed", exc_info=True)
        return False
    finally:
        for candidate in {path, actual}:
            if candidate and os.path.isfile(candidate):
                try:
                    os.unlink(candidate)
                except OSError:
                    pass


def _token_path() -> Path:
    home = Path(os.environ.get("HERMES_HOME", "/home/hermes/.hermes"))
    return home / "watch-announce.token"


def _read_token() -> str:
    path = _token_path()
    if not path.exists():
        token = uuid.uuid4().hex
        path.write_text(token + "\n", encoding="utf-8")
        path.chmod(0o600)
        return token
    return path.read_text(encoding="utf-8").strip()


def _watch_channel(adapter):
    client = getattr(adapter, "_client", None)
    if client is None:
        return None
    configured = os.environ.get("WATCH_TEXT_CHANNEL_ID", "").strip()
    if configured:
        return client.get_channel(int(configured))
    for guild in getattr(client, "guilds", []) or []:
        for channel in getattr(guild, "text_channels", []) or []:
            if getattr(channel, "name", "") == "watch":
                return channel
    return None


async def announce_text(text: str) -> None:
    adapter = _announce_adapter
    if adapter is None:
        raise RuntimeError("discord adapter is not connected")
    channel = _watch_channel(adapter)
    if channel is None:
        raise RuntimeError("watch text channel was not found")
    await channel.send(text[:400])
    guild = getattr(channel, "guild", None)
    guild_id = getattr(guild, "id", None)
    is_in = getattr(adapter, "is_in_voice_channel", None)
    if guild_id is None or not callable(is_in) or not is_in(guild_id):
        return
    # Alerts are already decided. Play them even though the answer "exists".
    await speak_phrase(adapter, guild_id, text[:400], asyncio.Event())


def start_announce_server(adapter) -> None:
    """LAN endpoint Home Assistant uses to post and speak a mail alert."""
    global _announce_started, _announce_adapter, _loop
    _announce_adapter = adapter
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _announce_started:
        return
    token = _read_token()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path != "/announce":
                self.send_error(404)
                return
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {token}":
                self.send_error(401)
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > 4000:
                self.send_error(400)
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                text = str(body.get("text") or "").strip()
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                self.send_error(400)
                return
            if not text:
                self.send_error(400)
                return
            if _loop is None or _announce_adapter is None:
                self.send_error(503)
                return
            future = asyncio.run_coroutine_threadsafe(announce_text(text), _loop)
            try:
                future.result(timeout=30)
            except Exception as exc:
                logger.warning("watch announce failed: %s", exc)
                message = str(exc).encode("utf-8", "replace")
                self.send_response(502)
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)
                return
            payload = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):
            logger.info("watch announce: " + fmt, *args)

    server = ThreadingHTTPServer(("0.0.0.0", ANNOUNCE_PORT), Handler)
    threading.Thread(target=server.serve_forever, name="watch-announce", daemon=True).start()
    _announce_started = True
    logger.info("Watch announce listening on %s", ANNOUNCE_PORT)
