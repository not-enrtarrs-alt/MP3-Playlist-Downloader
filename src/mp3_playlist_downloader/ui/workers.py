"""Qt thread-pool bridge for playlist operations."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace

from PySide6.QtCore import QObject, QRunnable, Signal

from .. import db, services
from ..settings import Settings
from ..youtube.errors import YouTubeError

logger = logging.getLogger(__name__)


class PlaylistSignals(QObject):
    completed = Signal(int, bool)
    error = Signal(str)
    finished = Signal()


class PlaylistWorker(QRunnable):
    """Own a fresh connection in the worker thread; discard cancelled results."""

    def __init__(self, settings: Settings, *, url: str | None = None, playlist_id: int | None = None) -> None:
        super().__init__()
        self.settings = replace(settings)
        self.url = url
        self.playlist_id = playlist_id
        self.signals = PlaylistSignals()
        self.cancelled = threading.Event()

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        try:
            connection = db.connect()
            try:
                if self.url is not None:
                    playlist_id, added = services.add_playlist(connection, self.url, self.settings, cancelled=self.cancelled.is_set)
                elif self.playlist_id is not None:
                    services.refresh_playlist(connection, self.playlist_id, self.settings, cancelled=self.cancelled.is_set)
                    playlist_id, added = self.playlist_id, False
                else:
                    raise ValueError("Missing playlist operation.")
                if not self.cancelled.is_set():
                    self.signals.completed.emit(playlist_id, added)
            finally:
                connection.close()
        except services.OperationCancelled:
            pass
        except YouTubeError as error:
            if not self.cancelled.is_set():
                self.signals.error.emit(str(error))
        except Exception:
            logger.warning("Playlist operation failed; details withheld to protect private paths.")
            if not self.cancelled.is_set():
                self.signals.error.emit("The playlist could not be saved or refreshed. Check your output folder and try again.")
        finally:
            self.signals.finished.emit()
