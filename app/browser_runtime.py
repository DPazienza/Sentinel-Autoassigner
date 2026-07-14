from dataclasses import dataclass
import subprocess
from pathlib import Path


@dataclass(frozen=True)
class BrowserLaunchResult:
    ok: bool
    error: str = ""
    pid: int | None = None


def build_browser_args(executable, port, profile_dir):
    """Single source of truth for the controlled background browser process."""
    return [
        str(executable),
        f"--remote-debugging-port={int(port)}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        f"--user-data-dir={str(Path(profile_dir).resolve())}",
        "--no-first-run",
        "--no-default-browser-check",
        "--restore-last-session",
        "--hide-crash-restore-bubble",
        "--start-minimized",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-features=CalculateNativeWinOcclusion",
        "--new-window",
        "https://portal.azure.com/",
    ]


def launch_controlled_browser(core, browser):
    browser = (browser or "").strip().lower()
    core.log_file("BROWSER_LAUNCH_START", f"browser={browser}")
    if browser not in ("chrome", "edge"):
        return BrowserLaunchResult(False, "Browser non valido")

    executable = core.find_chrome_path() if browser == "chrome" else core.find_edge_path()
    if not executable:
        core.log_file("BROWSER_LAUNCH_FAIL", f"browser={browser};reason=not_found")
        return BrowserLaunchResult(False, f"{browser} non trovato")

    port = core.CHROME_DEBUG_PORT if browser == "chrome" else core.EDGE_DEBUG_PORT
    if core._debug_port_alive(port):
        owned = [
            pid for pid in core._debug_port_owner_pids(port)
            if core._is_owned_debug_browser_process(pid, browser, port)
        ]
        if not owned:
            core.log_file("BROWSER_LAUNCH_BLOCKED", f"browser={browser};port={port};reason=not_owned")
            return BrowserLaunchResult(
                False,
                f"Porta debug {port} gia attiva ma non appartiene al profilo controllato dell'app",
            )
        core.log_file("BROWSER_LAUNCH_READY", f"browser={browser};port={port};existing={owned}")
        return BrowserLaunchResult(True, pid=owned[0])

    core.terminate_debug_port_owner(browser, port, reason="controlled_launch_port_not_responding")
    profile_dir = core.browser_profile_dir(browser)
    profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        process = subprocess.Popen(
            build_browser_args(executable, port, profile_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        core.log_file(
            "BROWSER_LAUNCH_OK",
            f"browser={browser};port={port};pid={process.pid};profile={profile_dir}",
        )
        if core.wait_debug_port_alive(port, timeout_seconds=12):
            core.log_file("BROWSER_LAUNCH_READY", f"browser={browser};port={port};pid={process.pid}")
            return BrowserLaunchResult(True, pid=process.pid)
        return BrowserLaunchResult(False, f"{browser} avviato ma porta debug {port} non pronta", process.pid)
    except Exception as exc:
        core.log_file("BROWSER_LAUNCH_FAIL", f"browser={browser};port={port};err={type(exc).__name__}: {exc}", exc)
        return BrowserLaunchResult(False, str(exc))
