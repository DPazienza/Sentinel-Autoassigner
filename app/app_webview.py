import argparse
import importlib.util
import copy
import queue
from pathlib import Path
import threading

from browser_runtime import launch_controlled_browser

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
    result = launch_controlled_browser(core, browser)
    return result.ok, result.error


class WebViewApi:
    def __init__(self, store, worker, in_q, out_q):
        self.store = store
        self.worker = worker
        self.in_q = in_q
        self.out_q = out_q
        self._lock = threading.RLock()
        self._running = True
        self._launching_browsers = set()
        self._pending_commands = set()
        self._state = {
            "status": "Worker pronto. Seleziona o avvia una tab Sentinel.",
            "runtime": self._snapshot_runtime(),
            "incidents": self.store.incidents(),
            "actions": self.store.actions(),
            "settings": self.worker.settings_dict(),
            "pages": [],
            "connected": [],
            "selected_page_id": None,
            "worker_alive": True,
        }
        self._drain_thread = threading.Thread(target=self._drain_messages, daemon=True)
        self._drain_thread.start()

    def _snapshot_runtime(self):
        try:
            return self.worker.get_runtime_state()
        except Exception:
            return {
                "running_monitor": False,
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
            except Exception as exc:
                core.log_file("WEBVIEW_DRAIN_QUEUE_FAIL", str(exc), exc)
                continue

            try:
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
                        result = "CONFIRMED" if action == "confirm" else "DISMISSED"
                        self.store.log_action(
                            key,
                            msg.get("incident_title") or "-",
                            "SLA_NOTIFICATION_ACTION",
                            result,
                            f"action={action};severity={sev}",
                        )
                        self._state["actions"] = self.store.actions()
                        self._state["status"] = f"Notifica Windows {action}: {sev.upper()} {key}"

                    elif kind == "sla_confirm":
                        sev = msg.get("severity") or ""
                        key = msg.get("incident_key") or "-"
                        self._state["status"] = f"Notifica Windows confermata: {sev.upper()} {key}"

                    elif kind == "command_complete":
                        self._pending_commands.discard(msg.get("action"))

                    elif kind == "error":
                        self._state["status"] = msg.get("message") or "Errore"
                        self._state["actions"] = msg.get("actions") or self._state.get("actions", [])

                    self._state["selected_page_id"] = self.worker.target_page_id
                    self._state["runtime"] = self._snapshot_runtime()
                    self._state["worker_alive"] = bool(self.worker and self.worker.is_alive())
            except Exception as exc:
                core.log_file("WEBVIEW_DRAIN_MESSAGE_FAIL", str(exc), exc)

    def _send(self, action, **kwargs):
        self._apply_immediate_control(action)
        if not self._running and action != "shutdown":
            return {"ok": False, "error": "UI chiusa"}
        if not self.worker or not self.worker.is_alive():
            with self._lock:
                self._state["status"] = "Worker non attivo: riavvia l'app."
                self._state["worker_alive"] = False
            return {"ok": False, "error": "Worker non attivo: riavvia l'app."}
        coalesced_actions = {"fetch", "start", "refresh_pages"}
        with self._lock:
            if action in coalesced_actions and action in self._pending_commands:
                return {"ok": True, "queued": False}
            if action in coalesced_actions:
                self._pending_commands.add(action)
        try:
            self.in_q.put({"action": action, **kwargs})
        except Exception:
            with self._lock:
                self._pending_commands.discard(action)
            raise
        return {"ok": True}

    def _apply_immediate_control(self, action):
        try:
            if not self.worker:
                return
            if action == "pause":
                self.worker.request_pause()
                with self._lock:
                    self._state["status"] = "Pausa richiesta. Stop scan in corso appena possibile."
            elif action == "stop":
                self.worker.request_stop()
                with self._lock:
                    self._state["status"] = "Stop richiesto. Operazioni in corso in chiusura."
            elif action == "shutdown":
                self.worker.request_stop(shutdown=True)
                with self._lock:
                    self._state["status"] = "Chiusura worker richiesta."
        except Exception as exc:
            core.log_file("WEBVIEW_IMMEDIATE_CONTROL_FAIL", f"action={action}", exc)

    def get_state(self):
        with self._lock:
            self._state["worker_alive"] = bool(self.worker and self.worker.is_alive())
            self._state["runtime"] = self._snapshot_runtime()
            return copy.deepcopy(self._state)

    def refresh_pages(self):
        return self._send("refresh_pages")

    def launch_browser(self, browser):
        browser_key = (browser or "").strip().lower()
        if browser_key not in ("chrome", "edge"):
            return {"ok": False, "error": "Browser non valido"}
        with self._lock:
            if browser_key in self._launching_browsers:
                return {"ok": True}
            self._launching_browsers.add(browser_key)
            self._state["status"] = f"Avvio {browser_key} debug in corso..."

        def _launch_job():
            ok, err = _launch_browser_process(browser_key)
            with self._lock:
                self._launching_browsers.discard(browser_key)
                self._state["status"] = (
                    f"{browser_key} debug avviato. Aggiornamento tab..."
                    if ok else (err or f"{browser_key} non avviato")
                )
            if ok:
                self.refresh_pages()

        threading.Thread(target=_launch_job, name=f"launch-{browser_key}", daemon=True).start()
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
        result = self._send("ignore_incident", incident_key=incident_key)
        if result.get("ok"):
            key = str(incident_key or "").strip()
            with self._lock:
                self._state["incidents"] = [
                    inc for inc in self._state.get("incidents", [])
                    if str(inc.get("incident_key") or "").strip() != key
                ]
                self._state["status"] = f"Incident {key or '-'} ignorato localmente."
        return result

    def dismiss_incident(self, incident_key):
        result = self._send("dismiss_incident", incident_key=incident_key)
        if result.get("ok"):
            key = str(incident_key or "").strip()
            with self._lock:
                self._state["incidents"] = [
                    inc for inc in self._state.get("incidents", [])
                    if str(inc.get("incident_key") or "").strip() != key
                ]
                self._state["status"] = f"Incident {key or '-'} rimosso dal database locale."
        return result

    def unignore_all(self):
        return self._send("unignore_all")

    def save_settings(self, values):
        payload = self._normalize_ints(values)
        result = self._send("settings", values=payload)
        if not result.get("ok"):
            with self._lock:
                self._state["status"] = result.get("error") or "Impostazioni non salvate: worker non disponibile."
            return result
        with self._lock:
            current = self._state.get("settings", {})
            if isinstance(current, dict):
                merged = dict(current)
                merged.update(payload)
                self._state["settings"] = merged
            else:
                self._state["settings"] = dict(payload)
            self._state["status"] = "Impostazioni salvate in coda."
        return result

    def shutdown(self):
        if not self._running:
            return {"ok": True}
        result = self._send("shutdown")
        self._running = False
        return result


def _build_window_html():
    html_path = ROOT / "dashboard.html"
    return html_path.read_text(encoding="utf-8")


def run_webview(debug=False):
    import webview

    core.enable_windows_background_runtime()
    store = core.Storage(core.DB_PATH)
    try:
        store.clear_runtime_data()
        core.log_file("WEBVIEW_DB_CLEAR", "startup clear runtime tables requested and completed")
    except Exception as exc:
        core.log_file("WEBVIEW_DB_CLEAR_FAIL", "startup clear runtime tables failed", exc)

    in_q = queue.Queue()
    out_q = queue.Queue()
    core.set_windows_notification_action_sink(
        lambda payload: out_q.put({**payload, "kind": "sla_action"})
    )
    worker = core.NotifierWorker(in_q, out_q, store)
    worker.browser_relauncher = lambda browser: _launch_browser_process(browser)[0]
    worker.start()

    api = WebViewApi(store, worker, in_q, out_q)
    api.refresh_pages()

    html = _build_window_html()
    try:
        window = webview.create_window(
            "Sentinel Notifier",
            html=html,
            js_api=api,
            width=1360,
            height=900,
            min_size=(980, 720),
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
    except Exception as exc:
        core.log_file("WEBVIEW_RUNTIME_FAIL", str(exc), exc)
        raise
    finally:
        try:
            api.shutdown()
        except Exception:
            pass
        try:
            worker.join(timeout=20)
        except Exception:
            pass
        if worker.is_alive():
            core.log_file("WEBVIEW_WORKER_JOIN_TIMEOUT", "skip cross-thread playwright cleanup")
        else:
            try:
                worker.cleanup_playwright()
            except Exception:
                pass
        core.set_windows_notification_action_sink(None)


def run_tk():
    app = core.NotifierApp()
    app.mainloop()
    return app


def main():
    parser = argparse.ArgumentParser(description="Sentinel Notifier launcher")
    parser.add_argument("--ui", default="webview", choices=("webview", "tk"), help="Modalita UI")
    parser.add_argument("--debug", action="store_true", help="Abilita debug nel wrapper webview")
    args = parser.parse_args()

    if args.ui == "tk":
        return run_tk()

    try:
        run_webview(debug=args.debug)
    except Exception as exc:
        core.log_file("WEBVIEW_MAIN_FAIL", str(exc), exc)
        raise


if __name__ == "__main__":
    main()

