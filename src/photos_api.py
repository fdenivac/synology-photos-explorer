"""
Encapsulate Synology Photos API

A fake API is set when login failed

"""

from typing import Optional
import logging
from synology_photos_api.photos import Photos
from synology_photos_api.exceptions import PhotosError

from synology_photos_api.exceptions import SynoBaseException

log = logging.getLogger(__name__)


class PhotosFakeEmpty:
    """
    A fake Synology Photos API used when connect fails
    """

    def isFake(self) -> bool:
        return True

    def count_albums(self, **kwargs) -> int:
        return 0

    def count_folders(self, folder_id: int = 0, team: bool = False) -> int:
        return 0

    def get_folder(self, folder_id: int = 0, team: bool = False, **kwargs) -> dict[str, object]:
        return {"id": 0}

    def count_photos_in_folder(self, folder_id: int, team: bool = False) -> int:
        return 0


class PhotosAPI:
    def __init__(self):
        self.api = PhotosFakeEmpty()
        self.connected = False
        self.exception = None

    def login(
        self,
        ip_address: str,
        port: str,
        username: str,
        password: str,
        secure: bool = False,
        cert_verify: bool = False,
        dsm_version: int = 7,
        debug: bool = True,
        otp_code: Optional[str] = None,
    ) -> bool:
        try:
            if self.connected:
                self.api.logout()
            self.connected = False
            self.api = Photos(
                ip_address,
                port,
                username,
                password,
                secure,
                cert_verify,
                dsm_version,
                debug,
                otp_code,
            )
            self.connected = True
        except Exception as _e:
            if isinstance(_e, SynoBaseException):
                self.exception = str(_e.error_message)
            else:
                self.exception = str(_e)
            self.api = PhotosFakeEmpty()
            return
        # now we are connected, but sometimes, a exception occurs on first api call with :
        #   (err 119 [Invalid session / SID not found.]) Error 119 - Invalid session / SID not found
        # so try to get user_info for test
        try:
            self.api.get_userinfo()
        except PhotosError as _e:
            self.connected = False
            self.exception = str(_e.error_message)
            self.api.logout()
            self.api = PhotosFakeEmpty()

    def is_connected(self) -> bool:
        return self.connected

    def set_fake(self):
        self.api = PhotosFakeEmpty()
        self.connected = True
        self.exception = None


synofoto = PhotosAPI()
