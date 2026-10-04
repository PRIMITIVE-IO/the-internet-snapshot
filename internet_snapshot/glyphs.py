"""Function glyphs: Lucide icon names that hint at what is at a node or endpoint.

Names are validated against the Lucide package at build time; unknown names fall back to "circle".
"""

from __future__ import annotations

import re

FALLBACK = "circle"

CATEGORY_GLYPH = {
    "search": "search", "reference": "book-open", "education": "graduation-cap", "maps": "map",
    "social": "users", "messaging": "message-circle", "email": "mail", "video-calls": "video", "forums": "messages-square",
    "video": "play", "music": "music", "gaming": "gamepad-2", "news": "newspaper",
    "shopping": "shopping-cart", "payments": "credit-card", "banking": "landmark", "crypto": "bitcoin", "travel": "plane",
    "ads": "megaphone", "analytics": "chart-line",
    "cloud": "cloud", "cdn": "zap", "dns": "globe", "identity": "shield",
    "code": "git-branch", "devtools": "wrench", "ai": "sparkles", "apis": "plug",
    "productivity": "file-text", "collaboration": "users-round", "storage": "hard-drive", "business": "briefcase",
    "design": "palette",
    "government": "building-2", "health": "heart-pulse", "nonprofit": "hand-heart",
    "web": "globe", "adult": "eye-off",
}

REALM_GLYPH = {
    "knowledge": "book-open", "communication": "message-circle", "media": "play", "commerce": "shopping-cart",
    "adtech": "megaphone", "cloud": "cloud", "developer": "code", "work": "briefcase", "society": "landmark",
    "longtail": "globe",
}

ROLE_GLYPH = {
    "tier1": "waypoints", "transit": "cable", "access": "router", "cloud": "cloud", "cdn": "zap", "content": "server",
    "hosting": "server", "enterprise": "building", "education": "graduation-cap", "government": "landmark",
    "ixp": "network", "region": "earth",
}

KIND_GLYPH = {"realm": "orbit", "category": "layout-grid", "org": "building-2", "host": "globe", "api": "plug",
              "api-group": "braces", "operation": "arrow-right-left", "surface": "layers", "site": "orbit",
              "universe": "orbit", "ecosystem": "boxes", "language": "code", "cluster": "shapes", "owner": "user",
              "repo": "book-marked"}

# Ordered keyword rules for endpoints, API groups, hosts and repo purposes. First match wins.
_RULES: list[tuple[str, str]] = [
    (r"\bmail|gmail|inbox|smtp|imap", "mail"),
    (r"calendar|event", "calendar"),
    (r"\bdrive\b|storage|bucket|blob|files?\b|upload", "hard-drive"),
    (r"folder|director", "folder"),
    (r"\bdocs?\b|document", "file-text"),
    (r"sheet|spreadsheet", "sheet"),
    (r"slide|presentation", "presentation"),
    (r"\bforms?\b", "clipboard-list"),
    (r"photo|image|avatar|picture|vision", "image"),
    (r"video|youtube|stream|meet\b|camera", "video"),
    (r"music|audio|speech|voice|podcast", "headphones"),
    (r"\bmaps?\b|places|route|geo|location|earth|navigation", "map-pin"),
    (r"search|query|find", "search"),
    (r"translat|language", "languages"),
    (r"\bchat|messag|conversation|comment|discussion", "message-circle"),
    (r"notification|alert|bell", "bell"),
    (r"pull|merge", "git-pull-request"),
    (r"commit", "git-commit-horizontal"),
    (r"branch|\bgit\b|\brefs?\b|tree", "git-branch"),
    (r"issue|bug|ticket", "circle-dot"),
    (r"action|workflow|pipeline|\bci\b|build|runner", "workflow"),
    (r"release|tag\b|tags", "tag"),
    (r"package|registry|artifact|container|ghcr|docker", "package"),
    (r"secret|key|token|credential|oauth|login|auth|identity|iam|sso", "key-round"),
    (r"security|scanning|advisor|vulnerab|dependabot|kms|protect", "shield-check"),
    (r"billing|payment|invoice|checkout|wallet|pay\b|subscription", "credit-card"),
    (r"\bads?\b|advert|adsense|doubleclick|campaign|marketing", "megaphone"),
    (r"analytic|metric|insight|report|stat|monitor|logging|trace", "chart-line"),
    (r"user|profile|people|contact|member|account", "user"),
    (r"\borgs?\b|organi|team|enterprise|group", "building-2"),
    (r"project|kanban|task|todo", "kanban"),
    (r"wiki|book|knowledge|learn|course|classroom|education|tutorial|awesome|interview", "book-open"),
    (r"deploy|pages|hosting|site\b|website", "rocket"),
    (r"codespace|editor|\bide\b|vim|emacs|vscode|terminal|shell|cli\b|command", "terminal"),
    (r"copilot|\bai\b|gemini|model|machine.?learning|deep.?learning|neural|llm|gpt|agent|ml\b|nlp|dialogflow", "sparkles"),
    (r"database|sql|\bdb\b|bigquery|spanner|firestore|datastore|bigtable|redis|cache", "database"),
    (r"compute|instance|\bvm\b|kubernetes|container|cluster|serverless|functions?\b|\brun\b", "cpu"),
    (r"network|dns|cdn|proxy|load.?balanc|vpc|router|http", "network"),
    (r"queue|pubsub|pub/sub|event|webhook|hook", "webhook"),
    (r"mobile|android|ios\b|iphone|flutter|react.?native|app store|play store", "smartphone"),
    (r"game|engine|unity|godot|unreal", "gamepad-2"),
    (r"\bui\b|component|css|design|theme|icon|font|frontend", "palette"),
    (r"framework|web|server|api\b|rest|graphql|http", "braces"),
    (r"test|lint|format|quality", "flask-conical"),
    (r"reaction|emoji|star", "star"),
    (r"license|code.?of.?conduct|gitignore|markdown|meta\b", "scroll-text"),
    (r"crypto|blockchain|bitcoin|ethereum|wallet", "bitcoin"),
    (r"shop|commerce|store|cart|product", "shopping-cart"),
    (r"health|fitness|medical", "heart-pulse"),
    (r"news|feed|blog|rss", "newspaper"),
    (r"setting|config|admin|manage", "settings"),
    (r"download|codeload|raw\b|content|cdn|static|assets", "download"),
]
_COMPILED = [(re.compile(p, re.I), g) for p, g in _RULES]


def glyph_for_text(*texts: str | None, default: str | None = None) -> str | None:
    blob = " ".join(t for t in texts if t)
    for rx, g in _COMPILED:
        if rx.search(blob):
            return g
    return default


def all_glyph_names() -> set[str]:
    return set(CATEGORY_GLYPH.values()) | set(ROLE_GLYPH.values()) | set(REALM_GLYPH.values()) | set(KIND_GLYPH.values()) | \
        {g for _, g in _RULES} | {FALLBACK}
