# gdrive-helper

Batch upload images from a local folder to Google Drive. Built for large folders (~2000+ images) with concurrent resumable uploads, retries, and checkpoint-based resume.

## Features

- Parallel uploads (default 6 workers; tune with `--workers`)
- Resumable uploads with automatic retry on rate limits and transient errors
- Checkpoint file so interrupted runs can resume without re-uploading
- Recursive scan for common image formats (jpg, png, webp, heic, etc.) with optional `--recursive`

## Setup

### 1. Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or pick an existing one)
3. Enable **Google Drive API**
4. Configure OAuth consent screen (External is fine for personal use)
5. Create **OAuth 2.0 Client ID** → Application type: **Desktop app**
6. Download the JSON and save it as `credentials.json` in this project directory

### 2. Install

```bash
cd gdrive-helper
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

Upload into a new Drive folder:

```bash
gdrive-upload /path/to/images --drive-folder-name "Vacation Photos 2024"
```

Upload into an existing Drive folder (get the ID from the folder URL):

```bash
gdrive-upload /path/to/images --drive-folder-id "1AbCdEfGhIjKlMnOpQrStUvWxYz"
```

### Options

| Flag | Description |
|------|-------------|
| `--workers N` | Concurrent uploads (default: 6). Use 4–8 for large batches. |
| `--recursive` | Also upload images in subfolders (default: top-level folder only) |
| `--parent-folder-id ID` | Create the new folder inside this Drive folder |
| `--checkpoint PATH` | Custom checkpoint file for resume |
| `--no-checkpoint` | Disable resume tracking |

On first run, a browser window opens for Google sign-in. A `token.json` file is saved for later runs.

### Resume after interruption

If the process stops (network error, Ctrl+C, etc.), run the same command again. Completed files are skipped using `.gdrive-upload.checkpoint.json` in the source folder.

### Example: ~2000 images

```bash
gdrive-upload ~/Pictures/export --drive-folder-name "Archive" --workers 8
```

## Notes

- The `drive.file` scope only allows access to files created by this app (uploaded files and folders it creates).
- Google Drive API has per-user rate limits. If you see many 429 errors, lower `--workers` to 4.
- Checkpoint files are gitignored; do not commit `credentials.json` or `token.json`.
