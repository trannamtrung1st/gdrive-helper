from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.discovery import Resource

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_credentials(
    credentials_path: Path,
    token_path: Path,
) -> Credentials:
    creds: Credentials | None = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"OAuth client secrets not found at {credentials_path}. "
                "Download credentials.json from Google Cloud Console "
                "(APIs & Services > Credentials > OAuth 2.0 Client ID > Desktop app)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds


def build_drive_service(credentials: Credentials) -> Resource:
    return build("drive", "v3", credentials=credentials, cache_discovery=False)
