from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context_engine import Candidate, lexical_relevance
from app.core.config import get_settings
from app.models import Event, Project, ProjectSource


class GoogleAPIError(RuntimeError):
    pass


class GoogleAuthUnavailable(GoogleAPIError):
    pass


class GoogleReader(Protocol):
    def drive_metadata(self, file_id: str) -> dict[str, Any]: ...
    def drive_text(self, file_id: str, metadata: dict[str, Any]) -> str | None: ...
    def calendar_events(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
    ) -> list[dict[str, Any]]: ...


class GoogleConnector:
    def __init__(
        self,
        *,
        access_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        token = access_token or settings.google_access_token
        if not token:
            token = self._refresh_access_token(transport=transport)

        self.drive_api_url = settings.google_drive_api_url.rstrip("/")
        self.calendar_api_url = settings.google_calendar_api_url.rstrip("/")
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "douglassnake-super-chat",
            },
            timeout=20.0,
            transport=transport,
        )

    @staticmethod
    def _refresh_access_token(
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> str:
        settings = get_settings()
        if not (
            settings.google_client_id
            and settings.google_client_secret
            and settings.google_refresh_token
        ):
            raise GoogleAuthUnavailable(
                "Google OAuth is not configured. Set GOOGLE_ACCESS_TOKEN or "
                "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REFRESH_TOKEN."
            )

        with httpx.Client(timeout=15.0, transport=transport) as client:
            response = client.post(
                settings.google_oauth_token_url,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": settings.google_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if response.status_code >= 400:
            raise GoogleAuthUnavailable(
                f"Google OAuth refresh failed ({response.status_code}): {response.text[:300]}"
            )
        token = str(response.json().get("access_token") or "").strip()
        if not token:
            raise GoogleAuthUnavailable("Google OAuth response did not contain an access_token")
        return token

    def close(self) -> None:
        self.client.close()

    def _get(self, url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        response = self.client.get(url, params=params)
        if response.status_code >= 400:
            raise GoogleAPIError(
                f"Google request failed ({response.status_code}): {response.text[:500]}"
            )
        return response

    def drive_metadata(self, file_id: str) -> dict[str, Any]:
        encoded = quote(file_id, safe="")
        response = self._get(
            f"{self.drive_api_url}/files/{encoded}",
            params={
                "fields": "id,name,mimeType,modifiedTime,webViewLink,size,md5Checksum,trashed",
                "supportsAllDrives": "true",
            },
        )
        return response.json()

    def drive_text(self, file_id: str, metadata: dict[str, Any]) -> str | None:
        mime_type = str(metadata.get("mimeType") or "")
        encoded = quote(file_id, safe="")
        if mime_type == "application/vnd.google-apps.document":
            response = self._get(
                f"{self.drive_api_url}/files/{encoded}/export",
                params={"mimeType": "text/plain"},
            )
            return response.text
        if mime_type.startswith("text/") or mime_type in {
            "application/json",
            "application/xml",
        }:
            response = self._get(
                f"{self.drive_api_url}/files/{encoded}",
                params={"alt": "media", "supportsAllDrives": "true"},
            )
            return response.text
        return None

    def calendar_events(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
    ) -> list[dict[str, Any]]:
        encoded = quote(calendar_id, safe="")
        response = self._get(
            f"{self.calendar_api_url}/calendars/{encoded}/events",
            params={
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 100,
                "timeMin": time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "timeMax": time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        return list(response.json().get("items", []))


def parse_google_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        if "T" not in value:
            parsed_date = date.fromisoformat(value)
            return datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
    except ValueError:
        return datetime.now(timezone.utc)


def _window_text(text: str, *, window_chars: int, overlap_chars: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if len(normalized) <= window_chars:
        return [normalized]
    step = max(1, window_chars - overlap_chars)
    windows: list[str] = []
    start = 0
    while start < len(normalized):
        chunk = normalized[start : start + window_chars].strip()
        if chunk:
            windows.append(chunk)
        if start + window_chars >= len(normalized):
            break
        start += step
    return windows


def _best_windows(
    text: str,
    query: str,
    *,
    limit: int,
    window_chars: int,
) -> list[str]:
    windows = _window_text(text, window_chars=window_chars, overlap_chars=min(400, window_chars // 4))
    if not windows:
        return []
    if not query.strip():
        return windows[:limit]
    ranked = sorted(
        enumerate(windows),
        key=lambda pair: (lexical_relevance(query, pair[1]), -pair[0]),
        reverse=True,
    )
    selected = sorted(ranked[:limit], key=lambda pair: pair[0])
    return [chunk for _, chunk in selected]


def drive_context_candidates(
    db: Session,
    project: Project,
    query: str,
    profile: str,
    reader: GoogleReader | None = None,
) -> tuple[list[Candidate], list[str]]:
    profile_config = {
        "minimal": (1, 1200),
        "standard": (2, 1800),
        "deep": (4, 2600),
    }
    max_windows, window_chars = profile_config.get(profile, profile_config["standard"])
    sources = list(
        db.scalars(
            select(ProjectSource).where(
                ProjectSource.project_id == project.id,
                ProjectSource.source_type == "google_drive",
                ProjectSource.is_active.is_(True),
            )
        ).all()
    )
    if not sources:
        return [], []

    owns_reader = reader is None
    try:
        connector: GoogleReader = reader or GoogleConnector()
    except GoogleAPIError as exc:
        return [], [str(exc)]

    candidates: list[Candidate] = []
    warnings: list[str] = []
    try:
        for source in sources:
            file_id = (source.external_id or "").strip()
            if not file_id:
                warnings.append(f"Google Drive source {source.id} has no file id")
                continue
            try:
                metadata = connector.drive_metadata(file_id)
                if metadata.get("trashed"):
                    warnings.append(f"Google Drive file {file_id} is trashed")
                    continue
                text = connector.drive_text(file_id, metadata)
            except GoogleAPIError as exc:
                warnings.append(f"Drive {file_id}: {exc}")
                continue

            title = str(metadata.get("name") or source.label or file_id)
            source_ref = str(metadata.get("webViewLink") or source.url or f"gdrive:{file_id}")
            timestamp = parse_google_datetime(metadata.get("modifiedTime"))
            if text:
                windows = _best_windows(
                    text,
                    f"{query} {title}",
                    limit=max_windows,
                    window_chars=window_chars,
                )
                for index, chunk in enumerate(windows, start=1):
                    candidates.append(
                        Candidate(
                            kind="document_excerpt",
                            title=f"{title} — trecho {index}",
                            content=chunk,
                            source_type="google_drive",
                            source_ref=source_ref,
                            timestamp=timestamp,
                            importance=0.92,
                        )
                    )
            else:
                candidates.append(
                    Candidate(
                        kind="fact",
                        title=title,
                        content=(
                            f"Documento Google Drive vinculado. MIME: {metadata.get('mimeType') or 'desconhecido'}. "
                            "O formato não possui extração textual no conector v1."
                        ),
                        source_type="google_drive",
                        source_ref=source_ref,
                        timestamp=timestamp,
                        importance=0.62,
                    )
                )
    finally:
        if owns_reader and isinstance(connector, GoogleConnector):
            connector.close()

    return candidates, warnings


def _calendar_event_payload(calendar_id: str, item: dict[str, Any]) -> dict[str, Any]:
    start = item.get("start") or {}
    end = item.get("end") or {}
    start_value = start.get("dateTime") or start.get("date")
    end_value = end.get("dateTime") or end.get("date")
    event_id = str(item.get("id") or "")
    summary = str(item.get("summary") or "Evento sem título")
    description = str(item.get("description") or "").strip()
    location = str(item.get("location") or "").strip()
    body_parts = []
    if description:
        body_parts.append(description)
    if location:
        body_parts.append(f"Local: {location}")
    if end_value:
        body_parts.append(f"Fim: {end_value}")
    return {
        "external_id": f"{calendar_id}:event:{event_id}",
        "title": summary[:255],
        "body": "\n".join(body_parts) or None,
        "occurred_at": parse_google_datetime(start_value),
        "url": item.get("htmlLink"),
        "metadata": {
            "calendar_id": calendar_id,
            "event_id": event_id,
            "status": item.get("status"),
            "start": start_value,
            "end": end_value,
            "location": location or None,
            "updated": item.get("updated"),
        },
    }


def _upsert_calendar_event(
    db: Session,
    project_id: UUID,
    payload: dict[str, Any],
) -> str:
    stmt = select(Event).where(
        Event.project_id == project_id,
        Event.source_type == "google_calendar",
        Event.event_type == "google_calendar.event",
        Event.external_id == payload["external_id"],
    )
    event = db.scalar(stmt)
    if event is None:
        db.add(
            Event(
                project_id=project_id,
                source_type="google_calendar",
                event_type="google_calendar.event",
                external_id=payload["external_id"],
                title=payload["title"],
                body=payload["body"],
                occurred_at=payload["occurred_at"],
                url=payload["url"],
                metadata_json=payload["metadata"],
            )
        )
        return "created"

    changed = any(
        [
            event.title != payload["title"],
            event.body != payload["body"],
            event.occurred_at != payload["occurred_at"],
            event.url != payload["url"],
            (event.metadata_json or {}) != payload["metadata"],
        ]
    )
    if not changed:
        return "skipped"
    event.title = payload["title"]
    event.body = payload["body"]
    event.occurred_at = payload["occurred_at"]
    event.url = payload["url"]
    event.metadata_json = payload["metadata"]
    return "updated"


def sync_project_google(
    db: Session,
    project: Project,
    reader: GoogleReader | None = None,
) -> dict[str, Any]:
    sources = list(
        db.scalars(
            select(ProjectSource).where(
                ProjectSource.project_id == project.id,
                ProjectSource.source_type.in_(["google_drive", "google_calendar"]),
                ProjectSource.is_active.is_(True),
            )
        ).all()
    )
    owns_reader = reader is None
    connector: GoogleReader = reader or GoogleConnector()
    now = datetime.now(timezone.utc)
    created = 0
    updated = 0
    skipped = 0
    drive_sources = 0
    calendar_sources = 0

    try:
        for source in sources:
            external_id = (source.external_id or "").strip()
            if not external_id:
                raise GoogleAPIError(f"Google source {source.id} has no external_id")

            if source.source_type == "google_drive":
                metadata = connector.drive_metadata(external_id)
                drive_sources += 1
                source.metadata_json = {
                    **(source.metadata_json or {}),
                    "name": metadata.get("name"),
                    "mime_type": metadata.get("mimeType"),
                    "modified_time": metadata.get("modifiedTime"),
                    "web_view_link": metadata.get("webViewLink"),
                    "trashed": bool(metadata.get("trashed")),
                    "last_synced_at": now.isoformat(),
                }
                source.updated_at = now
                continue

            calendar_sources += 1
            events = connector.calendar_events(
                external_id,
                time_min=now - timedelta(days=14),
                time_max=now + timedelta(days=120),
            )
            local_created = 0
            local_updated = 0
            local_skipped = 0
            for item in events:
                if not item.get("id"):
                    continue
                result = _upsert_calendar_event(
                    db,
                    project.id,
                    _calendar_event_payload(external_id, item),
                )
                local_created += int(result == "created")
                local_updated += int(result == "updated")
                local_skipped += int(result == "skipped")

            source.metadata_json = {
                **(source.metadata_json or {}),
                "last_synced_at": now.isoformat(),
                "last_sync": {
                    "events": len(events),
                    "created": local_created,
                    "updated": local_updated,
                    "skipped": local_skipped,
                },
            }
            source.updated_at = now
            created += local_created
            updated += local_updated
            skipped += local_skipped

        if sources:
            project.last_activity_at = now
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_reader and isinstance(connector, GoogleConnector):
            connector.close()

    return {
        "project_id": project.id,
        "source_count": len(sources),
        "drive_sources": drive_sources,
        "calendar_sources": calendar_sources,
        "created_events": created,
        "updated_events": updated,
        "skipped_events": skipped,
        "synced_at": now,
    }
