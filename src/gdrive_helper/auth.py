from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.discovery import Resource

OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
SERVICE_ACCOUNT_SCOPES = ["https://www.googleapis.com/auth/drive"]


def is_service_account(credentials_path: Path) -> bool:
    info = json.loads(credentials_path.read_text())
    return info.get("type") == "service_account"


def service_account_email(credentials_path: Path) -> str | None:
    info = json.loads(credentials_path.read_text())
    if info.get("type") != "service_account":
        return None
    return info.get("client_email")


def get_credentials(
    credentials_path: Path,
    token_path: Path,
) -> Credentials:
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Credentials not found at {credentials_path}. "
            "Use a service account JSON or OAuth Desktop client secrets from Google Cloud Console."
        )

    if is_service_account(credentials_path):
        return service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=SERVICE_ACCOUNT_SCOPES,
        )

    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), OAUTH_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), OAUTH_SCOPES)
        creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    return creds


def build_drive_service(credentials: Credentials) -> Resource:
    return build("drive", "v3", credentials=credentials, cache_discovery=False)
