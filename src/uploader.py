"""Upload the finished video to YouTube via the Data API v3.

First run opens a browser for OAuth consent and caches the token to
YOUTUBE_TOKEN_FILE, so later runs are non-interactive (good for cron).
"""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .script_generator import VideoScript

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_service(cfg: Config):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = cfg.path(cfg.youtube_token_file)
    secrets_path = cfg.path(cfg.youtube_client_secrets)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secrets_path.exists():
                raise RuntimeError(
                    f"YouTube client secrets not found at {secrets_path}. "
                    "Download OAuth client (Desktop app) JSON from Google Cloud "
                    "Console — see README 'YouTube setup'."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=creds)


def upload_video(video_path: Path, script: VideoScript, cfg: Config) -> str:
    from googleapiclient.http import MediaFileUpload

    youtube = _get_service(cfg)
    body = {
        "snippet": {
            "title": script.title[:100],
            "description": script.description[:5000],
            "tags": script.tags[:40],
            "categoryId": str(cfg.get("upload", "category_id", default="22")),
            "defaultLanguage": cfg.get("channel", "language_code", default="gu"),
            "defaultAudioLanguage": cfg.get("channel", "language_code", default="gu"),
        },
        "status": {
            "privacyStatus": cfg.get("upload", "privacy", default="private"),
            "selfDeclaredMadeForKids": cfg.get("upload", "made_for_kids", default=False),
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  upload {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"  ✓ https://youtu.be/{video_id} (privacy: {body['status']['privacyStatus']})")
    return video_id
