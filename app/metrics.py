"""Coleta de métricas do host (CPU, temperatura, RAM, disco, rede).

Dentro do container, o /proc do host é montado em HOST_PROC e a raiz do host
em HOST_ROOT. Sem esses mounts (ex.: rodando localmente), usa o /proc local.
"""

import os
import platform
import re
import socket
import threading
import time
from collections import deque

import psutil

HOST_PROC = os.environ.get("HOST_PROC", "/host/proc")
HOST_ROOT = os.environ.get("HOST_ROOT", "/hostfs")
INTERVAL = float(os.environ.get("METRICS_INTERVAL", "2"))
HISTORY_SIZE = int(os.environ.get("HISTORY_SIZE", "90"))

HAS_HOST_PROC = os.path.isfile(os.path.join(HOST_PROC, "stat"))
PROC = HOST_PROC if HAS_HOST_PROC else "/proc"
if HAS_HOST_PROC:
    psutil.PROCFS_PATH = HOST_PROC

DISK_FSTYPES = {
    "ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs",
    "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "bcachefs",
}
IGNORED_MOUNT_PREFIXES = ("/boot", "/snap", "/var/lib/docker", "/run", "/var/snap")
IGNORED_IFACE_PREFIXES = ("lo", "docker", "veth", "br-", "virbr", "vnet", "cni", "flannel", "cali")

CPU_SENSOR_PRIORITY = (
    "coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal",
    "soc_thermal", "x86_pkg_temp", "acpitz",
)


def _read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _unescape_mount(path):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def _host_info():
    hostname = (_read_file(os.path.join(HOST_ROOT, "etc/hostname")) or "").strip()
    os_name = None
    for line in (_read_file(os.path.join(HOST_ROOT, "etc/os-release")) or "").splitlines():
        if line.startswith("PRETTY_NAME="):
            os_name = line.split("=", 1)[1].strip().strip('"')
    return {
        "hostname": hostname or socket.gethostname(),
        "os": os_name or platform.system(),
        "kernel": platform.release(),
        "arch": platform.machine(),
    }


def _cpu_model():
    lines = (_read_file(os.path.join(PROC, "cpuinfo")) or "").splitlines()
    for key in ("model name", "hardware", "model"):
        for line in lines:
            if line.lower().startswith(key) and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value and not value.isdigit():
                    return value
    return platform.processor() or None


def _temperatures():
    if not hasattr(psutil, "sensors_temperatures"):
        return None, []
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None, []

    sensors = []
    for chip, entries in temps.items():
        for e in entries:
            if e.current is None or e.current <= 0:
                continue
            sensors.append({
                "chip": chip,
                "label": e.label or chip,
                "current": round(e.current, 1),
                "high": e.high,
                "critical": e.critical,
            })

    cpu = None
    candidates = [c for c in CPU_SENSOR_PRIORITY if temps.get(c)]
    candidates += [c for c in temps if "cpu" in c.lower() and c not in candidates]
    for chip in candidates:
        entries = [e for e in temps[chip] if e.current and e.current > 0]
        if not entries:
            continue
        preferred = [e for e in entries if (e.label or "").lower().startswith(("package", "tctl", "tdie"))]
        best = preferred[0] if preferred else max(entries, key=lambda e: e.current)
        cpu = {
            "current": round(best.current, 1),
            "high": best.high,
            "critical": best.critical,
            "source": f"{chip} {best.label}".strip(),
        }
        break
    return cpu, sensors


def _mount_entries():
    """Retorna [(device, mountpoint_no_host, fstype, caminho_acessivel)]."""
    prefix = HOST_ROOT.rstrip("/") if os.path.isdir(HOST_ROOT) else ""
    entries = []
    for line in (_read_file("/proc/self/mounts") or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, mnt, fstype = parts[0], _unescape_mount(parts[1]), parts[2]
        if not prefix:
            host_mnt = mnt
        elif mnt == prefix:
            host_mnt = "/"
        elif mnt.startswith(prefix + "/"):
            host_mnt = mnt[len(prefix):]
        else:
            continue
        entries.append((dev, host_mnt, fstype, mnt))
    return entries


def _disks():
    by_device = {}
    for dev, host_mnt, fstype, path in _mount_entries():
        if fstype not in DISK_FSTYPES:
            continue
        if host_mnt != "/" and host_mnt.startswith(IGNORED_MOUNT_PREFIXES):
            continue
        current = by_device.get(dev)
        if current and len(current[1]) <= len(host_mnt):
            continue
        by_device[dev] = (dev, host_mnt, fstype, path)

    disks = []
    for dev, host_mnt, fstype, path in by_device.values():
        try:
            st = os.statvfs(path)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        if total == 0:
            continue
        free = st.f_bavail * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        disks.append({
            "device": dev,
            "mountpoint": host_mnt,
            "fstype": fstype,
            "total": total,
            "used": used,
            "free": free,
            "percent": round(used / (used + free) * 100, 1) if used + free else 0,
        })
    disks.sort(key=lambda d: (d["mountpoint"] != "/", d["mountpoint"]))
    return disks


def _net_counters():
    """Bytes por interface do namespace de rede do host (via PID 1)."""
    content = _read_file(os.path.join(HOST_PROC, "1/net/dev")) if HAS_HOST_PROC else None
    result = {}
    if content:
        for line in content.splitlines()[2:]:
            if ":" not in line:
                continue
            iface, data = line.split(":", 1)
            fields = data.split()
            if len(fields) >= 9:
                result[iface.strip()] = (int(fields[0]), int(fields[8]))
    else:
        for iface, c in psutil.net_io_counters(pernic=True).items():
            result[iface] = (c.bytes_recv, c.bytes_sent)
    return {k: v for k, v in result.items() if not k.startswith(IGNORED_IFACE_PREFIXES)}


def _disk_io():
    try:
        c = psutil.disk_io_counters()
        return (c.read_bytes, c.write_bytes) if c else None
    except Exception:
        return None


class MetricsSampler:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._snapshot = {}
        self._history = deque(maxlen=HISTORY_SIZE)
        self._prev = None
        self._host = _host_info()
        self._cpu_model = _cpu_model()

    def start(self):
        psutil.cpu_percent(percpu=True)
        self._prev = (time.monotonic(), _net_counters(), _disk_io())
        self._thread = threading.Thread(target=self._run, name="metrics", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(INTERVAL):
            try:
                self._sample()
            except Exception as exc:  # nunca derrubar a thread
                print(f"[metrics] erro na coleta: {exc!r}", flush=True)

    def _sample(self):
        now = time.monotonic()
        per_core = psutil.cpu_percent(percpu=True)
        cpu_total = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
        try:
            freq = psutil.cpu_freq()
        except Exception:
            freq = None
        try:
            load = os.getloadavg()
        except OSError:
            load = (0, 0, 0)

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        cpu_temp, sensors = _temperatures()

        net = _net_counters()
        dio = _disk_io()
        prev_t, prev_net, prev_dio = self._prev
        dt = max(now - prev_t, 1e-6)

        interfaces = []
        rx_rate = tx_rate = 0.0
        for iface, (rx, tx) in sorted(net.items()):
            prx, ptx = prev_net.get(iface, (rx, tx))
            irx = max(rx - prx, 0) / dt
            itx = max(tx - ptx, 0) / dt
            rx_rate += irx
            tx_rate += itx
            interfaces.append({"name": iface, "rx_rate": irx, "tx_rate": itx, "rx_total": rx, "tx_total": tx})

        read_rate = write_rate = None
        if dio and prev_dio:
            read_rate = max(dio[0] - prev_dio[0], 0) / dt
            write_rate = max(dio[1] - prev_dio[1], 0) / dt
        self._prev = (now, net, dio)

        snapshot = {
            "timestamp": time.time(),
            "host": {**self._host, "uptime": time.time() - psutil.boot_time()},
            "cpu": {
                "percent": cpu_total,
                "per_core": per_core,
                "model": self._cpu_model,
                "cores": psutil.cpu_count(logical=False),
                "threads": psutil.cpu_count(),
                "freq_mhz": round(freq.current) if freq and freq.current else None,
                "load": [round(x, 2) for x in load],
            },
            "temperature": cpu_temp,
            "sensors": sensors,
            "memory": {
                "total": mem.total,
                "used": mem.total - mem.available,
                "available": mem.available,
                "cached": getattr(mem, "cached", 0) + getattr(mem, "buffers", 0),
                "percent": mem.percent,
            },
            "swap": {"total": swap.total, "used": swap.used, "percent": swap.percent},
            "network": {"rx_rate": rx_rate, "tx_rate": tx_rate, "interfaces": interfaces},
            "disk_io": {"read_rate": read_rate, "write_rate": write_rate},
            "disks": _disks(),
        }

        with self._lock:
            self._history.append({
                "cpu": cpu_total,
                "mem": mem.percent,
                "temp": cpu_temp["current"] if cpu_temp else None,
                "rx": rx_rate,
                "tx": tx_rate,
            })
            self._snapshot = snapshot

    def snapshot(self):
        with self._lock:
            hist = list(self._history)
            data = dict(self._snapshot)
        data["history"] = {k: [h[k] for h in hist] for k in ("cpu", "mem", "temp", "rx", "tx")}
        return data
