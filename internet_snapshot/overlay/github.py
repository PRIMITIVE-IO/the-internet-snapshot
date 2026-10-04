"""GitHub connector: the user, their organisations and repositories, grouped by owner."""

from __future__ import annotations

from collections import defaultdict

import httpx

from .base import AccountData, Connector, ProviderError
from .placement import Asset, Group

API = "https://api.github.com"


class GitHubConnector(Connector):
    provider = "github"
    label = "GitHub"
    anchor = "svc:github.com"
    scopes = ["read:user", "read:org", "repo"]
    authorize_url = "https://github.com/login/oauth/authorize"
    token_url = "https://github.com/login/oauth/access_token"
    docs = "https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user"

    async def fetch(self, client: httpx.AsyncClient, token: str, max_assets: int) -> AccountData:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        user = self.check(await client.get(f"{API}/user", headers=headers))
        if user.status_code != 200:
            raise ProviderError(f"GitHub /user returned {user.status_code}")
        u = user.json()
        warnings = []
        repos: list[dict] = []
        page = 1
        while len(repos) < max_assets and page <= 10:
            r = self.check(await client.get(
                f"{API}/user/repos", headers=headers,
                params={"per_page": min(100, max_assets), "page": page, "sort": "pushed",
                        "affiliation": "owner,collaborator,organization_member"}))
            if r.status_code != 200:
                warnings.append(f"repos: HTTP {r.status_code}")
                break
            batch = r.json()
            repos.extend(batch)
            if len(batch) < min(100, max_assets):
                break
            page += 1
        repos = repos[:max_assets]
        orgs_resp = self.check(await client.get(f"{API}/user/orgs", headers=headers, params={"per_page": 100}))
        orgs = orgs_resp.json() if orgs_resp.status_code == 200 else []
        if orgs_resp.status_code != 200:
            warnings.append(f"orgs: HTTP {orgs_resp.status_code} (needs read:org)")

        by_owner: dict[str, list[dict]] = defaultdict(list)
        for repo in repos:
            by_owner[repo["owner"]["login"]].append(repo)
        for o in orgs:
            by_owner.setdefault(o["login"], [])
        login = u["login"]
        owners = [login] + sorted(k for k in by_owner if k != login)
        groups = []
        for owner in owners:
            assets = [
                Asset(id=f"repo:{r['full_name']}", label=r["name"],
                      size=min(0.6, 0.18 + 0.04 * (r.get("stargazers_count") or 0) ** 0.25),
                      meta={"type": "repo", "full_name": r["full_name"], "private": r.get("private", False),
                            "stars": r.get("stargazers_count", 0), "language": r.get("language"),
                            "pushed_at": r.get("pushed_at"), "url": r.get("html_url")})
                for r in by_owner.get(owner, [])
            ]
            label = "Your repositories" if owner == login else owner
            groups.append(Group(key=f"owner:{owner}", label=label, assets=assets,
                                meta={"owner": owner, "is_user": owner == login,
                                      "url": f"https://github.com/{owner}"}))
        return AccountData(
            id=f"ov:github:{u['id']}", label=login,
            meta={"type": "user", "name": u.get("name"), "url": u.get("html_url"), "avatar": u.get("avatar_url"),
                  "public_repos": u.get("public_repos"), "private_repos": u.get("total_private_repos")},
            groups=groups, warnings=warnings)
