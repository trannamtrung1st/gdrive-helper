from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gdrive_helper.auth import (
    build_drive_service,
    get_credentials,
    is_service_account,
    service_account_email,
)
from gdrive_helper.uploader import create_drive_folder, upload_images


def _default_checkpoint(source: Path) -> Path:
    return source.resolve() / ".gdrive-upload.checkpoint.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload all images in a folder to Google Drive (optimized for large batches).",
    )
    parser.add_argument(
        "folder",
        type=Path,
        help="Local folder containing images to upload",
    )
    parser.add_argument(
        "--drive-folder-id",
        help="Existing Google Drive folder ID to upload into",
    )
    parser.add_argument(
        "--drive-folder-name",
        help="Create a new folder in Drive with this name (uses My Drive root unless --parent-folder-id is set)",
    )
    parser.add_argument(
        "--parent-folder-id",
        help="Parent Drive folder ID when creating a new folder with --drive-folder-name",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path("credentials.json"),
        help="Path to credentials JSON — service account or OAuth Desktop (default: credentials.json)",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=Path("token.json"),
        help="Path to store OAuth token (default: token.json)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Concurrent upload workers (default: 6; try 4-8 for ~2000 files)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only upload images in the top-level folder",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        help="Checkpoint file for resume (default: <folder>/.gdrive-upload.checkpoint.json)",
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Disable checkpoint/resume tracking",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.folder.resolve()

    if not source.is_dir():
        print(f"Error: folder does not exist: {source}", file=sys.stderr)
        return 1

    if not args.drive_folder_id and not args.drive_folder_name:
        print(
            "Error: provide --drive-folder-id or --drive-folder-name",
            file=sys.stderr,
        )
        return 1

    if args.workers < 1:
        print("Error: --workers must be at least 1", file=sys.stderr)
        return 1

    if is_service_account(args.credentials):
        email = service_account_email(args.credentials)
        print(
            f"Using service account: {email}\n"
            "Ensure the Drive folder is shared with this email (Editor access)."
        )

    creds = get_credentials(args.credentials, args.token)
    service = build_drive_service(creds)

    drive_folder_id = args.drive_folder_id
    if not drive_folder_id:
        drive_folder_id = create_drive_folder(
            service,
            args.drive_folder_name,
            parent_id=args.parent_folder_id,
        )
        print(f"Created Drive folder '{args.drive_folder_name}' (id: {drive_folder_id})")

    checkpoint_path = None
    if not args.no_checkpoint:
        checkpoint_path = args.checkpoint or _default_checkpoint(source)

    result = upload_images(
        creds,
        source,
        drive_folder_id,
        workers=args.workers,
        recursive=not args.no_recursive,
        checkpoint_path=checkpoint_path,
    )

    print()
    print(f"Uploaded: {result.uploaded}")
    print(f"Skipped (already done): {result.skipped}")
    print(f"Failed: {result.failed}")

    if result.errors:
        print("\nFailures:")
        for path, message in result.errors[:20]:
            print(f"  {path}: {message}")
        if len(result.errors) > 20:
            print(f"  ... and {len(result.errors) - 20} more")

    if checkpoint_path and result.failed:
        print(f"\nRe-run the same command to retry failed uploads (checkpoint: {checkpoint_path})")

    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
