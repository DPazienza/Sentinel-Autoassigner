import argparse
import importlib.util
import copy
import queue
import subprocess
from pathlib import Path
import threading

ROOT = Path(__file__).resolve().parent
APP_MODULE_PATH = ROOT / "app.py"


def _load_core():
    spec = importlib.util.spec_from_file_location("sentinel_app_core", str(APP_MODULE_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError("Impossibile caricare il modulo core dell'app")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)  # type: ignore[union-attr]
    return core


core = _load_core()


def _launch_browser_process(browser):
    browser = (browser or "").strip().lower()
    if browser not in ("chrome", "edge"):
        return False, "Browser non valido"

    exe = core.find_chrome_path() if browser == "chrome" else core.find_edge_path()
    if not exe:
        return False, f"{browser} non trovato"

    port = core.CHROME_DEBUG_PORT if browser == "chrome" else core.EDGE_DEBUG_PORT
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
            if 200 <= getattr(resp, "status", 0) < 400:
                return True, ""
    except Exception:
        pass

    profile_name = "chrome_bot_profile" if browser == "chrome" else "edge_bot_profile"
    profile_dir = (core.BROWSER_PROFILE_DIR / profile_name).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = [
        str(exe),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        f"--user-data-dir={str(profile_dir)}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-minimized",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-features=CalculateNativeWinOcclusion",
        "--new-window",
        "https://portal.azure.com/",
    ]

    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, ""
    except Exception as exc:
        return False, str(exc)


class WebViewApi:
    def __init__(self, store, worker, in_q, out_q):
        self.store = store
        self.worker = worker
        self.in_q = in_q
        self.out_q = out_q
        self._lock = threading.RLock()
        self._running = True
        self._state = {
            "status": "Worker pronto. Seleziona o avvia una tab Sentinel.",
            "runtime": self._snapshot_runtime(),
            "incidents": self.store.incidents(),
            "actions": self.store.actions(),
            "settings": self.worker.settings_dict(),
            "pages": [],
            "connected": [],
            "selected_page_id": None,
        }
        self._drain_thread = threading.Thread(target=self._drain_messages, daemon=True)
        self._drain_thread.start()

    def _snapshot_runtime(self):
        try:
            return self.worker.get_runtime_state()
        except Exception:
            return {
                "running_bot": False,
                "paused": False,
                "dry_run": True,
                "last_scan_ts": 0,
                "auto_fetch_enabled": False,
                "starting": False,
                "operation_in_progress": False,
                "operation_kind": "",
                "shutdown_requested": False,
            }

    @staticmethod
    def _normalize_ints(payload):
        if not isinstance(payload, dict):
            return {}
        out = {}
        for key, value in payload.items():
            try:
                out[key] = int(value)
            except Exception:
                out[key] = value
        return out

    def _drain_messages(self):
        while self._running:
            msg = None
            try:
                msg = self.out_q.get(timeout=0.4)
            except queue.Empty:
                continue

            kind = msg.get("kind")
            with self._lock:
                if kind == "pages":
                    self._state["pages"] = msg.get("pages", [])
                    self._state["connected"] = msg.get("connected", [])
                    self._state["selected_page_id"] = self.worker.target_page_id

                elif kind == "status":
                    self._state["status"] = msg.get("message", "")
                    settings = msg.get("settings")
                    if isinstance(settings, dict):
                        self._state["settings"] = settings

                elif kind == "scan_result":
                    self._state["incidents"] = msg.get("incidents", [])
                    self._state["actions"] = msg.get("actions", [])
                    settings = msg.get("settings")
                    if isinstance(settings, dict):
                        self._state["settings"] = settings

                elif kind == "sla_action":
                    action = msg.get("action") or ""
                    sev = msg.get("severity") or ""
                    key = msg.get("incident_key") or "-"
                    self._state["status"] = f"Notifica Windows {action}: {sev.upper()} {key}"

                elif kind == "error":
                    self._state["status"] = msg.get("message") or "Errore"
                    self._state["actions"] = msg.get("actions") or self._state.get("actions", [])

                self._state["runtime"] = self._snapshot_runtime()

    def _send(self, action, **kwargs):
        if not self._running:
            return {"ok": False, "error": "UI chiusa"}
        self.in_q.put({"action": action, **kwargs})
        return {"ok": True}

    def get_state(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def refresh_pages(self):
        return self._send("refresh_pages")

    def launch_browser(self, browser):
        ok, err = _launch_browser_process(browser)
        if not ok:
            return {"ok": False, "error": err}
        self.refresh_pages()
        return {"ok": True}

    def select_page(self, page_id):
        return self._send("select_page", page_id=str(page_id or ""))

    def open_sentinel_page(self):
        with self._lock:
            pages = list(self._state.get("pages", []))

        target = None
        for page in pages:
            if page.get("is_sentinel"):
                target = page.get("page_id")
                break

        if not target:
            return {"ok": False, "error": "Nessuna tab Sentinel trovata"}
        return self.select_page(target)

    def start(self, dry_run=True):
        return self._send("start", dry_run=bool(dry_run))

    def fetch(self):
        return self._send("fetch")

    def pause(self):
        return self._send("pause")

    def resume(self):
        return self._send("resume")

    def stop(self):
        return self._send("stop")

    def ignore_incident(self, incident_key):
        return self._send("ignore_incident", incident_key=incident_key)

    def dismiss_incident(self, incident_key):
        return self._send("dismiss_incident", incident_key=incident_key)

    def unignore_all(self):
        return self._send("unignore_all")

    def save_settings(self, values):
        payload = self._normalize_ints(values)
        return self._send("settings", values=payload)

    def shutdown(self):
        self._running = False
        return self._send("shutdown")


def _build_window_html():
    html_path = ROOT / "ui-demo-light-simple-dashboard.html"
    return html_path.read_text(encoding="utf-8")


def run_webview(debug=False):
    import webview

    store = core.Storage(core.DB_PATH)
    in_q = queue.Queue()
    out_q = queue.Queue()
    worker = core.BotWorker(in_q, out_q, store)
    worker.start()

    api = WebViewApi(store, worker, in_q, out_q)
    api.refresh_pages()

    html = _build_window_html()
    window = webview.create_window(
        "Sentinel Auto Assign Bot",
        html=html,
        js_api=api,
        width=1550,
        height=980,
        min_size=(1220, 820),
    )

    def _on_closed():
        try:
            api.shutdown()
        except Exception:
            pass

    try:
        window.events.closed += _on_closed
    except Exception:
        pass

    webview.start(gui="edgechromium", debug=debug)


def run_tk():
    app = core.BotApp()
    app.mainloop()
    return app


def main():
    parser = argparse.ArgumentParser(description="Sentinel Auto Assign Bot launcher")
    parser.add_argument("--ui", default="webview", choices=("webview", "tk"), help="Modalità UI")
    parser.add_argument("--debug", action="store_true", help="Abilita debug nel wrapper webview")
    args = parser.parse_args()

    if args.ui == "tk":
        return run_tk()

    try:
        run_webview(debug=args.debug)
    except Exception:
        run_tk()


if __name__ == "__main__":
    main()
