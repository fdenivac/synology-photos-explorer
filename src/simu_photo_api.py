"""
    Simulate Synology Photos API

    Used for development
"""


fakeDatas = {
    (0, True): {
        "json": {"id": 0, "name": "Shared Root"},
        "folders": [(100, True)],
        "photos": [],
    },
    (0, False): {
        "json": {
            "id": 0,
            "name": "Personal Root",
        },
        "folders": [],
        "photos": [],
    },
    (100, True): {
        "json": {
            "id": 100,
            "name": "folder shared 1",
        },
        "folders": [],
        "photos": [(1000, True)],
    },
    (1000, True): {
        "json": {
            "id": 1000,
            "filename": "Photo 1.jpg",
            "filesize": 12501,
            "time": 1627071194,
            "additional": {"thumbnail": {"cache_key": "xxxx"}},
        },
        "folders": [],
        "photos": [],
    },
}


class PhotosFake:
    """
    A fake Synology Photos API used for development
    """

    def isFake(self) -> bool:
        return True

    def count_albums(self) -> int:
        return 0

    def count_folders(self, folder_id: int = 0, team: bool = False) -> int:
        return len(fakeDatas[(folder_id, team)]["folders"])

    def get_folder(
        self, folder_id: int = 0, team: bool = False, **kwargs
    ) -> dict[str, object]:
        return fakeDatas[(folder_id, team)]["json"]
        # return {
        #     "id": 0 if team else 1,
        #     "name": "Fake team root" if team else "Fake personal root",
        # }

    def count_photos_in_folder(self, folder_id: int, team: bool = False) -> int:
        return len(fakeDatas[(folder_id, team)]["photos"])
        return 0

    def photos_in_folder(
        self, folder_id: int, team: bool = False, **kwargs
    ) -> list[dict[str, object]]:
        photos = []
        raw_folders = fakeDatas[(folder_id, team)]
        for photo in raw_folders["photos"]:
            raw_photo = fakeDatas[photo]
            photos.append(raw_photo["json"])
        return photos

    def list_folders(
        self, folder_id: int, team: bool = False, **kwargs
    ) -> list[dict[str, object]]:
        folders = []
        raw_folders = fakeDatas[(folder_id, team)]
        for folder in raw_folders["folders"]:
            raw_folder = fakeDatas[folder]
            folders.append(raw_folder["json"])
        return folders

    def thumbnail_download(
        self,
        photo_id: int,
        size: str,
        cache_key: str | None = None,
        team: bool | None = None,
    ) -> bytes:
        return []
