"""
Thumbnail cache for Synology Photos
"""

import logging
from threading import Lock, Event
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    Future,
    CancelledError,
    InvalidStateError,
)

from diskcache import Cache
from PyQt6.QtCore import QSettings

log = logging.getLogger(__name__)

# set thumbnail cache
THUMB_CALLABLE_NAME = "get_thumb"
cache = Cache(
    QSettings("fdenivac", "SynoPhotosExplorer").value("thumbcachepath", ".cache_synophoto"),
    size_limit=QSettings("fdenivac", "SynoPhotosExplorer").value("thumbcachesize", 1024 * 1024 * 512),
    statistics=1,
)


class ControlDownloadPool:
    """
    Clean results and Future objects,
    Cancel all futures

    """

    def __init__(self):
        self._lock = Lock()
        self._event_quit = Event()
        self.futures: [Future] = []

    def add_future(self, future: Future):
        self._lock.acquire()
        self.futures.append(future)
        self._lock.release()

    def clean_futures(self):
        self._lock.acquire()
        for future in as_completed(self.futures):
            try:
                # read result for clean future reference
                self.futures.remove(future)
                log.debug("clean_futures future removed")
                future.result()
            except (InvalidStateError, CancelledError) as _e:
                pass
            except Exception as _e:
                log.info(f"clean_futures EXCEPTION: {_e}")
        self._lock.release()

    def loop_clean_futures(self, time_loop: float = 1.0):
        """
        loop clean futures (in thread possibly)
        """
        while True:
            self.clean_futures()
            if self._event_quit.wait(time_loop):
                return

    def cancel_futures(self):
        log.debug("cancel_futures start")
        self._lock.acquire()
        for future in self.futures:
            if not future.done():
                future.cancel()
        log.debug("cancel_futures end")
        self._lock.release()

    def exit_loop(self):
        self._event_quit.set()


# download thread pool
download_thread_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="thumb")

# manage the download pool (the futures)
control_thread_pool = ControlDownloadPool()

# thread cleaning futures
futures_cleaner_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="futures_cleaner")
future_control_thread_pool = futures_cleaner_thread.submit(control_thread_pool.loop_clean_futures)
