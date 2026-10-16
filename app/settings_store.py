"""Persistência das preferências do usuário em JSON (apps ocultos, nomes, links)."""

import json
import os
import threading
import uuid
from pathlib import Path

EDITABLE_FIELDS = ("name", "url", "icon", "hidden")


class SettingsStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = {"apps": {}, "custom": []}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[settings] não foi possível ler {self.path}: {exc!r}", flush=True)
            return
        self._data["apps"] = data.get("apps") or {}
        self._data["custom"] = data.get("custom") or []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    @staticmethod
    def _apply(target, changes):
        for key, value in changes.items():
            if key not in EDITABLE_FIELDS:
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                target.pop(key, None)
            else:
                target[key] = value.strip() if isinstance(value, str) else value

    # --- containers detectados ---
    def app_overrides(self, key):
        with self._lock:
            return dict(self._data["apps"].get(key, {}))

    def update_app(self, key, changes):
        with self._lock:
            current = self._data["apps"].setdefault(key, {})
            self._apply(current, changes)
            if not current:
                self._data["apps"].pop(key, None)
            self._save()

    def reset_app(self, key):
        with self._lock:
            if self._data["apps"].pop(key, None) is not None:
                self._save()

    # --- links manuais ---
    def custom_links(self):
        with self._lock:
            return [dict(c) for c in self._data["custom"]]

    def add_custom(self, name, url, icon=None):
        link = {"id": uuid.uuid4().hex[:10], "name": name.strip(), "url": url.strip()}
        if icon and icon.strip():
            link["icon"] = icon.strip()
        with self._lock:
            self._data["custom"].append(link)
            self._save()
        return link

    def update_custom(self, link_id, changes):
        with self._lock:
            for link in self._data["custom"]:
                if link["id"] == link_id:
                    # nome e URL são obrigatórios em links manuais
                    changes = {k: v for k, v in changes.items()
                               if k not in ("name", "url") or (isinstance(v, str) and v.strip())}
                    self._apply(link, changes)
                    self._save()
                    return True
        return False

    def delete_custom(self, link_id):
        with self._lock:
            before = len(self._data["custom"])
            self._data["custom"] = [c for c in self._data["custom"] if c["id"] != link_id]
            if len(self._data["custom"]) != before:
                self._save()
                return True
        return False
