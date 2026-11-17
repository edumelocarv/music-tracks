"""Cross-platform launcher (spec §4): starts the worker and the API, opens the browser.

    uv run --project backend python -m app.launcher [--port N] [--no-browser] [--dev]

Replaces the bash logic of start.sh/dev.sh so the same code runs on macOS, Linux and
Windows (start.sh, dev.sh, start.ps1 and start.cmd are thin wrappers around it).

- Checks ffmpeg/ffprobe/node (and npm when the frontend must be built), printing the
  install command for the current OS.
- Builds `frontend/dist` when it is missing or older than the frontend sources
  (`npm ci` only when `node_modules` is missing or older than `package-lock.json`).
- Starts `python -m app.worker` and uvicorn with this interpreter (`sys.executable`),
  waits for GET /api/health (30 s) and opens the browser.
- Restarts the worker when it dies (at most 3 times in 5 min); if the API dies, stops
  everything and exits with 1. Ctrl+C (or SIGTERM) stops both cleanly.
- `--dev`: API with --reload, Vite dev server on :5173 (`npm run dev`), MUSIC_TRACKS_DEV=1.

Environment: MUSIC_TRACKS_PORT (8765), MUSIC_TRACKS_HOST (127.0.0.1), MUSIC_TRACKS_HOME
(data folder), MUSIC_TRACKS_NO_BROWSER (any non-empty value = --no-browser).
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path
from typing import Sequence

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"

IS_WINDOWS = os.name == "nt"
DEFAULT_PORT = 8765
VITE_PORT = 5173
MIN_NODE_MAJOR = 20
HEALTH_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 15.0
MAX_WORKER_RESTARTS = 3
RESTART_WINDOW_S = 300.0

# Inputs of the frontend build: dist is rebuilt when any of these is newer than dist/index.html.
FRONTEND_INPUTS = (
    "src", "public", "index.html", "package.json", "package-lock.json", "vite.config.ts",
    "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json",
)


class Shutdown(Exception):
    """SIGTERM/SIGHUP received: stop like Ctrl+C."""


def say(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def warn(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- dependencies


def which(name: str) -> str | None:
    if IS_WINDOWS and name == "npm":
        return shutil.which("npm.cmd") or shutil.which("npm")
    if name in ("ffmpeg", "ffprobe"):
        from .audio import find_executable  # also looks in Homebrew dirs on macOS

        return find_executable(name)
    return shutil.which(name)


def linux_distro_ids(os_release: Path = Path("/etc/os-release")) -> set[str]:
    try:
        text = os_release.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    ids: set[str] = set()
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("ID", "ID_LIKE"):
            ids.update(value.strip().strip("\"'").lower().split())
    return ids


def install_hint(missing: Sequence[str], platform: str | None = None, distro: set[str] | None = None) -> list[str]:
    """Commands that install the missing tools on this OS (one per line)."""
    platform = platform or sys.platform
    need_ffmpeg = any(m in ("ffmpeg", "ffprobe") for m in missing)
    need_node = any(m in ("node", "npm") for m in missing)
    if platform == "darwin":
        pkgs = (["ffmpeg"] if need_ffmpeg else []) + (["node"] if need_node else [])
        return [f"brew install {' '.join(pkgs)}", "(Homebrew: https://brew.sh)"]
    if platform == "win32":
        pkgs = (["Gyan.FFmpeg"] if need_ffmpeg else []) + (["OpenJS.NodeJS.LTS"] if need_node else [])
        return [
            f"winget install {' '.join(pkgs)}",
            "Depois abra um novo terminal / then open a new terminal (PATH is updated on new shells).",
        ]
    ids = linux_distro_ids() if distro is None else distro
    pkgs = (["ffmpeg"] if need_ffmpeg else []) + (["nodejs", "npm"] if need_node else [])
    if ids & {"debian", "ubuntu"}:
        return [f"sudo apt install {' '.join(pkgs)}"]
    if ids & {"fedora", "rhel", "centos"}:
        lines = [f"sudo dnf install {' '.join(pkgs)}"]
        if need_ffmpeg:
            lines.append("(Fedora: ffmpeg comes from RPM Fusion; `ffmpeg-free` also works)")
        return lines
    if ids & {"arch"}:
        return [f"sudo pacman -S {' '.join(pkgs)}"]
    return [f"Instale / install: {', '.join(pkgs)} (with your package manager)"]


def node_major(node: str) -> int | None:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15).stdout.strip()
        return int(out.lstrip("v").split(".")[0])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def check_dependencies(need_npm: bool) -> bool:
    """ffmpeg/ffprobe (always), node (YouTube downloads; frontend build), npm (build/dev)."""
    wanted = ["ffmpeg", "ffprobe", "node"] + (["npm"] if need_npm else [])
    missing = [name for name in wanted if which(name) is None]
    if missing:
        warn(f"Dependências ausentes / missing dependencies: {' '.join(missing)}")
        for line in install_hint(missing):
            warn(f"  {line}")
        return False
    major = node_major(which("node") or "node")
    if major is not None and major < MIN_NODE_MAJOR:
        msg = f"Node {major} é antigo / is too old: Node >= {MIN_NODE_MAJOR} is required (https://nodejs.org)."
        if need_npm:
            warn(msg)
            return False
        warn(f"Aviso / warning: {msg} YouTube downloads may fail.")
    return True


# ---------------------------------------------------------------- port


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True if something listens on the port or binding it fails (like uvicorn would)."""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "", "localhost") else host
    family = socket.AF_INET6 if ":" in probe_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((probe_host, port)) == 0:
            return True
    bind_host = "0.0.0.0" if host == "" else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        if not IS_WINDOWS:
            # uvicorn sets SO_REUSEADDR too; without it a TIME_WAIT socket from the previous
            # run would look busy. (On Windows SO_REUSEADDR means "steal the port": never.)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((bind_host, port))
        except OSError:
            return True
    return False


# ---------------------------------------------------------------- frontend


def _newest_mtime(path: Path) -> float:
    if path.is_file():
        return path.stat().st_mtime
    newest = 0.0
    if path.is_dir():
        for dirpath, _dirs, files in os.walk(path):
            for f in files:
                try:
                    newest = max(newest, os.stat(os.path.join(dirpath, f)).st_mtime)
                except OSError:
                    pass
    return newest


def frontend_needs_build(frontend: Path = FRONTEND_DIR) -> bool:
    index = frontend / "dist" / "index.html"
    if not index.is_file():
        return True
    if not (frontend / "src").is_dir():
        return False  # prebuilt dist without sources (e.g. the Docker image)
    built = index.stat().st_mtime
    return any(_newest_mtime(frontend / name) > built for name in FRONTEND_INPUTS)


def node_modules_outdated(frontend: Path = FRONTEND_DIR) -> bool:
    modules = frontend / "node_modules"
    if not modules.is_dir():
        return True
    lock = frontend / "package-lock.json"
    marker = modules / ".package-lock.json"  # written by npm on every install
    stamp = marker if marker.exists() else modules
    return lock.is_file() and lock.stat().st_mtime > stamp.stat().st_mtime


def npm_run(args: list[str]) -> bool:
    npm = which("npm")
    if npm is None:
        return False
    return subprocess.run([npm, *args], cwd=FRONTEND_DIR).returncode == 0


def ensure_node_modules() -> bool:
    if node_modules_outdated():
        say("Frontend: npm ci")
        return npm_run(["ci", "--no-audit", "--no-fund"])
    return True


def build_frontend() -> bool:
    if not ensure_node_modules():
        return False
    say("Frontend: build")
    return npm_run(["run", "build"])


# ---------------------------------------------------------------- child processes


class Child:
    """A subprocess in its own process group / session, so that terminal Ctrl+C reaches
    only the launcher, which then stops the children in order."""

    def __init__(self, name: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        kwargs: dict = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(self.cmd, cwd=self.cwd, env=self.env, **kwargs)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def returncode(self) -> int | None:
        return None if self.proc is None else self.proc.poll()

    def request_stop(self) -> None:
        """Graceful stop: SIGTERM to the process group (POSIX) or CTRL_BREAK (Windows;
        handled as SIGBREAK by uvicorn and the worker)."""
        if self.proc is None:
            return
        try:
            if IS_WINDOWS:
                if self.alive():
                    if self.cmd and self.cmd[0].lower().endswith((".cmd", ".bat")):
                        self.kill()  # cmd.exe would ask "Terminate batch job (Y/N)?"
                    else:
                        self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)  # also reaches reloader/vite children
        except (OSError, ValueError):
            pass

    def kill(self) -> None:
        if self.proc is None:
            return
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
            else:
                os.killpg(self.proc.pid, signal.SIGKILL)
        except (OSError, ValueError):
            pass

    def wait(self, timeout: float) -> bool:
        if self.proc is None:
            return True
        try:
            self.proc.wait(timeout=max(0.0, timeout))
            return True
        except subprocess.TimeoutExpired:
            return False


def stop_all(children: Sequence[Child | None], timeout: float = STOP_TIMEOUT_S) -> None:
    procs = [c for c in children if c is not None and c.proc is not None]
    for c in procs:
        c.request_stop()
    deadline = time.monotonic() + timeout
    for c in procs:
        if not c.wait(deadline - time.monotonic()):
            warn(f"{c.name} não encerrou / did not stop in {timeout:.0f} s; killing it")
            c.kill()
            c.wait(5)
        elif not IS_WINDOWS:
            c.kill()  # leftovers of the process group (e.g. uvicorn's reload child), if any


# ---------------------------------------------------------------- health / browser


def health_url(host: str, port: int) -> tuple[str, str]:
    """(URL to poll, Host header). Wildcard binds are reached through loopback."""
    connect = "127.0.0.1" if host in ("0.0.0.0", "::", "", "localhost") else host
    netloc = f"[{connect}]:{port}" if ":" in connect else f"{connect}:{port}"
    return f"http://{netloc}/api/health", f"127.0.0.1:{port}"


def api_healthy(host: str, port: int) -> bool:
    url, host_header = health_url(host, port)
    req = urllib.request.Request(url, headers={"Host": host_header})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310 - local URL
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_for_api(api: Child, host: str, port: int, timeout: float = HEALTH_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if api_healthy(host, port):
            return True
        if not api.alive():
            return False
        time.sleep(0.5)
    return False


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - headless machines have no browser; not fatal
        pass


# ---------------------------------------------------------------- main


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m app.launcher", description="Music Tracks launcher")
    p.add_argument("--port", type=int, default=None, help="API port (default: $MUSIC_TRACKS_PORT or 8765)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser ($MUSIC_TRACKS_NO_BROWSER)")
    p.add_argument("--dev", action="store_true", help="API with --reload + Vite dev server on :5173")
    args = p.parse_args(argv)
    if args.port is None:
        raw = os.environ.get("MUSIC_TRACKS_PORT", "").strip() or str(DEFAULT_PORT)
        try:
            args.port = int(raw)
        except ValueError:
            p.error(f"invalid MUSIC_TRACKS_PORT: {raw!r}")
    if not 1 <= args.port <= 65535:
        p.error(f"invalid port: {args.port}")
    args.no_browser = args.no_browser or bool(os.environ.get("MUSIC_TRACKS_NO_BROWSER", "").strip())
    return args


def child_env(port: int, dev: bool) -> dict[str, str]:
    env = dict(os.environ)
    env["MUSIC_TRACKS_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    if dev:
        env["MUSIC_TRACKS_DEV"] = "1"
    return env


def _install_signal_handlers() -> None:
    fired = []

    def handler(signum, _frame) -> None:  # noqa: ANN001
        if not fired:  # only the first one interrupts; later ones must not break the cleanup
            fired.append(signum)
            raise Shutdown(signal.Signals(signum).name)

    # Ctrl+C -> KeyboardInterrupt even when started with SIGINT ignored (background job).
    signal.signal(signal.SIGINT, signal.default_int_handler)
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError):
                pass


def _ensure_homebrew_on_path() -> None:
    """macOS: Homebrew's bin may be missing from PATH (GUI/non-login shells); node, npm and
    ffmpeg live there. Children inherit the fixed PATH."""
    if sys.platform == "darwin":
        path = os.environ.get("PATH", "")
        for d in ("/usr/local/bin", "/opt/homebrew/bin"):
            if os.path.isdir(d) and d not in path.split(os.pathsep):
                path = d + (os.pathsep + path if path else "")
        os.environ["PATH"] = path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    _ensure_homebrew_on_path()
    from .config import bind_host

    host = bind_host()
    port = args.port
    dev = args.dev

    needs_build = not dev and frontend_needs_build()
    if not check_dependencies(need_npm=dev or needs_build):
        return 1
    if port_in_use(port, host):
        warn(f"A porta {port} já está em uso / port {port} is already in use.")
        warn("Use --port <N> ou / or MUSIC_TRACKS_PORT=<N>")
        return 1
    if dev and port_in_use(VITE_PORT):
        warn(f"A porta {VITE_PORT} (Vite) já está em uso / port {VITE_PORT} (Vite) is already in use.")
        return 1
    if dev:
        if not ensure_node_modules():
            return 1
    elif needs_build and not build_frontend():
        warn("Falha ao compilar a interface / frontend build failed.")
        return 1

    env = child_env(port, dev)
    py = sys.executable
    api_cmd = [py, "-m", "uvicorn", "app.api.main:app", "--host", host, "--port", str(port)]
    if dev:
        api_cmd += ["--reload", "--reload-dir", str(BACKEND_DIR / "app")]
    else:
        api_cmd += ["--log-level", "warning"]
    worker = Child("worker", [py, "-m", "app.worker"], BACKEND_DIR, env)
    api = Child("api", api_cmd, BACKEND_DIR, env)
    vite: Child | None = None
    if dev:
        npm = which("npm") or "npm"
        vite = Child("vite", [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(VITE_PORT),
                              "--strictPort"], FRONTEND_DIR, env)

    _install_signal_handlers()
    url = f"http://localhost:{VITE_PORT}" if dev else f"http://127.0.0.1:{port}"
    restarts: deque[float] = deque()
    try:
        say(f"Iniciando worker e API / starting worker and API on http://{host}:{port}")
        worker.start()
        api.start()
        if vite is not None:
            vite.start()
        if not wait_for_api(api, host, port):
            warn(f"A API não respondeu em {HEALTH_TIMEOUT_S:.0f} s / API did not respond within "
                 f"{HEALTH_TIMEOUT_S:.0f} s.")
            return 1
        if not args.no_browser:
            open_browser(url)
        extra = f" (API em / at http://127.0.0.1:{port})" if dev else ""
        say(f"Pronto / ready: {url}{extra}  (Ctrl+C para sair / to quit)")

        while True:
            if not api.alive():
                warn(f"A API parou / API stopped (exit code {api.returncode}).")
                return 1
            if vite is not None and not vite.alive():
                warn(f"O Vite parou / Vite stopped (exit code {vite.returncode}).")
                return 1
            if not worker.alive():
                now = time.monotonic()
                while restarts and now - restarts[0] >= RESTART_WINDOW_S:
                    restarts.popleft()
                if len(restarts) >= MAX_WORKER_RESTARTS:
                    warn("O worker caiu 3 vezes em 5 min; encerrando / worker crashed 3 times in 5 min; exiting.")
                    return 1
                warn(f"O worker parou (código {worker.returncode}); reiniciando / worker stopped; restarting...")
                restarts.append(now)
                worker.start()
            time.sleep(1)
    except (KeyboardInterrupt, Shutdown):
        return 0
    finally:
        print(flush=True)
        say("Encerrando / stopping...")
        # API first (stops accepting requests), then the worker (requeues a running job).
        try:
            stop_all([vite, api, worker])
        except KeyboardInterrupt:  # second Ctrl+C: don't wait any longer
            for c in (vite, api, worker):
                if c is not None:
                    c.kill()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # Ctrl+C before the processes started (e.g. during npm ci)
        sys.exit(130)
