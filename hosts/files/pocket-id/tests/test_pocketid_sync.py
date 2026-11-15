import importlib.util
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location("sync", Path(__file__).parents[1] / "pocketid_sync.py")
sync_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_mod)

REAL_SPEC = yaml.safe_load((Path(__file__).parents[4] / "identity/pocket-id.yaml").read_text())


class FakeAPI:
    """In-memory stand-in for the parts of the Pocket ID API the sync uses."""

    def __init__(self):
        self.dry_run = False
        self.groups, self.users, self.clients = {}, {}, {}
        self.user_groups, self.client_groups = {}, {}
        self.writes = []

    def all(self, path):
        return list({"/user-groups": self.groups, "/users": self.users, "/oidc/clients": self.clients}[path].values())

    def get(self, path, **_):
        uid = path.split("/")[2]
        return [self.groups_by_id[g] for g in self.user_groups.get(uid, [])]

    @property
    def groups_by_id(self):
        return {g["id"]: g for g in self.groups.values()}

    def send(self, method, path, body=None):
        self.writes.append((method, path))
        if (method, path) == ("POST", "/user-groups"):
            g = {"id": f"g-{body['name']}", **body}; self.groups[body["name"]] = g; return g
        if (method, path) == ("POST", "/users"):
            u = {"id": f"u-{body['username']}", **body}; self.users[body["username"]] = u; return u
        if (method, path) == ("POST", "/oidc/clients"):
            self.clients[body["id"]] = dict(body); return body
        if method == "PUT" and path.endswith("/user-groups") and path.startswith("/users/"):
            self.user_groups[path.split("/")[2]] = body["userGroupIds"]; return {}
        if method == "PUT" and path.endswith("/allowed-user-groups"):
            self.client_groups[path.split("/")[3]] = body["userGroupIds"]; return {}
        if method == "PUT" and path.startswith("/oidc/clients/"):
            self.clients[path.split("/")[3]].update(body); return {}
        if method == "POST" and path.endswith("/secrets"):
            return {"secret": "s3cret-" + path.split("/")[3]}
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def stored(monkeypatch):
    store = {}
    monkeypatch.setattr(sync_mod, "sops_get", lambda k: store.get(k))
    monkeypatch.setattr(sync_mod, "sops_set", lambda k, v: store.__setitem__(k, v))
    return store


def test_first_run_creates_everything(stored):
    api = FakeAPI()
    sync_mod.sync(api, REAL_SPEC, log=lambda *_: None)
    assert set(api.groups) == {"admins", "family"}
    assert api.users["nikghodki"]["isAdmin"] is True
    assert api.user_groups["u-nikghodki"] == ["g-admins"]
    assert set(api.clients) == {c["id"] for c in REAL_SPEC["clients"]}
    assert all(v == ["g-admins"] for v in api.client_groups.values())
    assert set(stored) == {f"oidc_{c['id']}_secret" for c in REAL_SPEC["clients"]}


def test_second_run_writes_only_group_assignments(stored):
    api = FakeAPI()
    sync_mod.sync(api, REAL_SPEC, log=lambda *_: None)
    api.writes.clear()
    sync_mod.sync(api, REAL_SPEC, log=lambda *_: None)
    assert all(path.endswith("/allowed-user-groups") for _, path in api.writes)


def test_changed_callback_updates_client_without_new_secret(stored):
    api = FakeAPI()
    sync_mod.sync(api, REAL_SPEC, log=lambda *_: None)
    secrets_before = dict(stored)
    spec = yaml.safe_load(yaml.safe_dump(REAL_SPEC))
    spec["clients"][0]["callbackURLs"].append("https://example.nghodki.ai/cb")
    sync_mod.sync(api, spec, log=lambda *_: None)
    assert "https://example.nghodki.ai/cb" in api.clients[spec["clients"][0]["id"]]["callbackURLs"]
    assert stored == secrets_before


def test_every_client_is_https_and_restricted():
    for c in REAL_SPEC["clients"]:
        assert c["groups"], c["id"]
        assert all(u.startswith("https://") and ".nghodki.ai/" in u for u in c["callbackURLs"]), c["id"]
