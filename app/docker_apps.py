"""Descoberta automática de containers e montagem dos atalhos."""

import os
import re
import threading
import time

import docker

ICON_BASE = os.environ.get("ICON_BASE", "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png")
CACHE_TTL = float(os.environ.get("DOCKER_CACHE_TTL", "5"))
LABEL = "homedash."

HTTPS_PORTS = {443, 8443, 9443}
WEB_PORT_PREFERENCE = (80, 8080, 443, 8443, 3000, 8000, 5000, 9000, 8081, 8888)

# porta = porta interna do container
KNOWN_APPS = {
    "jellyfin": {"name": "Jellyfin", "port": 8096},
    "emby": {"name": "Emby", "port": 8096},
    "plex": {"name": "Plex", "port": 32400, "path": "/web"},
    "jellyseerr": {"name": "Jellyseerr", "port": 5055},
    "overseerr": {"name": "Overseerr", "port": 5055},
    "sonarr": {"name": "Sonarr", "port": 8989},
    "radarr": {"name": "Radarr", "port": 7878},
    "lidarr": {"name": "Lidarr", "port": 8686},
    "readarr": {"name": "Readarr", "port": 8787},
    "prowlarr": {"name": "Prowlarr", "port": 9696},
    "bazarr": {"name": "Bazarr", "port": 6767},
    "jackett": {"name": "Jackett", "port": 9117},
    "tautulli": {"name": "Tautulli", "port": 8181},
    "qbittorrent": {"name": "qBittorrent", "port": 8080},
    "transmission": {"name": "Transmission", "port": 9091},
    "deluge": {"name": "Deluge", "port": 8112},
    "sabnzbd": {"name": "SABnzbd", "port": 8080},
    "nzbget": {"name": "NZBGet", "port": 6789},
    "portainer": {"name": "Portainer", "port": 9443, "scheme": "https"},
    "homeassistant": {"name": "Home Assistant", "port": 8123, "icon": "home-assistant"},
    "home-assistant": {"name": "Home Assistant", "port": 8123, "icon": "home-assistant"},
    "pihole": {"name": "Pi-hole", "port": 80, "path": "/admin", "icon": "pi-hole"},
    "adguardhome": {"name": "AdGuard Home", "port": 3000, "icon": "adguard-home"},
    "nextcloud": {"name": "Nextcloud", "port": 80},
    "immich": {"name": "Immich", "port": 2283},
    "photoprism": {"name": "PhotoPrism", "port": 2342},
    "uptime-kuma": {"name": "Uptime Kuma", "port": 3001},
    "grafana": {"name": "Grafana", "port": 3000},
    "prometheus": {"name": "Prometheus", "port": 9090},
    "nginx-proxy-manager": {"name": "Nginx Proxy Manager", "port": 81},
    "syncthing": {"name": "Syncthing", "port": 8384},
    "vaultwarden": {"name": "Vaultwarden", "port": 80},
    "filebrowser": {"name": "File Browser", "port": 80},
    "heimdall": {"name": "Heimdall", "port": 80},
    "code-server": {"name": "code-server", "port": 8443},
    "navidrome": {"name": "Navidrome", "port": 4533},
    "paperless-ngx": {"name": "Paperless-ngx", "port": 8000},
    "gitea": {"name": "Gitea", "port": 3000},
    "forgejo": {"name": "Forgejo", "port": 3000},
    "node-red": {"name": "Node-RED", "port": 1880},
    "frigate": {"name": "Frigate", "port": 5000},
    "duplicati": {"name": "Duplicati", "port": 8200},
    "calibre-web": {"name": "Calibre-Web", "port": 8083},
    "audiobookshelf": {"name": "Audiobookshelf", "port": 80},
    "kavita": {"name": "Kavita", "port": 5000},
    "netdata": {"name": "Netdata", "port": 19999},
    "dozzle": {"name": "Dozzle", "port": 8080},
    "glances": {"name": "Glances", "port": 61208},
    "cockpit": {"name": "Cockpit", "port": 9090, "scheme": "https"},
}


def image_slug(image):
    """'lscr.io/linuxserver/jellyfin:latest' -> 'jellyfin'"""
    name = (image or "").split("@")[0].rsplit("/", 1)[-1]
    return name.split(":")[0].lower()


def match_known(text):
    if text in KNOWN_APPS:
        return text, KNOWN_APPS[text]
    best = None
    for key in KNOWN_APPS:
        if key in text and (best is None or len(key) > len(best)):
            best = key
    return (best, KNOWN_APPS[best]) if best else (None, {})


def prettify(name):
    return " ".join(p[:1].upper() + p[1:] for p in re.split(r"[-_.]+", name) if p) or name


def icon_url(icon):
    if not icon:
        return None
    if icon.startswith(("http://", "https://", "/", "data:")):
        return icon
    return f"{ICON_BASE}/{icon}.png"


def pick_port(published, known, strict=False):
    """published: {porta_interna: porta_no_host}. Retorna (interna, host).
    strict: não cai no fallback de "qualquer porta publicada"."""
    if not published:
        return None, None
    known_port = known.get("port")
    if known_port in published:
        return known_port, published[known_port]
    for port in WEB_PORT_PREFERENCE:
        if port in published:
            return port, published[port]
    if strict:
        return None, None
    private = min(published, key=lambda p: published[p])
    return private, published[private]


class DockerApps:
    def __init__(self, store):
        self.store = store
        self._client = None
        self._lock = threading.Lock()
        self._cache = ([], None)
        self._cache_time = 0.0
        self._exposed_cache = {}

    def _get_client(self):
        if self._client is None:
            self._client = docker.from_env(timeout=5)
        return self._client

    def _exposed_ports(self, client, container_id):
        if container_id not in self._exposed_cache:
            try:
                info = client.api.inspect_container(container_id)
                exposed = (info.get("Config") or {}).get("ExposedPorts") or {}
                self._exposed_cache[container_id] = [
                    int(p.split("/")[0]) for p in exposed if p.endswith("/tcp")
                ]
            except Exception:
                return []
        return self._exposed_cache[container_id]

    def _fetch(self):
        try:
            client = self._get_client()
            raw = client.api.containers(all=True)
        except Exception as exc:
            self._client = None
            return [], f"Não foi possível acessar o Docker: {exc}"

        # 1ª passada: portas publicadas de cada container
        published_by_id = {}
        id_by_name = {}
        for c in raw:
            published = {}
            for p in c.get("Ports") or []:
                if p.get("Type") == "tcp" and p.get("PublicPort"):
                    published.setdefault(p["PrivatePort"], p["PublicPort"])
            published_by_id[c["Id"]] = published
            for n in c.get("Names") or []:
                id_by_name[n.lstrip("/")] = c["Id"]

        def resolve_parent(network_mode):
            ref = network_mode.split(":", 1)[1]
            if ref in id_by_name:
                return id_by_name[ref]
            return next((cid for cid in published_by_id if cid.startswith(ref)), None)

        # Containers com network_mode "container:X" (ex.: qBittorrent atrás do
        # Gluetun) não publicam portas: elas aparecem no container X. O filho
        # reivindica as portas dele que estão publicadas no pai.
        borrowed = {}   # id do filho -> {interna: host}
        lent = {}       # id do pai -> portas internas cedidas
        for c in raw:
            network_mode = (c.get("HostConfig") or {}).get("NetworkMode", "")
            if not network_mode.startswith("container:"):
                continue
            parent = resolve_parent(network_mode)
            if not parent:
                continue
            name = (c.get("Names") or [""])[0].lstrip("/")
            _, known = match_known(image_slug(c.get("Image", "")))
            if not known:
                _, known = match_known(name.lower())
            wanted = set(self._exposed_ports(client, c["Id"]))
            if known.get("port"):
                wanted.add(known["port"])
            parent_pub = published_by_id.get(parent, {})
            claim = {p: parent_pub[p] for p in wanted if p in parent_pub}
            if claim:
                borrowed[c["Id"]] = claim
                lent.setdefault(parent, set()).update(claim)

        containers = []
        for c in raw:
            labels = c.get("Labels") or {}
            if labels.get(LABEL + "self") == "true":
                continue
            name = (c.get("Names") or ["/desconhecido"])[0].lstrip("/")
            image = c.get("Image", "")
            slug = image_slug(image)
            known_key, known = match_known(slug)
            if not known_key:
                known_key, known = match_known(name.lower())

            published = {p: h for p, h in published_by_id[c["Id"]].items()
                         if p not in lent.get(c["Id"], ())}
            published.update(borrowed.get(c["Id"], {}))
            network_mode = (c.get("HostConfig") or {}).get("NetworkMode", "")
            if network_mode == "host":
                for port in self._exposed_ports(client, c["Id"]):
                    published.setdefault(port, port)
                if known.get("port"):
                    published.setdefault(known["port"], known["port"])

            private, port = pick_port(published, known, strict=c["Id"] in lent)
            if labels.get(LABEL + "port", "").isdigit():
                port = int(labels[LABEL + "port"])
                private = port
            scheme = labels.get(LABEL + "scheme") or known.get("scheme") or (
                "https" if private in HTTPS_PORTS else "http")

            containers.append({
                "key": name,
                "container": True,
                "auto_name": labels.get(LABEL + "name") or known.get("name") or prettify(name),
                "auto_icon": labels.get(LABEL + "icon") or known.get("icon") or known_key or slug,
                "auto_url": labels.get(LABEL + "url"),
                "label_hidden": labels.get(LABEL + "hide") == "true",
                "image": image,
                "state": c.get("State"),
                "status": c.get("Status"),
                "port": port,
                "scheme": scheme,
                "path": labels.get(LABEL + "path") or known.get("path", ""),
                "ports": sorted(set(published.values())),
                "network_mode": network_mode,
                "project": labels.get("com.docker.compose.project"),
            })

        live_ids = {c["Id"] for c in raw}
        self._exposed_cache = {k: v for k, v in self._exposed_cache.items() if k in live_ids}
        containers.sort(key=lambda c: c["auto_name"].lower())
        return containers, None

    def list(self):
        with self._lock:
            if time.monotonic() - self._cache_time > CACHE_TTL:
                self._cache = self._fetch()
                self._cache_time = time.monotonic()
            containers, error = self._cache

        apps = []
        for c in containers:
            ov = self.store.app_overrides(c["key"])
            icon = ov.get("icon") or c["auto_icon"]
            url = ov.get("url") or c["auto_url"]
            apps.append({
                **{k: v for k, v in c.items() if k != "label_hidden"},
                "name": ov.get("name") or c["auto_name"],
                "url": url,
                "icon": icon,
                "icon_url": icon_url(icon),
                "hidden": ov.get("hidden", c["label_hidden"]),
                "overrides": ov,
                "has_web": bool(url or c["port"]),
            })

        for link in self.store.custom_links():
            icon = link.get("icon") or re.sub(r"[^a-z0-9]+", "-", link["name"].lower()).strip("-")
            apps.append({
                "key": "custom:" + link["id"],
                "container": False,
                "name": link["name"],
                "url": link["url"],
                "icon": icon,
                "icon_url": icon_url(icon),
                "hidden": link.get("hidden", False),
                "overrides": link,
                "has_web": True,
                "state": None,
            })
        return {"apps": apps, "docker_error": error}
