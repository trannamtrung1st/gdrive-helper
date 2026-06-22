from __future__ import annotations

import json
import mimetypes
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from tqdm import tqdm

from gdrive_helper.auth import SERVICE_ACCOUNT_PERSONAL_DRIVE_ERROR, build_drive_service

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
    ".avif",
}

_thread_local = threading.local()


def _get_thread_service(credentials: Credentials) -> Resource:
    if not hasattr(_thread_local, "service"):
        _thread_local.service = build_drive_service(credentials)
    return _thread_local.service


def find_images(folder: Path, recursive: bool = False) -> list[Path]:
    folder = folder.resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder}")

    if recursive:
        candidates = folder.rglob("*")
    else:
        candidates = folder.iterdir()

    images = [
        path
        for path in candidates
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(images)


def create_drive_folder(service: Resource, name: str, parent_id: str | None = None) -> str:
    metadata: dict[str, object] = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def get_drive_folder_info(service: Resource, folder_id: str) -> dict:
    return (
        service.files()
        .get(
            fileId=folder_id,
            fields="id,name,driveId",
            supportsAllDrives=True,
        )
        .execute()
    )


def is_shared_drive_folder(folder_info: dict) -> bool:
    return bool(folder_info.get("driveId"))


def validate_service_account_target(service: Resource, folder_id: str) -> None:
    folder = get_drive_folder_info(service, folder_id)
    if not is_shared_drive_folder(folder):
        raise RuntimeError(SERVICE_ACCOUNT_PERSONAL_DRIVE_ERROR)


def _format_upload_error(exc: Exception) -> str:
    message = str(exc)
    if "storageQuotaExceeded" in message or "do not have storage quota" in message:
        return SERVICE_ACCOUNT_PERSONAL_DRIVE_ERROR
    return message


@dataclass
class Checkpoint:
    source_folder: str
    drive_folder_id: str
    completed: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Checkpoint | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return cls(
            source_folder=data["source_folder"],
            drive_folder_id=data["drive_folder_id"],
            completed=data.get("completed", {}),
            failed=data.get("failed", {}),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "source_folder": self.source_folder,
                    "drive_folder_id": self.drive_folder_id,
                    "completed": self.completed,
                    "failed": self.failed,
                },
                indent=2,
            )
        )


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def _upload_with_retry(
    service: Resource,
    file_path: Path,
    drive_folder_id: str,
    max_retries: int = 5,
) -> str:
    metadata = {"name": file_path.name, "parents": [drive_folder_id]}
    media = MediaFileUpload(
        str(file_path),
        mimetype=_guess_mime(file_path),
        resumable=True,
        chunksize=8 * 1024 * 1024,
    )

    backoff = 2.0
    last_error: Exception | None = None

    for attempt in range(max_retries):
        request = service.files().create(body=metadata, media_body=media, fields="id")
        try:
            response = None
            while response is None:
                _, response = request.next_chunk()
            return response["id"]
        except HttpError as exc:
            last_error = exc
            status = exc.resp.status if exc.resp else None
            retryable = status in {429, 500, 502, 503, 504}
            if not retryable or attempt == max_retries - 1:
                raise
        except (TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == max_retries - 1:
                raise

        time.sleep(backoff)
        backoff = min(backoff * 2, 60.0)

    raise RuntimeError(f"Upload failed for {file_path}: {last_error}")


@dataclass
class UploadResult:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def upload_images(
    credentials: Credentials,
    source_folder: Path,
    drive_folder_id: str,
    *,
    workers: int = 6,
    recursive: bool = False,
    checkpoint_path: Path | None = None,
    on_progress: Callable[[], None] | None = None,
) -> UploadResult:
    source_folder = source_folder.resolve()
    images = find_images(source_folder, recursive=recursive)
    checkpoint = Checkpoint(str(source_folder), drive_folder_id)

    if checkpoint_path and (existing := Checkpoint.load(checkpoint_path)):
        if (
            existing.source_folder == checkpoint.source_folder
            and existing.drive_folder_id == checkpoint.drive_folder_id
        ):
            checkpoint = existing

    pending = [path for path in images if str(path) not in checkpoint.completed]
    result = UploadResult(skipped=len(images) - len(pending))

    if not pending:
        return result

    lock = threading.Lock()

    def upload_one(file_path: Path) -> tuple[Path, str | None, str | None]:
        try:
            service = _get_thread_service(credentials)
            file_id = _upload_with_retry(service, file_path, drive_folder_id)
            return file_path, file_id, None
        except Exception as exc:
            return file_path, None, _format_upload_error(exc)

    abort_error: str | None = None

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(upload_one, path): path for path in pending}

        with tqdm(total=len(pending), desc="Uploading", unit="file") as bar:
            for future in as_completed(futures):
                if abort_error is not None:
                    future.cancel()
                    continue

                file_path, file_id, error = future.result()

                with lock:
                    key = str(file_path)
                    if file_id:
                        checkpoint.completed[key] = file_id
                        checkpoint.failed.pop(key, None)
                        result.uploaded += 1
                    else:
                        checkpoint.failed[key] = error or "unknown error"
                        result.failed += 1
                        result.errors.append((key, checkpoint.failed[key]))

                        if "Service accounts cannot upload to personal Google Drive" in (
                            checkpoint.failed[key]
                        ):
                            abort_error = checkpoint.failed[key]

                    if checkpoint_path:
                        checkpoint.save(checkpoint_path)

                bar.set_postfix(ok=result.uploaded, failed=result.failed, refresh=False)
                bar.update(1)
                if on_progress:
                    on_progress()

                if abort_error is not None:
                    for pending_future in futures:
                        pending_future.cancel()
                    break

    if abort_error and len(result.errors) == 1:
        raise RuntimeError(abort_error)

    return result
