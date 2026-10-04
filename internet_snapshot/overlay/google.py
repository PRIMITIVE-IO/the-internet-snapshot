"""Google connector: Gmail labels, top-level Drive folders and files, and calendars.

Each product group is placed next to its own snapshot node (svc:gmail.com, svc:drive.google.com,
svc:calendar.google.com). The account node attaches to org:google.
"""

from __future__ import annotations

import asyncio

import httpx

from .base import AccountData, Connector, ProviderError
from .placement import Asset, Group

USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3/files"
CALENDAR = "https://www.googleapis.com/calendar/v3/users/me/calendarList"

SYSTEM_LABELS = ("INBOX", "STARRED", "IMPORTANT", "SENT", "DRAFT", "SPAM")


class GoogleConnector(Connector):
    provider = "google"
    label = "Google"
    anchor = "org:google"
    scopes = ["openid", "email", "profile",
              "https://www.googleapis.com/auth/gmail.labels",
              "https://www.googleapis.com/auth/drive.metadata.readonly",
              "https://www.googleapis.com/auth/calendar.readonly"]
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    docs = "https://developers.google.com/identity/protocols/oauth2"

    async def fetch(self, client: httpx.AsyncClient, token: str, max_assets: int) -> AccountData:
        headers = {"Authorization": f"Bearer {token}"}
        me = self.check(await client.get(USERINFO, headers=headers))
        if me.status_code != 200:
            raise ProviderError(f"Google userinfo returned {me.status_code}")
        info = me.json()
        warnings: list[str] = []
        gmail, drive, cal = await asyncio.gather(
            self._gmail(client, headers, max_assets, warnings),
            self._drive(client, headers, max_assets, warnings),
            self._calendar(client, headers, max_assets, warnings),
        )
        groups = [g for g in (gmail, drive, cal) if g is not None]
        return AccountData(id=f"ov:google:{info['sub']}", label=info.get("email") or info.get("name") or "Google account",
                           meta={"type": "google-account", "email": info.get("email"), "name": info.get("name"),
                                 "picture": info.get("picture")},
                           groups=groups, warnings=warnings)

    async def _gmail(self, client, headers, max_assets, warnings) -> Group | None:
        r = self.check(await client.get(f"{GMAIL}/labels", headers=headers))
        if r.status_code != 200:
            warnings.append(f"gmail: HTTP {r.status_code} (needs gmail.labels scope)")
            return None
        labels = r.json().get("labels", [])
        labels = [lb for lb in labels if lb.get("type") == "user" or lb["id"] in SYSTEM_LABELS]
        labels.sort(key=lambda lb: (lb.get("type") != "system", SYSTEM_LABELS.index(lb["id"])
                                    if lb["id"] in SYSTEM_LABELS else 99, lb["name"].lower()))
        labels = labels[:max_assets]
        sem = asyncio.Semaphore(8)

        async def detail(lb):
            async with sem:
                d = await client.get(f"{GMAIL}/labels/{lb['id']}", headers=headers)
                return d.json() if d.status_code == 200 else lb

        details = await asyncio.gather(*(detail(lb) for lb in labels[:40]))
        details += labels[40:]
        assets = [Asset(id=f"label:{d['id']}", label=d["name"].title() if d.get("type") == "system" else d["name"],
                        size=min(0.6, 0.18 + 0.03 * (d.get("messagesTotal") or 0) ** 0.25),
                        meta={"type": "gmail-label", "system": d.get("type") == "system",
                              "messages": d.get("messagesTotal"), "unread": d.get("messagesUnread")})
                  for d in details]
        return Group(key="gmail", label="Gmail", assets=assets, product_anchor="svc:gmail.com")

    async def _drive(self, client, headers, max_assets, warnings) -> Group | None:
        r = self.check(await client.get(DRIVE, headers=headers, params={
            "q": "'root' in parents and trashed = false", "pageSize": min(max_assets, 100),
            "orderBy": "folder,modifiedTime desc",
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink,shared)"}))
        if r.status_code != 200:
            warnings.append(f"drive: HTTP {r.status_code} (needs drive.metadata.readonly scope)")
            return None
        assets = []
        for f in r.json().get("files", [])[:max_assets]:
            folder = f.get("mimeType") == "application/vnd.google-apps.folder"
            assets.append(Asset(id=f"file:{f['id']}", label=f["name"], size=0.32 if folder else 0.2,
                                meta={"type": "drive-folder" if folder else "drive-file", "mime": f.get("mimeType"),
                                      "modified": f.get("modifiedTime"), "shared": f.get("shared"),
                                      "url": f.get("webViewLink")}))
        return Group(key="drive", label="Google Drive", assets=assets, product_anchor="svc:drive.google.com")

    async def _calendar(self, client, headers, max_assets, warnings) -> Group | None:
        r = self.check(await client.get(CALENDAR, headers=headers, params={"maxResults": min(max_assets, 250)}))
        if r.status_code != 200:
            warnings.append(f"calendar: HTTP {r.status_code} (needs calendar.readonly scope)")
            return None
        assets = [Asset(id=f"cal:{c['id']}", label=c.get("summaryOverride") or c.get("summary", c["id"]), size=0.22,
                        meta={"type": "calendar", "primary": c.get("primary", False),
                              "access": c.get("accessRole"), "color": c.get("backgroundColor")})
                  for c in r.json().get("items", [])[:max_assets]]
        return Group(key="calendar", label="Google Calendar", assets=assets, product_anchor="svc:calendar.google.com")
