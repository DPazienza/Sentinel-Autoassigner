
import argparse, copy, math, os, queue, re, shutil, sqlite3, subprocess, threading, time, tkinter as tk, sys, traceback
import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "bot_state.sqlite3"
BROWSER_PROFILE_DIR = BASE_DIR / "browser_profiles"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
BROWSER_PROFILE_DIR.mkdir(exist_ok=True)
CHROME_DEBUG_PORT = 9222
EDGE_DEBUG_PORT = 9223
ENABLE_ASSIGNMENT_WORKFLOW = True
KEEP_WINDOWS_AWAKE = True

APP_LOG_PATH = LOG_DIR / "app.log"

def log_file(event, details="", exc=None):
    """
    Append diagnostic information to logs/app.log.
    This is intentionally simple and dependency-free so it also works when UI/DB logging fails.
    """
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        thread_name = threading.current_thread().name
        msg = f"[{ts}] [{thread_name}] {event}"
        if details:
            msg += f" | {details}"
        if exc is not None:
            msg += "\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with APP_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def enable_windows_background_runtime():
    """
    Keep the logged-in Windows session alive while the app is running.
    This helps when the PC is locked: processes keep running, while the display
    can still turn off. It cannot bypass sleep/hibernation policies enforced by IT.
    """
    if os.name != 'nt' or not KEEP_WINDOWS_AWAKE:
        return False
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_AWAYMODE_REQUIRED = 0x00000040
        result = ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
        )
        log_file("WINDOWS_KEEP_AWAKE", f"enabled={bool(result)}")
        return bool(result)
    except Exception as exc:
        log_file("WINDOWS_KEEP_AWAKE_FAIL", str(exc), exc)
        return False


def browser_profile_dir(browser):
    browser = (browser or '').strip().lower()
    if browser == 'chrome':
        preferred = 'chrome_notifier_profile'
        legacy = ['chrome_bot_profile', 'chrome_monitor_profile']
    else:
        preferred = 'edge_notifier_profile'
        legacy = ['edge_bot_profile', 'edge_monitor_profile']

    preferred_path = (BROWSER_PROFILE_DIR / preferred).resolve()
    if preferred_path.exists():
        return preferred_path

    for name in legacy:
        candidate = (BROWSER_PROFILE_DIR / name).resolve()
        if candidate.exists():
            log_file("BROWSER_PROFILE_LEGACY", f"browser={browser};profile={candidate}")
            return candidate

    return preferred_path

def install_global_exception_logging():
    def _excepthook(exc_type, exc, tb):
        try:
            log_file("UNHANDLED_EXCEPTION", "", exc)
        finally:
            try:
                sys.__excepthook__(exc_type, exc, tb)
            except Exception:
                pass

    sys.excepthook = _excepthook

    try:
        def _threading_excepthook(args):
            try:
                log_file("UNHANDLED_THREAD_EXCEPTION", getattr(args.thread, "name", ""), args.exc_value)
            except Exception:
                pass
        threading.excepthook = _threading_excepthook
    except Exception:
        pass

install_global_exception_logging()


def now_utc(): return datetime.now(timezone.utc)
def now_iso(): return now_utc().isoformat(timespec="seconds")
def normalize_text(v): return re.sub(r"\s+", " ", v or "").strip()

def local_now_iso():
    return datetime.now().isoformat(timespec="seconds")


def format_time_only(value):
    """
    Display only system-local hour and minute.
    """
    if not value:
        return "-"
    dt = parse_iso(value)
    if not dt:
        dt = parse_sentinel_datetime(value) if "parse_sentinel_datetime" in globals() else None
    if not dt:
        return "-"

    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.astimezone().replace(tzinfo=None)

    return dt.strftime("%H:%M")


def parse_iso(v):
    if not v: return None
    try: return datetime.fromisoformat(v)
    except Exception: return None


def parse_sentinel_datetime(value):
    """
    Parses Sentinel UI dates such as:
      06/06/26, 04:23 PM
      06/06/2026, 04:23 PM
      6/6/26, 4:23 PM
    Returns a timezone-aware datetime.
    """
    if not value:
        return None

    raw = str(value).strip()
    raw = re.sub(r"\s+", " ", raw)

    formats = [
        "%m/%d/%y, %I:%M %p",
        "%m/%d/%Y, %I:%M %p",
        "%d/%m/%y, %I:%M %p",
        "%d/%m/%Y, %I:%M %p",
        "%m/%d/%y, %H:%M",
        "%m/%d/%Y, %H:%M",
        "%d/%m/%y, %H:%M",
        "%d/%m/%Y, %H:%M",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%Y %I:%M %p",
        "%d/%m/%y %I:%M %p",
        "%d/%m/%Y %I:%M %p",
        "%m/%d/%y %H:%M",
        "%m/%d/%Y %H:%M",
        "%d/%m/%y %H:%M",
        "%d/%m/%Y %H:%M",
        "%m/%d/%y %I:%M:%S %p",
        "%m/%d/%Y %I:%M:%S %p",
        "%d/%m/%y %I:%M:%S %p",
        "%d/%m/%Y %I:%M:%S %p",
        "%m/%d/%y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%d/%m/%y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            pass

    try:
        return parse_iso(raw)
    except Exception:
        return None


def format_sentinel_datetime(dt):
    if not dt:
        return "-"
    try:
        return dt.strftime("%m/%d/%y, %I:%M %p")
    except Exception:
        return "-"


def add_minutes_to_sentinel_datetime(value, minutes):
    dt = parse_sentinel_datetime(value)
    if not dt:
        return "-"
    return format_sentinel_datetime(dt + timedelta(minutes=int(minutes)))


def created_age_minutes(created_time):
    dt = parse_sentinel_datetime(created_time)
    if not dt:
        return None
    # Sentinel UI shows browser-local time. Use local now and strip timezone if present.
    if getattr(dt, 'tzinfo', None) is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return int((datetime.now() - dt).total_seconds() // 60)


def created_age_minutes_with_fallback(created_time, fallback_time=""):
    age = created_age_minutes(created_time)
    if age is not None:
        return age

    dt = parse_sentinel_datetime(fallback_time)
    if not dt:
        return None

    if getattr(dt, 'tzinfo', None) is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return int((datetime.now() - dt).total_seconds() // 60)


def remaining_minutes_from_created(created_time, target_minutes):
    """
    Remaining minutes from Sentinel Creation time to a target threshold.
    Example:
        created=10:00, target=60, now=10:20 -> 40
        created=10:00, target=60, now=11:10 -> -10
    """
    age = created_age_minutes(created_time)
    if age is None:
        return None
    return int(target_minutes) - age


def minutes_since(timestamp):
    dt = parse_iso(timestamp)
    if dt is None and "parse_sentinel_datetime" in globals():
        dt = parse_sentinel_datetime(timestamp)
    if not dt:
        return None

    if getattr(dt, 'tzinfo', None) is not None:
        dt = dt.astimezone().replace(tzinfo=None)

    return max(0, int((datetime.now() - dt).total_seconds() // 60))


def format_remaining_minutes(value):
    if value is None:
        return "-"
    if value > 0:
        return f"{value} min"
    if value == 0:
        return "0 min"
    return f"OVERDUE {abs(value)} min"


def sla_remaining_from_created(created_time, severity, settings):
    return remaining_minutes_from_created(created_time, settings.sla_for(severity))


def customer_notification_remaining_from_created(created_time, severity, settings):
    return remaining_minutes_from_created(created_time, settings.notification_for(severity))


def clamp_int(v, default, lo, hi):
    try: x = int(v)
    except Exception: x = default
    return max(lo, min(hi, x))

_WINOTIFY_NOTIFIER = None
_WINDOWS_NOTIFICATION_ACTION_SINK = None


def _sanitize_identifier(value):
    try:
        return re.sub(r"[^a-zA-Z0-9_\\-]", "_", str(value or ''))
    except Exception:
        return "item"


def set_windows_notification_action_sink(callback):
    global _WINDOWS_NOTIFICATION_ACTION_SINK
    _WINDOWS_NOTIFICATION_ACTION_SINK = callback


def _dispatch_windows_notification_action(payload):
    sink = _WINDOWS_NOTIFICATION_ACTION_SINK
    if not callable(sink):
        return
    try:
        sink(payload)
    except Exception as e:
        log_file("WINDOWS_TOAST_ACTION_SINK_FAIL", str(e))


def _get_winotify_notifier():
    global _WINOTIFY_NOTIFIER
    if os.name != 'nt':
        return None
    try:
        if _WINOTIFY_NOTIFIER is None:
            from winotify import Notifier, Registry
            registry = Registry("Sentinel Notifier", script_path=str(Path(__file__).resolve()))
            _WINOTIFY_NOTIFIER = Notifier(registry)
            _WINOTIFY_NOTIFIER.start()
        return _WINOTIFY_NOTIFIER
    except Exception as e:
        return None


def _winotify_action_handler(action, incident_key, incident_title, severity):
    key = _sanitize_identifier(incident_key)
    title = str(incident_title or 'incident')
    sev = (severity or '').strip().lower()
    def _handler():
        log_file("WINDOWS_TOAST_ACTION", f"action={action};severity={sev};incident_key={key};title={title}")
        _dispatch_windows_notification_action({
            "action": action,
            "severity": sev,
            "incident_key": incident_key,
            "incident_title": incident_title,
        })
    _handler.__name__ = f"sentinel_{action}_{key}_{int(time.time())}"
    notifier = _get_winotify_notifier()
    if notifier is None:
        return None
    try:
        return notifier.register_callback(_handler)
    except Exception:
        return None


def _winotify_update():
    notifier = _get_winotify_notifier()
    if notifier is None:
        return
    try:
        notifier.update()
    except Exception:
        pass


def notify_windows(title, message, severity='medium', incident_key=None, incident_title=None):
    log_file(
        "WINDOWS_NOTIFY_START",
        f"incident_key={incident_key};incident_title={incident_title};severity={severity};title_len={len(str(title or ''))}"
    )
    sev = (severity or '').strip().lower()
    # High/critical keep attention on screen longer and with stronger title.
    timeout = 30 if sev in ('critical', 'high') else 15
    windows_title = f"[{sev.upper()}] {title}" if sev in ('critical', 'high') else title
    notified, actionable = _notify_windows_toast(windows_title, message, sev=sev, timeout=timeout, incident_key=incident_key, incident_title=incident_title)
    if notified:
        log_file("WINDOWS_NOTIFY_OK", f"incident_key={incident_key};severity={sev};actionable={actionable}")
        return True, actionable
    log_file("WINDOWS_NOTIFY_FALLBACK", f"incident_key={incident_key};severity={sev}")
    _notify_windows_plyer(windows_title, message, timeout)
    return False, False


def _notify_windows_toast(title, message, sev='medium', timeout=15, incident_key=None, incident_title=None):
    if os.name != 'nt':
        return False, False
    sev = (sev or '').strip().lower()
    is_urgent = sev in ('critical', 'high')
    scenario = 'urgent' if is_urgent else 'reminder'
    duration = 'long' if is_urgent else 'short'
    title_xml = html.escape(title or 'Sentinel')
    message_xml = html.escape(message or '')
    log_file("WINDOWS_TOAST_START", f"incident_key={incident_key};severity={sev};urgent={is_urgent};message_len={len(str(message or ''))}")

    # Native Windows Toast with action buttons (Confirm/Dismiss for critical & high).
    # Prefer winsdk if installed, then fallback to winrt namespace.
    try:
        try:
            from winsdk.windows.ui.notifications import ToastNotification, ToastNotificationManager
            from winsdk.windows.data.xml.dom import XmlDocument
        except Exception:
            from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager
            from winrt.windows.data.xml.dom import XmlDocument
        actions = ""
        if is_urgent:
            actions = (
                "<actions>"
                "<action content='Conferma' arguments='action=confirm&severity=" + sev + "' activationType='foreground'/>"
                "<action content='Ignora' arguments='action=dismiss&severity=" + sev + "' activationType='foreground'/>"
                "</actions>"
            )
        toast_xml = (
            "<toast"
            f" scenario='{scenario}' duration='{duration}' launch='sentinel-notify'>"
            "<visual><binding template='ToastGeneric'>"
            f"<text>{title_xml}</text>"
            f"<text>{message_xml}</text>"
            "</binding></visual>"
            f"{actions}"
            "<audio src='ms-winsoundevent:Notification.IM'/>"
            "</toast>"
        )
        doc = XmlDocument()
        doc.load_xml(toast_xml)
        notifier = ToastNotificationManager.create_toast_notifier("Sentinel.Notifier")
        notification = ToastNotification(doc)
        notifier.show(notification)
        log_file("WINDOWS_TOAST_OK", f"incident_key={incident_key};severity={sev};urgent={is_urgent};action_hooks={bool(is_urgent)}")
        return True, is_urgent
    except Exception as e:
        log_file("WINDOWS_TOAST_FAIL", f"severity={sev}; err={str(e)}")
        # Fallback with winotify (py package available on this environment).
        try:
            from winotify import Notification, audio
            winotify_notifier = _get_winotify_notifier()
            if winotify_notifier is not None:
                n = winotify_notifier.create_notification(
                    title=title,
                    msg=message,
                    duration='long' if is_urgent else 'short'
                )
                if is_urgent:
                    n.set_audio(audio.Default, False)
                else:
                    n.set_audio(audio.Silent, False)

                action_hooks = False
                if is_urgent:
                    on_conf = _winotify_action_handler('confirm', incident_key, incident_title, sev)
                    on_dismiss = _winotify_action_handler('dismiss', incident_key, incident_title, sev)
                    if on_conf is not None:
                        n.add_actions('Conferma', on_conf)
                        action_hooks = True
                    if on_dismiss is not None:
                        n.add_actions('Ignora', on_dismiss)
                        action_hooks = True

                n.show()
                log_file("WINDOWS_WINOTIFY_OK", f"incident_key={incident_key};severity={sev};action_hooks={action_hooks}")
                return True, action_hooks
        except Exception as e2:
            log_file("WINDOWS_TOAST_FAIL_WINOTIFY", f"severity={sev}; err={str(e2)}")
            return False, False

        return False, False


def _notify_windows_plyer(title, message, timeout):
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=timeout, app_name="Sentinel Notifier")
        log_file("WINDOWS_PLYER_OK", f"title={title}")
    except Exception:
        log_file("WINDOWS_PLYER_FAIL", f"title={title}")
        pass

class Storage:
    def __init__(self, path: Path):
        self.path = path
        self._db_lock = threading.RLock()
        self.init_db()

    def connect(self):
        con = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        con.execute("PRAGMA busy_timeout = 30000")
        return con

    def _with_db_retry(self, fn, *, max_attempts=6, base_delay=0.08):
        last_error = None
        for attempt in range(max_attempts):
            try:
                if attempt == 0:
                    log_file("DB_TX_START")
                with self._db_lock:
                    log_file("DB_LOCK_ACQUIRED")
                    with self.connect() as con:
                        t0 = time.perf_counter()
                        out = fn(con)
                        dt = int((time.perf_counter() - t0) * 1000)
                        log_file("DB_TX_OK", f"duration_ms={dt}")
                        return out
            except sqlite3.OperationalError as e:
                last_error = e
                if "database is locked" not in str(e).lower() or attempt == max_attempts - 1:
                    raise
                wait = base_delay * (2 ** attempt)
                log_file("DB_RETRY", f"attempt={attempt + 1};err={type(e).__name__};wait_ms={int(wait*1000)}")
                time.sleep(wait)
            finally:
                log_file("DB_TX_END")
        if last_error is not None:
            raise last_error

    def init_db(self):
        with self.connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS incidents(
                incident_key TEXT PRIMARY KEY, title TEXT, severity TEXT, status TEXT, owner TEXT,
                created_time TEXT, last_update_time TEXT, activated_at TEXT, activated_by_bot INTEGER DEFAULT 0,
                first_seen_active TEXT, first_alert_notified INTEGER DEFAULT 0, first_alert_notified_at TEXT,
                last_seen TEXT, sla_warning_sent INTEGER DEFAULT 0,
                last_sla_warning_at TEXT, workspace_hint TEXT, source_page TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS actions(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, incident_key TEXT, title TEXT,
                action TEXT, result TEXT, details TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY, value TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS ignored_incidents(
                incident_key TEXT PRIMARY KEY, ignored_at TEXT, reason TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS hidden_incidents(
                incident_key TEXT PRIMARY KEY, hidden_at TEXT, reason TEXT)''')

            cols = {row[1] for row in con.execute("PRAGMA table_info(incidents)").fetchall()}
            if 'first_alert_notified' not in cols:
                con.execute("ALTER TABLE incidents ADD COLUMN first_alert_notified INTEGER DEFAULT 0")
            if 'first_alert_notified_at' not in cols:
                con.execute("ALTER TABLE incidents ADD COLUMN first_alert_notified_at TEXT")

    def hidden_keys(self):
        with self.connect() as con:
            rows = {str(r[0]) for r in con.execute("SELECT incident_key FROM hidden_incidents").fetchall()}
            log_file("HIDDEN_KEYS", f"count={len(rows)}")
            return rows

    def is_hidden(self, key):
        return str(key or '').strip() in self.hidden_keys()

    def hide_incident(self, key, reason='manual'):
        key = str(key or '').strip()
        if not key:
            self.log_system('HIDE_INCIDENT', 'SKIP_EMPTY', '')
            return
        def _op(con):
            con.execute("INSERT OR REPLACE INTO hidden_incidents(incident_key, hidden_at, reason) VALUES(?,?,?)", (key, now_iso(), reason))
            con.execute("DELETE FROM incidents WHERE incident_key=?", (key,))
            con.execute("DELETE FROM actions WHERE incident_key=?", (key,))
        self._with_db_retry(_op)
        log_file("HIDE_INCIDENT_DB", f"key={key};reason={reason}")
        self.log_system('HIDE_INCIDENT', 'SUCCESS', f'key={key}; reason={reason}')

    def unhide_incident(self, key):
        key = str(key or '').strip()
        if not key:
            self.log_system('UNHIDE_INCIDENT', 'SKIP_EMPTY', '')
            return
        self._with_db_retry(lambda con: con.execute("DELETE FROM hidden_incidents WHERE incident_key=?", (key,)))
        log_file("UNHIDE_INCIDENT_DB", f"key={key}")
        self.log_system('UNHIDE_INCIDENT', 'SUCCESS', f'key={key}')
    def ignore_incident(self, key, reason='manual'):
        key = str(key or '').strip()
        if not key:
            self.log_system('IGNORE_INCIDENT', 'SKIP_EMPTY', '')
            return
        self._with_db_retry(lambda con: con.execute(
            "INSERT OR REPLACE INTO ignored_incidents(incident_key,ignored_at,reason) VALUES(?,?,?)",
            (key, now_iso(), reason)
        ))
        log_file("IGNORE_INCIDENT_DB", f"key={key};reason={reason}")
        self.log_system('IGNORE_INCIDENT', 'SUCCESS', f'ignored={key}; reason={reason}')

    def unignore_all(self):
        before = len(self.ignored_keys())
        self._with_db_retry(lambda con: con.execute("DELETE FROM ignored_incidents"))
        after = len(self.ignored_keys())
        log_file("UNIGNORE_ALL_DB", f"removed={before};remaining={after}")
        self.log_system('UNIGNORE_ALL', 'SUCCESS', '')

    def clear_runtime_data(self):
        def _safe_count(con, table):
            try:
                row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                return int(row[0]) if row else 0
            except Exception:
                return 0

        counts_before = {}
        counts_after = {}
        def _op(con):
            counts_before['incidents'] = _safe_count(con, 'incidents')
            counts_before['actions'] = _safe_count(con, 'actions')
            counts_before['ignored_incidents'] = _safe_count(con, 'ignored_incidents')
            counts_before['hidden_incidents'] = _safe_count(con, 'hidden_incidents')

            con.execute("DELETE FROM incidents")
            con.execute("DELETE FROM actions")
            con.execute("DELETE FROM ignored_incidents")
            con.execute("DELETE FROM hidden_incidents")

            counts_after['incidents'] = _safe_count(con, 'incidents')
            counts_after['actions'] = _safe_count(con, 'actions')
            counts_after['ignored_incidents'] = _safe_count(con, 'ignored_incidents')
            counts_after['hidden_incidents'] = _safe_count(con, 'hidden_incidents')

        self._with_db_retry(_op)
        log_file("DB_CLEAR", f"runtime tables cleared on startup | before={counts_before} | after={counts_after}")
        self.log_system('DB_CLEAR', 'SUCCESS', f"runtime tables cleared on startup | before={counts_before} | after={counts_after}")

    def ignored_keys(self):
        with self.connect() as con:
            rows = {str(r[0]) for r in con.execute("SELECT incident_key FROM ignored_incidents").fetchall()}
            log_file("IGNORED_KEYS", f"count={len(rows)}")
            return rows

    def is_ignored(self, key):
        return str(key or '').strip() in self.ignored_keys()

    def load_settings(self):
        log_file("DB_LOAD_SETTINGS", "start")
        with self.connect() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT key,value FROM settings").fetchall()
        payload = {r['key']: r['value'] for r in rows}
        log_file("DB_LOAD_SETTINGS", f"count={len(payload)}")
        return payload
    def save_settings(self, settings):
        if not isinstance(settings, dict):
            log_file("DB_SAVE_SETTINGS", "skip_non_dict")
            return
        log_file("DB_SAVE_SETTINGS", f"count={len(settings)}")
        def _op(con):
            for k,v in settings.items():
                con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(k), str(v)))
        self._with_db_retry(_op)
        log_file("DB_SAVE_SETTINGS", f"ok count={len(settings)}")

    def log_action(self, key, title, action, result, details=""):
        def _op(con):
            con.execute(
                "INSERT INTO actions(ts,incident_key,title,action,result,details) VALUES(?,?,?,?,?,?)",
                (now_iso(), key, title, action, result, details)
            )
        self._with_db_retry(_op)
        try:
            log_file("DB_LOG_ACTION", f"incident={key};action={action};result={result};details={details}")
        except Exception:
            pass

    def log_system(self, action, result, details=""):
        try:
            self.log_action("__SYSTEM__", "System", action, result, details)
        except Exception as e:
            log_file("DB_LOG_SYSTEM_FAILED", f"{action} {result} {details}", e)
    def upsert_seen(self, key, title, severity, status, owner, created="", last_update="", workspace="", source=""):
        if self.is_hidden(key):
            log_file("UPSERT_SEEN_SKIPPED_HIDDEN", f"key={key}")
            return
        ts = now_iso(); first_active = ts if (status or '').lower() == 'active' else None
        log_file("UPSERT_SEEN", f"key={key};status={status};owner={owner};severity={severity};workspace={workspace};source={source}")
        def _op(con):
            con.execute('''INSERT INTO incidents(incident_key,title,severity,status,owner,created_time,last_update_time,first_seen_active,workspace_hint,source_page)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(incident_key) DO UPDATE SET
                title=excluded.title, severity=COALESCE(NULLIF(excluded.severity,''),incidents.severity),
                    status=COALESCE(NULLIF(excluded.status,''),incidents.status),
                    owner=COALESCE(NULLIF(excluded.owner,''),incidents.owner),
                    created_time=COALESCE(NULLIF(excluded.created_time,''),incidents.created_time),
                last_update_time=COALESCE(NULLIF(excluded.last_update_time,''),incidents.last_update_time),
                first_seen_active=CASE WHEN excluded.status='Active' THEN COALESCE(incidents.first_seen_active, excluded.first_seen_active) ELSE incidents.first_seen_active END,
                workspace_hint=COALESCE(NULLIF(excluded.workspace_hint,''),incidents.workspace_hint),
                source_page=COALESCE(NULLIF(excluded.source_page,''),incidents.source_page)''',
                (key,title,severity,status,owner,created,last_update,first_active,workspace,source))
        self._with_db_retry(_op)

    def mark_activated(self, key, title, severity="", created="", last_update="", workspace="", source=""):
        if self.is_hidden(key):
            log_file("MARK_ACTIVE_SKIPPED_HIDDEN", f"key={key}")
            return
        ts = now_iso()
        log_file("MARK_ACTIVATED", f"key={key};severity={severity};workspace={workspace};source={source}")
        def _op(con):
            con.execute('''INSERT INTO incidents(incident_key,title,severity,status,owner,created_time,last_update_time,activated_at,activated_by_bot,first_seen_active,workspace_hint,source_page)
                VALUES(?,?,?,'Active','me',?,?,?,?,1,?,?)
                ON CONFLICT(incident_key) DO UPDATE SET title=excluded.title, severity=COALESCE(NULLIF(excluded.severity,''),incidents.severity),
                status='Active', owner='me', created_time=COALESCE(NULLIF(excluded.created_time,''),incidents.created_time),
                last_update_time=COALESCE(NULLIF(excluded.last_update_time,''),incidents.last_update_time),
                activated_at=COALESCE(incidents.activated_at,excluded.activated_at), activated_by_bot=1,
                first_seen_active=COALESCE(incidents.first_seen_active,excluded.first_seen_active),
                workspace_hint=COALESCE(NULLIF(excluded.workspace_hint,''),incidents.workspace_hint), source_page=COALESCE(NULLIF(excluded.source_page,''),incidents.source_page)''',
                (key,title,severity,created,last_update,ts,ts,workspace,source))
        self._with_db_retry(_op)

    def sync_visible_incidents(self, visible_keys, clear_when_empty=False):
        """
        Keep the local dashboard aligned with the current Sentinel Incidents grid.

        If an incident is no longer visible in the current Sentinel Incidents list,
        it is removed from the local dashboard and will not generate further SLA notifications.

        Safety:
        - clear_when_empty=False preserves local state when parsing returns an empty list.
        - clear_when_empty=True is used only when parser returns a non-empty view.
        """
        keys = [str(k) for k in visible_keys if k]
        sync_status = {
            "status": "SUCCESS",
            "details": ""
        }

        def _op(con):
            if not keys:
                if clear_when_empty:
                    stale = [str(r[0]) for r in con.execute("SELECT incident_key FROM incidents").fetchall()]
                    sync_status["status"] = "CLEARED_EMPTY_VIEW"
                    sync_status["details"] = f"No visible incidents in current Sentinel view; removed={len(stale)}"
                    con.execute("DELETE FROM incidents")
                    con.execute("DELETE FROM actions")
                    con.execute("DELETE FROM ignored_incidents")
                    con.execute("DELETE FROM hidden_incidents")
                else:
                    sync_status["status"] = "SKIP_EMPTY_UNSAFE"
                    sync_status["details"] = "Visible incident list empty and clear_when_empty=False"
                return sync_status["status"], sync_status["details"]

            placeholders = ",".join(["?"] * len(keys))
            stale = [str(r[0]) for r in con.execute(f"SELECT incident_key FROM incidents WHERE incident_key NOT IN ({placeholders})", keys).fetchall()]
            con.execute(f"DELETE FROM incidents WHERE incident_key NOT IN ({placeholders})", keys)
            if stale:
                stale_placeholders = ",".join(["?"] * len(stale))
                con.execute(f"DELETE FROM actions WHERE incident_key IN ({stale_placeholders})", stale)
                con.execute(f"DELETE FROM ignored_incidents WHERE incident_key IN ({stale_placeholders})", stale)
                con.execute(f"DELETE FROM hidden_incidents WHERE incident_key IN ({stale_placeholders})", stale)

            # Ignored incidents must never reappear in the dashboard.
            try:
                ignored = [r[0] for r in con.execute("SELECT incident_key FROM ignored_incidents").fetchall()]
                if ignored:
                    ignored_placeholders = ",".join(["?"] * len(ignored))
                    con.execute(f"DELETE FROM incidents WHERE incident_key IN ({ignored_placeholders})", ignored)
            except Exception as e:
                log_file("SYNC_VISIBLE_IGNORED_SKIP", f"err={type(e).__name__}:{e}")

            removed_count = len(stale)
            log_file("SYNC_VISIBLE", f"visible_count={len(keys)};removed_count={removed_count}")
            sync_status["details"] = f"visible_count={len(keys)};removed_count={removed_count}"
            return sync_status["status"], sync_status["details"]

        status, details = self._with_db_retry(_op)
        self.log_system('SYNC_VISIBLE', status, details)

    def incidents(self, limit=500):

        with self.connect() as con:
            con.row_factory = sqlite3.Row
            ignored = self.ignored_keys()
            hidden = self.hidden_keys()
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM incidents ORDER BY COALESCE(last_seen, last_update_time, created_time, activated_at, first_seen_active, '') DESC LIMIT ?",
                (limit,)
            ).fetchall()]
            visible = [r for r in rows if str(r.get('incident_key')) not in ignored and str(r.get('incident_key')) not in hidden]
            log_file("DB_LIST_INCIDENTS", f"limit={limit};fetched={len(rows)};visible={len(visible)}")
            return visible
    def active_incidents(self):
        with self.connect() as con:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute("SELECT * FROM incidents WHERE status='Active' ORDER BY COALESCE(activated_at,first_seen_active) ASC").fetchall()]
            log_file("DB_LIST_ACTIVE", f"count={len(rows)}")
            return rows
    def actions(self, limit=100):
        with self.connect() as con:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
            log_file("DB_LIST_ACTIONS", f"count={len(rows)}")
            return rows
    def mark_sla_warning(self, key):
        log_file("MARK_SLA_WARNING", f"key={str(key or '').strip()}")
        self._with_db_retry(lambda con: con.execute(
            "UPDATE incidents SET sla_warning_sent=1,last_sla_warning_at=? WHERE incident_key=?",
            (local_now_iso(), key)
        ))

    def mark_first_alert_notified(self, key):
        if not (str(key or '').strip()):
            log_file("MARK_FIRST_ALERT_NOTIFIED", "SKIP_EMPTY")
            return
        log_file("MARK_FIRST_ALERT_NOTIFIED", f"key={str(key).strip()}")
        self._with_db_retry(lambda con: con.execute(
            "UPDATE incidents SET first_alert_notified=1, first_alert_notified_at=? WHERE incident_key=?",
            (local_now_iso(), str(key).strip())
        ))

    def mark_last_seen(self, key, when_iso=None):
        if not (str(key or '').strip()):
            log_file("MARK_LAST_SEEN", "SKIP_EMPTY")
            return
        ts = (when_iso or local_now_iso()).strip()
        if not ts:
            log_file("MARK_LAST_SEEN", f"key={str(key).strip()};SKIP_EMPTY_TS")
            return
        log_file("MARK_LAST_SEEN", f"key={str(key).strip()};ts={ts}")
        self._with_db_retry(lambda con: con.execute(
            "UPDATE incidents SET last_seen=? WHERE incident_key=?",
            (ts, str(key).strip())
        ))

    def delete_incident(self, key, reason='manual'):
        key = str(key or '').strip()
        if not key:
            log_file("DELETE_INCIDENT", "SKIP_EMPTY")
            return
        def _op(con):
            con.execute("DELETE FROM incidents WHERE incident_key=?", (key,))
            con.execute("DELETE FROM actions WHERE incident_key=?", (key,))
            con.execute("DELETE FROM hidden_incidents WHERE incident_key=?", (key,))
            con.execute("DELETE FROM ignored_incidents WHERE incident_key=?", (key,))
        self._with_db_retry(_op)
        log_file("DELETE_INCIDENT_DB", f"key={key};reason={reason}")
        self.log_system('DELETE_INCIDENT', 'SUCCESS', f'key={key}; reason={reason}')

@dataclass
class RuntimeSettings:
    # Taking Charge Time KPI: time to take ownership/assign the incident.
    scan_interval_seconds:int=60
    sla_critical_minutes:int=30; sla_high_minutes:int=30; sla_medium_minutes:int=60; sla_low_minutes:int=60; sla_informational_minutes:int=60
    # Resolution Time KPI: time to close / complete remediation for the incident.
    resolution_critical_minutes:int=60; resolution_high_minutes:int=120; resolution_medium_minutes:int=480; resolution_low_minutes:int=720; resolution_informational_minutes:int=720
    misclassification_percent:int=1

    # Notification Time KPI: customer/user notification timing. Popup notifications are based on this KPI.
    notification_critical_minutes:int=30; notification_high_minutes:int=60; notification_medium_minutes:int=240; notification_low_minutes:int=480; notification_informational_minutes:int=480
    notification_warning_percent:int=75
    notification_repeat_minutes:int=30

    auto_fetch_interval_seconds:int=60; my_owner_identity:str=''

    def severity_key(self, sev):
        s=(sev or '').strip().lower()
        if s in ['critical','high','medium','low','informational']:
            return s
        return 'medium'

    def sla_for(self, sev):
        # Backward-compatible name: this is Taking Charge SLA.
        s=self.severity_key(sev)
        return self.sla_critical_minutes if s=='critical' else self.sla_high_minutes if s=='high' else self.sla_medium_minutes if s=='medium' else self.sla_low_minutes if s=='low' else self.sla_informational_minutes

    def notification_for(self, sev):
        s=self.severity_key(sev)
        return self.notification_critical_minutes if s=='critical' else self.notification_high_minutes if s=='high' else self.notification_medium_minutes if s=='medium' else self.notification_low_minutes if s=='low' else self.notification_informational_minutes

    def warning_at(self, sev):
        # Popup warning is now based directly on Notification Time KPI, not on % of Taking Charge.
        warn_pct = clamp_int(self.notification_warning_percent, 75, 1, 100)
        return max(1, int(math.ceil(self.notification_for(sev) * warn_pct / 100)))


def sla_due_from_created(created_time: str, severity: str, settings: RuntimeSettings) -> str:
    """
    SLA breach timestamp based on Sentinel Creation time, not activated_at.
    """
    if not created_time:
        return "-"
    return add_minutes_to_sentinel_datetime(created_time, settings.sla_for(severity))


def sla_notify_from_created(created_time: str, severity: str, settings: RuntimeSettings) -> str:
    """
    Warning timestamp based on percentage threshold, e.g. 60% of SLA from Created.
    """
    if not created_time:
        return "-"
    return add_minutes_to_sentinel_datetime(created_time, settings.warning_at(severity))

def runtime_settings_from_storage(store):
    s = RuntimeSettings()
    saved = store.load_settings()
    log_file("RUNTIME_SETTINGS_LOAD", f"stored_count={len(saved)}")

    for key in [
        'scan_interval_seconds',
        'sla_critical_minutes','sla_high_minutes','sla_medium_minutes','sla_low_minutes','sla_informational_minutes',
        'resolution_critical_minutes','resolution_high_minutes','resolution_medium_minutes','resolution_low_minutes','resolution_informational_minutes',
        'misclassification_percent',
        'notification_critical_minutes','notification_high_minutes','notification_medium_minutes','notification_low_minutes','notification_informational_minutes',
        'notification_warning_percent','notification_repeat_minutes','auto_fetch_interval_seconds'
    ]:
        default = getattr(s, key)
        if key in saved:
            if key == 'auto_fetch_interval_seconds':
                lo, hi = 30, 3600
            elif key == 'scan_interval_seconds':
                lo, hi = 30, 3600
            elif key == 'misclassification_percent':
                lo, hi = 0, 100
            elif key == 'notification_warning_percent':
                lo, hi = 1, 100
            elif key == 'notification_repeat_minutes':
                lo, hi = 1, 10080
        else:
            lo, hi = 1, 10080
        setattr(s, key, clamp_int(saved.get(key), default, lo, hi))
        if key in saved:
            log_file("RUNTIME_SETTING_APPLIED", f"{key}={getattr(s, key)};source={saved.get(key)}")

    s.my_owner_identity = saved.get('my_owner_identity', '') or ''
    log_file("RUNTIME_SETTINGS_DONE", f"my_owner={s.my_owner_identity};scan={s.scan_interval_seconds};auto_fetch={s.auto_fetch_interval_seconds}")
    return s

class SentinelPageMonitor:
    def __init__(self, page, store, settings):
        self.page = page
        self.store = store
        self.settings = settings
        self.can_continue = lambda: True

    def wait(self, ms=1000):
        self.page.wait_for_timeout(ms)

    def body(self):
        try:
            return self.page.locator('body').inner_text(timeout=4000)
        except Exception:
            return ''

    def is_incidents_page(self):
        try:
            url = (self.page.url or '').lower()
            if 'portal.azure.com' in url or 'security.microsoft.com' in url or 'sentinel' in url:
                return True
        except Exception:
            pass
        try:
            title = (self.page.title() or '').lower()
            if 'sentinel' in title and 'incident' in title:
                return True
        except Exception:
            pass
        t = self.body().lower()
        return 'sentinel' in t and 'incident' in t

    def workspace_hint(self):
        url = self.page.url or ''
        title = ''
        try:
            title = self.page.title()
        except Exception:
            pass
        m = re.search(r"workspaces?/([^/?#]+)", url, re.I)
        return m.group(1) if m else (title[:80] if title else 'unknown')

    def parse_row_identity(self, txt):
        text = normalize_text(txt)
        severity = ''

        # Prefer the actual row shape: severity immediately before the incident ID.
        # Page-level KPI text can contain "High (0) Medium (1)" before the row body,
        # so taking the first severity word from the whole string is unsafe.
        m = re.search(
            r"\b(Critical|High|Medium|Low|Informational)\b\s+(\d{3,})\b\s+(.+?)(?:\s+\d+\s+Microsoft|\s+Microsoft|\s+\d{1,2}/\d{1,2}/\d{2,4})",
            text,
            re.I
        )
        if m:
            return m.group(2), normalize_text(m.group(3)), m.group(1).title()

        m = re.search(r"\b(Critical|High|Medium|Low|Informational)\b\s+(\d{3,})\b", text, re.I)
        if m:
            key = m.group(2)
            idx = text.find(key)
            return key, (text[idx + len(key):].strip()[:160] or key), m.group(1).title()

        for sev in ['Critical', 'High', 'Medium', 'Low', 'Informational']:
            if re.search(rf"\b{sev}\b", text, re.I):
                severity = sev
                break

        # Typical Sentinel row:
        # Informational 18831 Multi-stage incident ...
        m = re.search(
            r"\b(Critical|High|Medium|Low|Informational)\b\s+(\d{3,})\s+(.+?)(?:\s+\d+\s+Microsoft|\s+Microsoft|\s+\d{1,2}/\d{1,2}/\d{2,4})",
            text,
            re.I
        )
        if m:
            return m.group(2), normalize_text(m.group(3)), m.group(1).title()

        m = re.search(r"\b(\d{3,})\b", text)
        if m:
            key = m.group(1)
            idx = text.find(key)
            return key, (text[idx + len(key):].strip()[:160] or key), severity

        return None, '', severity

    def visible_incident_snapshot(self, max_rows=80, row_text_timeout_ms=800):
        """
        Snapshot iniziale degli incident visibili.
        Salva gli ID prima di fare qualsiasi click. Cosi', se una riga sparisce,
        cambia posizione o la lista si riordina dopo l'assegnazione, il monitor lavora
        comunque per ID e non per indice statico.
        """
        rows = self.page.get_by_role('row')
        out = []
        seen = set()
        log_file("SNAPSHOT_START", f"max_rows={max_rows};timeout={row_text_timeout_ms}")

        try:
            texts = rows.all_inner_texts()
            texts = [t for t in texts[:max_rows] if t]
            for txt in texts:
                t = txt.lower()
                if 'incident number' in t:
                    continue
                key, title, severity = self.parse_row_identity(txt)
                if key and key not in seen:
                    seen.add(key)
                    out.append({
                        'incident_key': key,
                        'title': title or key,
                        'severity': severity,
                    })
            if out:
                log_file("SNAPSHOT_OK", f"rows={len(out)};source=all_inner_texts")
                return out
        except Exception:
            log_file("SNAPSHOT_TEXT_FAIL", "rows fallback to per-row path")

        try:
            count = min(rows.count(), max_rows)
        except Exception:
            return out

        for i in range(count):
            try:
                txt = rows.nth(i).inner_text(timeout=row_text_timeout_ms)
            except Exception:
                continue

            if 'incident number' in txt.lower():
                continue

            key, title, severity = self.parse_row_identity(txt)
            if key and key not in seen:
                seen.add(key)
                out.append({
                    'incident_key': key,
                    'title': title or key,
                    'severity': severity,
                })

        log_file("SNAPSHOT_OK", f"rows={len(out)};source=per_row")
        return out

    def current_view_reports_no_incidents(self):
        """
        Return True only when the loaded Sentinel page explicitly looks empty.
        A parsing failure or half-loaded grid must not wipe local runtime state.
        """
        text = normalize_text(self.body()).lower()
        if not text:
            return False

        empty_markers = [
            'no incidents',
            'no results',
            'no items to show',
            'there are no incidents',
            'nessun incident',
            'nessun risultato',
        ]
        if any(marker in text for marker in empty_markers):
            return True

        if re.search(r"\b0\s+open incidents\b", text, re.I):
            return True
        if re.search(r"\bopen incidents\s+0\b", text, re.I):
            return True
        if re.search(r"\b0\s+active incidents\b", text, re.I) and re.search(r"\b0\s+new incidents\b", text, re.I):
            return True

        return False

    def find_row_index_by_incident_id(self, incident_key, max_rows=120):
        """
        Cerca dinamicamente la riga con l'ID richiesto nella vista corrente.
        Non usa l'indice vecchio, perche' dopo assign/status la lista puo' cambiare.
        """
        rows = self.page.get_by_role('row')
        try:
            count = min(rows.count(), max_rows)
        except Exception:
            return None

        for i in range(count):
            try:
                txt = rows.nth(i).inner_text(timeout=1200)
            except Exception:
                continue

            key, _title, _severity = self.parse_row_identity(txt)
            if key == incident_key:
                return i

        return None

    def panel_text(self, full, key):
        """
        Extract right detail pane text.

        The incident ID appears both in the grid row and in the right detail pane.
        Using the first ID occurrence can parse table headers as fields.
        """
        if not key:
            return full

        pattern = re.compile(rf"Incident number\s*{re.escape(str(key))}", re.I)
        matches = list(pattern.finditer(full))
        if matches:
            idx = matches[-1].start()
            return full[max(0, idx - 800):min(len(full), idx + 5000)]

        positions = [m.start() for m in re.finditer(rf"\b{re.escape(str(key))}\b", full)]
        if positions:
            idx = positions[-1]
            return full[max(0, idx - 800):min(len(full), idx + 5000)]

        return full

    def panel_matches_id(self, panel, incident_key):
        if not incident_key:
            return False
        return re.search(rf"\b{re.escape(str(incident_key))}\b", panel) is not None

    def near_label(self, lines, label):
        lab = label.lower()
        bad_values = {
            'severity', 'status', 'owner', 'incident number', 'created time',
            'creation time', 'last update time', 'title', 'alerts', 'incident provider name',
            'alert product name'
        }
        for i, line in enumerate(lines):
            if line.lower() == lab:
                # Sentinel detail pane usually renders Value above Label.
                for j in [i - 1, i + 1]:
                    if 0 <= j < len(lines):
                        candidate = lines[j]
                        c = candidate.lower()
                        if c != lab and c not in bad_values and len(candidate) <= 160:
                            return candidate
        return ''

    def details(self, panel):
        lines = [normalize_text(x) for x in panel.splitlines() if normalize_text(x)]
        compact = normalize_text(panel)
        compact_lines = panel.splitlines()

        status = ''
        owner = ''
        severity = ''
        created = ''
        last_update = ''

        for c in ['New', 'Active', 'Closed']:
            if re.search(rf"\b{c}\b\s+Status\b", compact, re.I) or re.search(rf"\bStatus\b\s+{c}\b", compact, re.I):
                status = c
                break

        if not status:
            n = self.near_label(lines, 'Status')
            status = n.title() if n.lower() in ['new', 'active', 'closed'] else 'Unknown'

        if re.search(r"\bUnassigned\b\s+Owner\b", compact, re.I) or re.search(r"\bOwner\b\s+Unassigned\b", compact, re.I):
            owner = 'Unassigned'
        else:
            owner = self.near_label(lines, 'Owner') or 'Unknown'

        for sev in ['Critical', 'High', 'Medium', 'Low', 'Informational']:
            if re.search(rf"\b{sev}\b\s+Severity\b", compact, re.I) or re.search(rf"\bSeverity\b\s+{sev}\b", compact, re.I):
                severity = sev
                break

        if not severity:
            n = self.near_label(lines, 'Severity')
            severity = n.title() if n.title() in ['Critical', 'High', 'Medium', 'Low', 'Informational'] else ''

        for i, line in enumerate(lines):
            if line.lower() == 'creation time' and i + 1 < len(lines):
                created = lines[i + 1]
            if not created and line.lower() in {'created time', 'created'} and i + 1 < len(lines):
                created = lines[i + 1]
            if line.lower() == 'last update time' and i + 1 < len(lines):
                last_update = lines[i + 1]

        if not status and compact_lines:
            # Fallback label parsing when the panel uses inline text (`Status: Active`).
            m = re.search(r"\bStatus\s*[:\-]?\s*([A-Za-z]+)\b", panel, re.I)
            if m:
                status = m.group(1).strip().title()

        if not owner or owner == 'Unknown':
            m = re.search(r"\bOwner\s*[:\-]?\s*([^\n\r;]{1,120})", panel, re.I)
            if m:
                owner = normalize_text(m.group(1))

        if not severity:
            m = re.search(r"\bSeverity\s*[:\-]?\s*([A-Za-z]+)\b", panel, re.I)
            if m:
                s = normalize_text(m.group(1)).title()
                if s in ['Critical', 'High', 'Medium', 'Low', 'Informational']:
                    severity = s

        if not created:
            for pat in [r"\bCreation\s*time\s*[:\-]?\s*([^\n\r;]{4,120})", r"\bCreated\s*time\s*[:\-]?\s*([^\n\r;]{4,120})", r"\bCreated\s*[:\-]?\s*([^\n\r;]{4,120})"]:
                m = re.search(pat, panel, re.I)
                if m:
                    created = normalize_text(m.group(1))
                    break

        if not last_update:
            m = re.search(r"\bLast\s*update\s*time\s*[:\-]?\s*([^\n\r;]{4,120})", panel, re.I)
            if m:
                last_update = normalize_text(m.group(1))

        return {
            'status': status,
            'owner': owner,
            'severity': severity,
            'created_time': created,
            'last_update_time': last_update,
        }

    def read_open_incident_details(self, expected_key):
        """
        Legge il detail pane e conferma che l'incident aperto sia quello atteso.
        """
        full = self.body()
        panel = self.panel_text(full, expected_key)

        if not self.panel_matches_id(panel, expected_key):
            return None, None

        return panel, self.details(panel)

    def open_incident_by_id(self, incident_key):
        """
        Apre dinamicamente la riga con ID specifico e verifica che il detail pane
        contenga lo stesso ID.
        """
        idx = self.find_row_index_by_incident_id(incident_key)
        if idx is None:
            return None, None

        rows = self.page.get_by_role('row')
        try:
            rows.nth(idx).click()
        except Exception:
            return None, None

        self.wait(1000)
        return self.read_open_incident_details(incident_key)

    def safe_locator_click(self, locator, timeout=1000):
        """
        Sentinel often keeps hidden duplicated text nodes in the DOM.
        Click only visible locators and never raise a timeout to the UI.
        """
        try:
            if not locator.is_visible(timeout=timeout):
                return False
        except Exception:
            return False

        try:
            locator.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass

        try:
            locator.click(timeout=timeout)
            return True
        except Exception:
            return False

    def click_text(self, texts, exact_first=True, timeout=2000):
        for txt in texts:
            locators_to_try = []

            if exact_first:
                try:
                    loc = self.page.get_by_text(txt, exact=True)
                    count = min(loc.count(), 30)
                    for i in reversed(range(count)):
                        locators_to_try.append(loc.nth(i))
                except Exception:
                    pass

            try:
                loc = self.page.get_by_text(txt, exact=False)
                count = min(loc.count(), 30)
                for i in reversed(range(count)):
                    locators_to_try.append(loc.nth(i))
            except Exception:
                pass

            for loc in locators_to_try:
                if self.safe_locator_click(loc, timeout=min(timeout, 1200)):
                    return True

        return False

    def click_button_text(self, texts, timeout=2500):
        for txt in texts:
            locators_to_try = []

            try:
                loc = self.page.get_by_role('button', name=re.compile(re.escape(txt), re.I))
                count = min(loc.count(), 20)
                for i in reversed(range(count)):
                    locators_to_try.append(loc.nth(i))
            except Exception:
                pass

            try:
                loc = self.page.get_by_text(txt, exact=True)
                count = min(loc.count(), 20)
                for i in reversed(range(count)):
                    locators_to_try.append(loc.nth(i))
            except Exception:
                pass

            for loc in locators_to_try:
                if self.safe_locator_click(loc, timeout=min(timeout, 1200)):
                    return True

        return False

    def apply_open_panel_if_present(self, timeout=2500):
        """
        Sentinel Owner picker requires Apply. Some Status dropdowns do not.
        We call this only immediately after opening/selecting inside a picker, not globally.
        """
        if self.click_button_text(['Apply', 'Applica'], timeout=timeout):
            self.wait(1000)
            return True
        return False

    def wait_until_owner_assigned(self, incident_key, max_attempts=5):
        """
        Verifica reale dalla UI: owner non deve piu' essere Unassigned.
        """
        last_details = None
        for _ in range(max_attempts):
            self.wait(700)
            panel, d = self.read_open_incident_details(incident_key)
            if panel is None or d is None:
                continue
            last_details = d
            if not self.owner_is_unassigned(d.get('owner')):
                return True, d
        return False, last_details

    def wait_until_status_active(self, incident_key, max_attempts=5):
        """
        Verifica reale dalla UI: status deve diventare Active.
        """
        last_details = None
        for _ in range(max_attempts):
            self.wait(700)
            panel, d = self.read_open_incident_details(incident_key)
            if panel is None or d is None:
                continue
            last_details = d
            if self.status_is_active(d.get('status')):
                return True, d
        return False, last_details

    def detail_pane_min_x(self):
        """
        Estimate the x position where the Sentinel detail pane starts.
        This avoids using fixed screen percentages and works better with different zoom/screen sizes.
        """
        viewport = self.page.viewport_size or {'width': 1600, 'height': 900}
        fallback = viewport['width'] * 0.78

        candidates = []
        for txt in ['Incident number', 'Investigate in Microsoft Defender XDR', 'Incident workbook', 'Analytics rule']:
            try:
                loc = self.page.get_by_text(txt, exact=False)
                count = min(loc.count(), 10)
                for i in range(count):
                    box = loc.nth(i).bounding_box(timeout=500)
                    if box and box['x'] > viewport['width'] * 0.45:
                        candidates.append(box['x'])
            except Exception:
                pass

        if candidates:
            return max(0, min(candidates) - 80)

        return fallback

    def click_field_value_by_label(self, label, value_texts, timeout=1200):
        """
        Click the value associated with a field label in the Sentinel right detail pane.
        Example:
            label='Status', value_texts=['New']
            label='Owner',  value_texts=['Unassigned']
        The click is based on actual DOM element positions, not fixed coordinates.
        """
        viewport = self.page.viewport_size or {'width': 1600, 'height': 900}
        pane_min_x = self.detail_pane_min_x()

        label_boxes = []
        try:
            labels = self.page.get_by_text(label, exact=True)
            count = min(labels.count(), 20)
            for i in range(count):
                box = labels.nth(i).bounding_box(timeout=timeout)
                if not box:
                    continue
                # Detail-pane label, not table header.
                if box['x'] >= pane_min_x and box['y'] < viewport['height'] * 0.55:
                    label_boxes.append(box)
        except Exception:
            pass

        # Pick the upper/right detail label.
        label_boxes.sort(key=lambda b: (b['y'], b['x']))

        for lbox in label_boxes:
            best = None
            best_score = 999999

            for value in value_texts:
                try:
                    loc = self.page.get_by_text(value, exact=True)
                    count = min(loc.count(), 30)
                except Exception:
                    count = 0

                for i in range(count):
                    try:
                        item = loc.nth(i)
                        if not item.is_visible(timeout=min(timeout, 500)):
                            continue
                        vbox = item.bounding_box(timeout=timeout)
                        if not vbox:
                            continue

                        # Value is usually above the label and roughly same x range.
                        near_x = (lbox['x'] - 140) <= vbox['x'] <= (lbox['x'] + lbox['width'] + 180)
                        near_y = (lbox['y'] - 90) <= vbox['y'] <= (lbox['y'] + 8)
                        in_pane = vbox['x'] >= pane_min_x

                        if in_pane and near_x and near_y:
                            score = abs((vbox['x'] + vbox['width'] / 2) - (lbox['x'] + lbox['width'] / 2)) + abs(vbox['y'] - lbox['y'])
                            if score < best_score:
                                best_score = score
                                best = item
                    except Exception:
                        continue

            if best is not None:
                if self.safe_locator_click(best, timeout=min(timeout, 1000)):
                    self.wait(300)
                    return True

            # Last resort relative to label: click just above the label.
            try:
                self.page.mouse.click(lbox['x'] + lbox['width'] / 2, max(0, lbox['y'] - 24))
                self.wait(300)
                return True
            except Exception:
                pass

        return False

    def click_text_in_right_pane(self, texts, exact_first=True, timeout=1200, max_y_ratio=0.55):
        """
        Clicks visible text only if it is in Sentinel right detail pane / popup area.
        This avoids clicking 'New' or 'Active' from the incident table or counters.
        """
        viewport = self.page.viewport_size or {'width': 1600, 'height': 900}
        min_x = self.detail_pane_min_x()
        max_y = viewport['height'] * max_y_ratio

        for txt in texts:
            loc = self.page.get_by_text(txt, exact=exact_first)
            try:
                count = min(loc.count(), 25)
            except Exception:
                count = 0

            for i in range(count):
                try:
                    item = loc.nth(i)
                    if not item.is_visible(timeout=min(timeout, 500)):
                        continue
                    box = item.bounding_box(timeout=timeout)
                    if not box:
                        continue
                    if box['x'] >= min_x and box['y'] <= max_y:
                        if self.safe_locator_click(item, timeout=min(timeout, 1000)):
                            return True
                except Exception:
                    continue

            # contains fallback
            if not exact_first:
                continue
            loc = self.page.get_by_text(txt, exact=False)
            try:
                count = min(loc.count(), 25)
            except Exception:
                count = 0

            for i in range(count):
                try:
                    item = loc.nth(i)
                    if not item.is_visible(timeout=min(timeout, 500)):
                        continue
                    box = item.bounding_box(timeout=timeout)
                    if not box:
                        continue
                    if box['x'] >= min_x and box['y'] <= max_y:
                        if self.safe_locator_click(item, timeout=min(timeout, 1000)):
                            return True
                except Exception:
                    continue

        return False

    def click_toolbar_refresh(self):
        """
        Refreshes Sentinel incidents grid after a successful status change.
        Prefer the Sentinel toolbar Refresh button; fallback to browser reload only if not found.
        """
        try:
            btn = self.page.get_by_role('button', name=re.compile('Refresh', re.I)).first
            btn.wait_for(state='visible', timeout=1200)
            btn.click(timeout=1200)
            self.wait(1200)
            return True
        except Exception:
            pass

        try:
            self.page.reload(wait_until='domcontentloaded')
            self.wait(1800)
            return True
        except Exception:
            return False

    def click_owner_fallback(self):
        # Zoom/screen safe: locate Owner label and click its value above it.
        if self.click_field_value_by_label('Owner', ['Unassigned', 'Non assegnato'], timeout=1200):
            return
        # Fallback: click any Unassigned text in the actual detail pane.
        self.click_text_in_right_pane(['Unassigned', 'Non assegnato'], exact_first=True, timeout=1200, max_y_ratio=0.55)
        self.wait(120)

    def click_status_fallback(self):
        # Zoom/screen safe: locate Status label and click its value above it.
        if self.click_field_value_by_label('Status', ['New'], timeout=1200):
            return
        # Fallback: click any New text in the actual detail pane.
        self.click_text_in_right_pane(['New'], exact_first=True, timeout=1200, max_y_ratio=0.55)
        self.wait(120)

    def normalize_owner_text(self, owner):
        return re.sub(r"\s+", " ", (owner or "").strip()).lower()

    def owner_is_me(self, owner):
        owner_norm = self.normalize_owner_text(owner)
        known_me = self.normalize_owner_text(getattr(self.settings, 'my_owner_identity', ''))
        if not owner_norm or owner_norm in ['unknown', '-']:
            return False
        if self.owner_is_unassigned(owner):
            return False
        if not known_me:
            return False
        return owner_norm == known_me

    def owner_is_unassigned(self, owner):
        owner_l = (owner or '').lower()
        return 'unassigned' in owner_l or 'non assegnato' in owner_l

    def status_is_new(self, status):
        return (status or '').lower() == 'new'

    def status_is_active(self, status):
        return (status or '').lower() == 'active'

    def WORKFLOW_STEP_current_open_id(self, incident_key):
        """
        Assegna solo l'incident attualmente aperto e poi verifica davvero dalla UI.

        Importante:
        nel picker Owner di Sentinel non basta cliccare 'Assign to me';
        bisogna premere Apply. Senza Apply l'incident resta Unassigned.
        """
        before_panel, before_details = self.read_open_incident_details(incident_key)
        if before_panel is None or before_details is None:
            return False, 'ID mismatch before assign'

        if not self.owner_is_unassigned(before_details.get('owner')):
            return True, before_details

        # Apri menu owner.
        self.click_owner_fallback()
        self.wait(500)

        if not self.click_text_in_right_pane(['Assign to me', 'Assign to myself', 'Assegna a me'], exact_first=False, timeout=1400, max_y_ratio=0.80):
            # Fallback: clicca valore Unassigned solo dopo aver gia' verificato che l'owner e' Unassigned.
            try:
                self.page.keyboard.press('Escape')
            except Exception:
                pass
            self.wait(400)
            self.click_text_in_right_pane(['Unassigned', 'Non assegnato'], exact_first=True, timeout=1200, max_y_ratio=0.55)
            self.wait(500)

            if not self.click_text_in_right_pane(['Assign to me', 'Assign to myself', 'Assegna a me'], exact_first=False, timeout=1800, max_y_ratio=0.80):
                return False, 'Assign to me not found'

        self.wait(500)

        # Punto chiave: nel popup owner serve Apply.
        if not self.apply_open_panel_if_present(timeout=3500):
            return False, 'Apply button not found after Assign to me'

        ok, details_after = self.wait_until_owner_assigned(incident_key)
        if not ok:
            owner_after = details_after.get('owner') if isinstance(details_after, dict) else 'Unknown'
            return False, f'Owner still not assigned after Apply. owner_after={owner_after}'

        return True, details_after

    def set_active_current_open_id(self, incident_key):
        """
        Porta in Active solo l'incident attualmente aperto e poi verifica davvero dalla UI.
        """
        before_panel, before_details = self.read_open_incident_details(incident_key)
        if before_panel is None or before_details is None:
            return False, 'ID mismatch before status change'

        if self.status_is_active(before_details.get('status')):
            return True, before_details

        if not self.status_is_new(before_details.get('status')):
            return True, before_details

        # Apri menu status.
        self.click_status_fallback()
        self.wait(500)

        if not self.click_text_in_right_pane(['Active', 'Attivo'], exact_first=True, timeout=1400, max_y_ratio=0.80):
            # Fallback: clicca valore New solo dopo aver gia' verificato che lo status e' New.
            try:
                self.page.keyboard.press('Escape')
            except Exception:
                pass
            self.wait(400)
            self.click_text_in_right_pane(['New'], exact_first=True, timeout=1200, max_y_ratio=0.55)
            self.wait(500)

            if not self.click_text_in_right_pane(['Active', 'Attivo'], exact_first=True, timeout=1800, max_y_ratio=0.80):
                return False, 'Active option not found'

        self.wait(500)

        # Alcune build salvano subito, altre mostrano Apply.
        self.apply_open_panel_if_present(timeout=1500)

        ok, details_after = self.wait_until_status_active(incident_key)
        if not ok:
            # One quick refresh/re-read: Sentinel sometimes applies the status but the pane stays stale.
            self.click_toolbar_refresh()
            panel, refreshed = self.open_incident_by_id(incident_key)
            if refreshed and self.status_is_active(refreshed.get('status')):
                return True, refreshed

            status_after = details_after.get('status') if isinstance(details_after, dict) else 'Unknown'
            return False, f'Status still not Active after selection. status_after={status_after}'

        return True, details_after

    def save_if_needed(self):
        # No-op by design. Sentinel owner/status dropdowns save the change themselves.
        # Generic Apply/Save in the whole page is risky because it can belong to filters or other panels.
        self.wait(500)
        return

    def process_incident_by_id(self, target, dry_run, fetch_only):
        expected_key = target['incident_key']
        fallback_title = target.get('title') or expected_key
        fallback_severity = target.get('severity') or ''

        log_file("PROCESS_INCIDENT_START", f"key={expected_key};dry_run={dry_run};fetch_only={fetch_only};title={fallback_title}")

        panel, d = self.open_incident_by_id(expected_key)
        if panel is None or d is None:
            self.store.log_action(expected_key, fallback_title, 'OPEN_BY_ID', 'SKIP', 'row not found or opened ID mismatch')
            log_file("PROCESS_INCIDENT_SKIP", f"key={expected_key};reason=no_panel")
            return False, False

        key = expected_key
        title = fallback_title
        severity = d.get('severity') or fallback_severity
        status = d['status']
        owner = d['owner']
        workspace = self.workspace_hint()
        source = self.page.url

        self.store.upsert_seen(
            key, title, severity, status, owner,
            d['created_time'], d['last_update_time'], workspace, source
        )

        if fetch_only:
            self.store.log_action(key, title, 'FETCH', 'SEEN', f'status={status}, owner={owner}, severity={severity}')
            log_file("PROCESS_INCIDENT_FETCH", f"key={key};status={status};owner={owner};severity={severity}")
            return True, False

        # Dry-run: ragiona come il real monitor, ma non clicca.
        if dry_run:
            planned = []
            if self.owner_is_unassigned(owner):
                planned.append('WorkflowStep' if ENABLE_ASSIGNMENT_WORKFLOW else 'AssignmentDisabled')
            if self.status_is_new(status):
                planned.append('SetActive')
            if planned:
                self.store.log_action(key, title, 'DRY_RUN', 'WOULD_DO', ','.join(planned))
                log_file("PROCESS_INCIDENT_DRYRUN", f"key={key};planned={','.join(planned)};status={status};owner={owner}")
                return True, True
            self.store.log_action(key, title, 'DRY_RUN', 'NO_ACTION', f'status={status}, owner={owner}')
            log_file("PROCESS_INCIDENT_DRYRUN", f"key={key};status={status};owner={owner};action=no_action")
            return True, False

        processed = False

        # 1. Owner check: se e' davvero Unassigned, assegna a me.
        # Se non e' Unassigned, non tocca l'owner.
        if self.owner_is_unassigned(owner):
            if not ENABLE_ASSIGNMENT_WORKFLOW:
                self.store.log_action(key, title, 'WORKFLOW_STEP', 'SKIP_DISABLED', f'owner={owner}')
                log_file("PROCESS_INCIDENT_ASSIGN", f"key={key};skip_assignment_disabled=true;owner={owner}")
                return True, False

            owner_before = owner
            ok, result = self.WORKFLOW_STEP_current_open_id(key)
            if not ok:
                self.store.log_action(key, title, 'WORKFLOW_STEP', 'FAILED', str(result))
                return True, False

            processed = True
            # Aggiorna il DB solo con quanto verificato realmente dalla UI.
            if isinstance(result, dict):
                d = result
                status = d.get('status', status)
                owner = d.get('owner', owner)
                severity = d.get('severity') or severity
                self.store.upsert_seen(
                    key, title, severity, status, owner,
                    d.get('created_time', ''), d.get('last_update_time', ''), workspace, source
                )
            # Learn current user's owner display name after a verified Assign to me.
            if owner and not self.owner_is_unassigned(owner):
                self.settings.my_owner_identity = owner
                try:
                    self.store.save_settings({'my_owner_identity': owner})
                except Exception:
                    pass
            self.store.log_action(key, title, 'WORKFLOW_STEP', 'SUCCESS_VERIFIED', f'owner_before={owner_before}, owner_after={owner}')
            log_file("PROCESS_INCIDENT_ASSIGN", f"key={key};owner_before={owner_before};owner_after={owner}")

        else:
            self.store.log_action(key, title, 'WORKFLOW_STEP', 'SKIP', f'owner={owner}')
            log_file("PROCESS_INCIDENT_ASSIGN", f"key={key};skip_owner={owner}")

        # 2. Status check: change Status only if the incident is now assigned to me.
        # If it is assigned to another user, do not assign and do not change status.
        if (not self.owner_is_unassigned(owner)) and (not self.owner_is_me(owner)):
            self.store.log_action(key, title, 'SET_ACTIVE', 'SKIP_OTHER_OWNER', f'owner={owner}')
            return True, processed

        # Prima di cliccare ricontrolla il detail pane dello stesso ID, perche' la UI puo' aggiornarsi.
        panel2, d2 = self.read_open_incident_details(key)
        if panel2 is None or d2 is None:
            self.store.log_action(key, title, 'SET_ACTIVE', 'SKIP', 'ID mismatch before final status check')
            return True, processed

        status = d2.get('status', status)
        owner = d2.get('owner', owner)
        severity = d2.get('severity') or severity

        if (not self.owner_is_unassigned(owner)) and (not self.owner_is_me(owner)):
            self.store.log_action(key, title, 'SET_ACTIVE', 'SKIP_OTHER_OWNER_AFTER_REREAD', f'owner={owner}')
            log_file("PROCESS_INCIDENT_ACTIVE", f"key={key};skip_other_owner_after_reread={owner}")
            return True, processed

        if self.status_is_new(status):
            status_before = status
            ok, result = self.set_active_current_open_id(key)
            if not ok:
                self.store.log_action(key, title, 'SET_ACTIVE', 'FAILED', str(result))
                return True, processed

            processed = True
            verified_active = False
            if isinstance(result, dict):
                d = result
                status = d.get('status', status)
                owner = d.get('owner', owner)
                severity = d.get('severity') or severity
                verified_active = self.status_is_active(status)

            # Marca Active solo se la UI ha confermato veramente Active.
            if verified_active:
                self.store.mark_activated(
                    key, title, severity,
                    d2.get('created_time', ''), d2.get('last_update_time', ''),
                    workspace, source
                )
                self.store.log_action(key, title, 'SET_ACTIVE', 'SUCCESS_VERIFIED', f'status_before={status_before}, status_after={status}')
                log_file("PROCESS_INCIDENT_ACTIVE", f"key={key};status_before={status_before};status_after={status};verified=true")
                self.click_toolbar_refresh()
            else:
                self.store.upsert_seen(
                    key, title, severity, status, owner,
                    d2.get('created_time', ''), d2.get('last_update_time', ''),
                    workspace, source
                )
                self.store.log_action(key, title, 'SET_ACTIVE', 'FAILED_VERIFY', f'status_before={status_before}, status_after={status}')
                log_file("PROCESS_INCIDENT_ACTIVE", f"key={key};status_before={status_before};status_after={status};verified=false")

        else:
            if self.status_is_active(status):
                # Traccia comunque gli Active per SLA.
                self.store.mark_activated(
                    key, title, severity,
                    d2.get('created_time', ''), d2.get('last_update_time', ''),
                    workspace, source
                )
                log_file("PROCESS_INCIDENT_ACTIVE", f"key={key};status={status};already_active=true")
            self.store.log_action(key, title, 'SET_ACTIVE', 'SKIP', f'status={status}')
            log_file("PROCESS_INCIDENT_ACTIVE", f"key={key};status={status};already_active_or_skip")

        return True, processed

    def process_incident_snapshot(self, target, fetch_only=True):
        """
        Fast path used by fetch-only runs.
        Snapshot rows are already filtered and deduplicated, so we keep details
        minimal and avoid opening every incident panel for speed.
        """
        if not fetch_only:
            raise RuntimeError('process_incident_snapshot is fetch-only')

        expected_key = target.get('incident_key')
        if not expected_key:
            return False, False

        key = str(expected_key).strip()
        title = target.get('title') or key
        severity = target.get('severity') or ''

        status = ''
        owner = ''
        workspace = self.workspace_hint()
        source = self.page.url

        log_file("SNAPSHOT_INCIDENT", f"key={key};title={title};severity={severity};status={status or 'unknown'}")
        self.store.upsert_seen(
            key, title, severity, status, owner,
            '', '', workspace, source
        )
        self.store.log_action(key, title, 'FETCH', 'SEEN', f'status={status or "unknown"}, owner={owner or "unknown"}, severity={severity}, fast=1')
        return True, False

    def scan(self, dry_run, fetch_only):
        if not self.is_incidents_page():
            raise RuntimeError('La tab selezionata non sembra essere Microsoft Sentinel > Incidents.')

        # Non ricaricare la pagina: usa la vista corrente, senza cambiare filtri o refreshare la blade.
        self.wait(120)

        start_scan = time.perf_counter()
        snapshot = self.visible_incident_snapshot(
            max_rows=120 if not fetch_only else 15,
            row_text_timeout_ms=80 if fetch_only else 800
        )
        snapshot_ms = int((time.perf_counter() - start_scan) * 1000)
        try:
            log_file('SCAN_SNAPSHOT', f'fetch_only={fetch_only}; rows={len(snapshot)}; snapshot_ms={snapshot_ms}')
        except Exception:
            pass

        scanned = 0
        processed = 0

        for target in snapshot:
            if not self.can_continue():
                log_file("SCAN_BREAK", f"fetch_only={fetch_only};can_continue=false")
                break
            if fetch_only:
                s, p = self.process_incident_snapshot(target, fetch_only=True)
            else:
                s, p = self.process_incident_by_id(target, dry_run, fetch_only)
            scanned += 1 if s else 0
            processed += 1 if p else 0
            if s:
                log_file("SCAN_ITEM", f"fetch_only={fetch_only};seen={target.get('incident_key')};processed={p}")

        # Remove stale incidents from dashboard that are no longer present in the current Sentinel view.
        keys = [x.get('incident_key') for x in snapshot]
        clear_empty_view = bool(keys) or self.current_view_reports_no_incidents()
        self.store.sync_visible_incidents(keys, clear_when_empty=clear_empty_view)

        total_ms = int((time.perf_counter() - start_scan) * 1000)
        try:
            log_file('SCAN_DONE', f'fetch_only={fetch_only}; scanned={scanned}; processed={processed}; total_ms={total_ms}')
        except Exception:
            pass

        return scanned, processed


class NotifierWorker(threading.Thread):
    def __init__(self, in_q, out_q, store):
        super().__init__(daemon=True); self.in_q=in_q; self.out_q=out_q; self.store=store; self.settings=runtime_settings_from_storage(store); self.state_lock=threading.RLock(); self.operation_lock=threading.RLock(); self.running_monitor=False; self.paused=False; self.dry_run=True; self.auto_fetch_enabled=False; self.starting=False; self.shutdown_requested=False; self.stop_requested=False; self.target_page_id=None; self.pages={}; self.browsers=[]; self.playwright=None; self.last_scan_ts=0; self.last_fetch_ts=0; self.operation_in_progress=False; self.operation_kind=''; self.session_first_notified_keys=set()
    def emit(self,kind,payload): self.out_q.put({'kind':kind, **payload})
    def set_runtime_state(self, **changes):
        with self.state_lock:
            prev = {k: getattr(self, k, None) for k in changes.keys()}
            for key, value in changes.items():
                setattr(self, key, value)
            log_file("STATE_CHANGE", f"prev={prev};next={changes}")

    def get_runtime_state(self):
        with self.state_lock:
            return {
                'running_monitor': self.running_monitor,
                'paused': self.paused,
                'dry_run': self.dry_run,
                'last_scan_ts': self.last_scan_ts,
                'auto_fetch_enabled': self.auto_fetch_enabled,
                'starting': self.starting,
                'operation_in_progress': self.operation_in_progress,
                'operation_kind': self.operation_kind,
                'shutdown_requested': self.shutdown_requested,
                'stop_requested': self.stop_requested,
            }

    def can_continue_flag(self):
        with self.state_lock:
            return self.running_monitor and not self.paused and not self.shutdown_requested and not self.stop_requested

    def connect_browsers(self):
        log_file("BROWSER_CONNECT_START", '')
        started = time.perf_counter()
        if self.playwright is None:
            self.playwright = sync_playwright().start()
            log_file("BROWSER_CONNECT_PLAYWRIGHT", "started")

        # Close previous browser connections before opening new ones to avoid handle leaks.
        self.cleanup_browsers_connections()
        self.pages = {}
        connected = []

        for name,port in [('Chrome',CHROME_DEBUG_PORT),('Edge',EDGE_DEBUG_PORT)]:
            try:
                log_file("BROWSER_CONNECT_TRY", f"name={name};port={port}")
                br=self.playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                self.browsers.append((name,br))
                connected.append(name)
                log_file("BROWSER_CONNECT_OK", f"{name}:port={port}")
            except Exception:
                log_file("BROWSER_CONNECT_FAIL", f"{name}:port={port}")
                continue
        elapsed = int((time.perf_counter() - started) * 1000)
        log_file("BROWSER_CONNECT_DONE", f"connected={connected};elapsed_ms={elapsed}")
        return connected

    def restore_browser_window(self, page):
        """
        Kept as a best-effort background check.
        We intentionally avoid forcing window focus now, so the monitor can keep running
        while Chrome/Edge stay on another desktop or minimized.
        """
        for attempt in range(1, 4):
            try:
                if page.is_closed():
                    raise RuntimeError("target page closed")
                # Background-safe: only verify the page is reachable, no focus forcing.
                try:
                    page.wait_for_load_state('domcontentloaded', timeout=1000)
                except Exception:
                    page.wait_for_load_state('load', timeout=1000)
                log_file("PAGE_RESTORE", f"target={self.target_page_id};attempt={attempt}")
                return True
            except Exception as exc:
                log_file("PAGE_RESTORE_FAIL", f"target={self.target_page_id};attempt={attempt}", exc)
                time.sleep(0.2)
        return False

    def refresh_pages(self):
        connected=self.connect_browsers(); rows=[]; self.pages={}
        log_file("REFRESH_PAGES_START", f"connected_candidates={connected}")
        for bname,br in self.browsers:
            for cidx,ctx in enumerate(br.contexts):
                for pidx,page in enumerate(ctx.pages):
                    url=page.url or ''
                    try: title=page.title()
                    except Exception: title=''
                    pid=f'{bname}:{cidx}:{pidx}:{abs(hash(url+title))}'; self.pages[pid]=page
                    is_sentinel=('portal.azure.com' in url or 'security.microsoft.com' in url or 'sentinel' in title.lower())
                    rows.append({'page_id':pid,'browser':bname,'title':title[:160],'url':url,'is_sentinel':is_sentinel})
        sentinel_rows = sum(1 for r in rows if r.get('is_sentinel'))
        log_file("REFRESH_PAGES_DONE", f"rows={len(rows)};sentinel_rows={sentinel_rows};connected={connected}")
        self.emit('pages', {'pages':rows,'connected':connected})
    def selected_page(self):
        if not self.target_page_id:
            log_file("SELECTED_PAGE_FAIL", "no_target")
            raise RuntimeError('Nessuna tab Sentinel selezionata.')
        page=self.pages.get(self.target_page_id)
        if page is None:
            log_file("SELECTED_PAGE_FAIL", f"target={self.target_page_id};missing")
            raise RuntimeError('Tab selezionata non piu disponibile. Premi Refresh browser tabs.')
        try:
            if page.is_closed():
                log_file("SELECTED_PAGE_FAIL", f"target={self.target_page_id};closed")
                raise RuntimeError('Tab selezionata chiusa. Premi Refresh browser tabs e seleziona di nuovo Sentinel.')
        except AttributeError:
            pass
        log_file("SELECTED_PAGE_OK", f"target={self.target_page_id}")
        return page
    def settings_dict(self): return self.settings.__dict__.copy()
    def update_settings(self, vals):
        int_fields = [
            'scan_interval_seconds',
            'sla_critical_minutes','sla_high_minutes','sla_medium_minutes','sla_low_minutes','sla_informational_minutes',
            'resolution_critical_minutes','resolution_high_minutes','resolution_medium_minutes','resolution_low_minutes','resolution_informational_minutes',
            'misclassification_percent',
            'notification_critical_minutes','notification_high_minutes','notification_medium_minutes','notification_low_minutes','notification_informational_minutes',
            'notification_warning_percent','notification_repeat_minutes','auto_fetch_interval_seconds'
        ]
        for key in int_fields:
            default = getattr(self.settings, key)
            if key == 'auto_fetch_interval_seconds':
                lo, hi = 30, 3600
            elif key == 'scan_interval_seconds':
                lo, hi = 30, 3600
            elif key == 'notification_warning_percent':
                lo, hi = 1, 100
            elif key == 'notification_repeat_minutes':
                lo, hi = 1, 10080
            else:
                lo, hi = 1, 10080
            setattr(self.settings, key, clamp_int(vals.get(key), default, lo, hi))
            log_file("WORKER_SETTINGS_APPLY", f"{key}={getattr(self.settings, key)}")

        self.store.save_settings(self.settings_dict()); self.emit('status', {'message':'Taking Charge / Notification SLA settings saved','settings':self.settings_dict()})
        log_file("WORKER_SETTINGS_UPDATE", f"updated={self.settings_dict()}")
    def check_sla(self, force_first_alert_for_existing=False):
        warnings = 0
        check_started = time.perf_counter()
        ignored = self.store.ignored_keys()
        candidates = self.store.incidents()
        total = len(candidates)
        log_file("SLA_CHECK_START", f"force_first={force_first_alert_for_existing};candidates={total};ignored_cached={len(ignored)}")
        if not total:
            log_file("SLA_CHECK_DONE", f"warnings=0;elapsed_ms=0;total=0")
            return 0
        priority = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'informational': 4}
        for inc in sorted(
            candidates,
            key=lambda i: (
                priority.get((i.get('severity') or '').strip().lower(), 99),
                -(created_age_minutes_with_fallback(
                    i.get('created_time') or '',
                    i.get('last_seen') or i.get('first_seen_active') or i.get('activated_at') or ''
                ) or 0)
            )
        ):
            if str(inc.get('incident_key')) in ignored:
                log_file("SLA_SKIP", f"key={inc.get('incident_key')};reason=ignored")
                continue
            status = (inc.get('status') or '').lower()
            if status == 'closed':
                log_file("SLA_SKIP", f"key={inc.get('incident_key')};reason=closed")
                continue
            created = inc.get('created_time') or ''
            age = created_age_minutes_with_fallback(created, inc.get('last_seen') or inc.get('first_seen_active') or inc.get('activated_at') or '')
            sev = inc.get('severity') or 'Medium'
            notify_due = self.settings.notification_for(sev)
            warn_threshold = self.settings.warning_at(sev)
            key = inc.get('incident_key') or '-'
            title = inc.get('title') or '-'
            first_alert_notified = int(inc.get('first_alert_notified') or 0)
            should_notify_first = (not first_alert_notified) or force_first_alert_for_existing
            if should_notify_first and key not in self.session_first_notified_keys:
                nt = 'Nuovo alert rilevato'
                message = f'Nuovo alert rilevato: {key} ({sev}). {title}'
                sev_norm = (sev or '').strip().lower()
                notification_ok, actionable = notify_windows(nt, message, severity=sev_norm, incident_key=key, incident_title=title)
                age_label = str(age) if age is not None else 'N/D'
                if sev_norm in ('critical', 'high') and not actionable:
                    self.emit('sla_confirm', {
                        'incident_key': key,
                        'incident_title': title,
                        'severity': sev_norm,
                        'age': age_label,
                        'threshold': warn_threshold,
                        'message': message,
                        'notification_ok': notification_ok,
                    })
                if notification_ok:
                    if not first_alert_notified:
                        self.store.mark_first_alert_notified(key)
                    self.store.mark_last_seen(key)
                    self.session_first_notified_keys.add(key)
                    self.store.log_action(key, title, 'NEW_ALERT_NOTIFICATION', 'SENT', f'age={age_label}, created={created}, severity={sev}')
                    log_file("SLA_FIRST_NOTIFY", f"key={key};severity={sev};age={age_label};first={first_alert_notified}")
                    log_file("SLA_NOTIFY_FLOW", f"key={key};type=first;severity={sev};ok=1")
                    warnings += 1
                    continue
                self.store.log_action(key, title, 'NEW_ALERT_NOTIFICATION', 'FAILED', f'age={age_label}, created={created}, severity={sev}')
                log_file("SLA_NOTIFY_FLOW", f"key={key};type=first;severity={sev};ok=0")
                continue
            if age is None:
                log_file("SLA_SKIP", f"key={key};reason=age_unknown")
                continue
            if age < warn_threshold:
                log_file("SLA_SKIP", f"key={key};reason=under_threshold;age={age};threshold={warn_threshold}")
                continue
            if int(inc.get('sla_warning_sent') or 0):
                last_warning = inc.get('last_sla_warning_at')
                repeat_every = self.settings.notification_repeat_minutes
                minutes_since_last = minutes_since(last_warning)
                if minutes_since_last is not None and minutes_since_last < repeat_every:
                    log_file("SLA_REPEAT_SKIP", f"key={key};since_last={minutes_since_last};repeat_every={repeat_every}")
                    continue
            nt = 'Sentinel Notification Time reached'
            warn_pct = self.settings.notification_warning_percent
            message = f'Incident {key} reached {warn_pct}% of Notification Time: {age}/{warn_threshold}/{notify_due} min ({sev}). {title}'
            sev_norm = (sev or '').strip().lower()
            notification_ok, actionable = notify_windows(nt, message, severity=sev_norm, incident_key=key, incident_title=title)
            if sev_norm in ('critical', 'high') and not actionable:
                self.emit('sla_confirm', {
                    'incident_key': key,
                    'incident_title': title,
                'severity': sev_norm,
                'age': age,
                'threshold': warn_threshold,
                'message': message,
                'notification_ok': notification_ok,
                })
                if notification_ok:
                    self.store.mark_last_seen(key)
                    self.store.mark_sla_warning(key)
                    self.store.log_action(key, title, 'SLA_NOTIFICATION', 'SENT', f'age={age}, notification_due={notify_due}, warning_percent={warn_pct}, warning_threshold={warn_threshold}, repeat_minutes={self.settings.notification_repeat_minutes}, severity={sev}, created={created}')
                    log_file("SLA_NOTIFY", f"key={key};severity={sev};age={age};result=SENT")
                    log_file("SLA_NOTIFY_FLOW", f"key={key};type=notify;severity={sev};ok=1")
                    warnings += 1
                else:
                    self.store.log_action(key, title, 'SLA_NOTIFICATION', 'FAILED', f'age={age}, notification_due={notify_due}, warning_percent={warn_pct}, warning_threshold={warn_threshold}, repeat_minutes={self.settings.notification_repeat_minutes}, severity={sev}, created={created}')
                    log_file("SLA_NOTIFY", f"key={key};severity={sev};age={age};result=FAILED")
                    log_file("SLA_NOTIFY_FLOW", f"key={key};type=notify;severity={sev};ok=0")
        elapsed = int((time.perf_counter() - check_started) * 1000)
        log_file("SLA_CHECK_DONE", f"warnings={warnings};elapsed_ms={elapsed};total={total}")
        return warnings
    def run_scan(self, fetch_only=False, force_first_alert_for_existing=False):
        """
        Runs exactly one browser operation at a time.
        This prevents auto-fetch and monitor actions from touching the same Sentinel tab together.
        """
        run_id = int(time.time() * 1000)
        log_file("RUN_SCAN_CALL", f"run_id={run_id};fetch_only={fetch_only};force_first={force_first_alert_for_existing}")
        with self.operation_lock:
            if self.operation_in_progress:
                self.store.log_system('SCAN', 'SKIP_BUSY', f'fetch_only={fetch_only}')
                log_file("RUN_SCAN_SKIP", f"run_id={run_id};reason=busy;fetch_only={fetch_only}")
                return 0, 0

            self.set_runtime_state(operation_in_progress=True, operation_kind='fetch' if fetch_only else 'scan')
            state = self.get_runtime_state()
            if state.get('stop_requested'):
                self.store.log_system('SCAN', 'SKIP_STOPPED', 'Stop requested')
                log_file("RUN_SCAN_SKIP", f"run_id={run_id};reason=stop_requested;fetch_only={fetch_only}")
                self.set_runtime_state(operation_in_progress=False, operation_kind='')
                return 0, 0
            if state.get('shutdown_requested'):
                self.store.log_system('SCAN', 'SKIP_SHUTDOWN', f'fetch_only={fetch_only}')
                log_file("RUN_SCAN_SKIP", f"run_id={run_id};reason=shutdown_requested;fetch_only={fetch_only}")
                self.set_runtime_state(operation_in_progress=False, operation_kind='')
                return 0, 0

            if (not fetch_only) and (not self.can_continue_flag()):
                self.store.log_system('SCAN', 'SKIP_STOPPED', 'Monitor stopped or paused before scan start')
                log_file("RUN_SCAN_SKIP", f"run_id={run_id};reason=can_continue_false;fetch_only={fetch_only}")
                self.set_runtime_state(operation_in_progress=False, operation_kind='')
                return 0, 0

            page = self.selected_page()
            if not self.restore_browser_window(page):
                self.store.log_system('SCAN', 'WINDOW_RESTORE_FAIL', 'Continuing without explicit restore')
                log_file("RUN_SCAN_CONTINUE", f"run_id={run_id};reason=restore_browser_window_failed;fetch_only={fetch_only}")
            self.store.log_system('FETCH' if fetch_only else 'SCAN', 'START', f'url={getattr(page, "url", "")}')
            log_file("RUN_SCAN_START", f"run_id={run_id};fetch_only={fetch_only};url={getattr(page,'url','')}")

            try:
                run_started = time.perf_counter()
                monitor = SentinelPageMonitor(page, self.store, self.settings)
                monitor.can_continue = (
                    lambda: not self.get_runtime_state().get('shutdown_requested')
                    and not self.get_runtime_state().get('stop_requested')
                ) if fetch_only else self.can_continue_flag

                scan_start = time.perf_counter()
                scanned, processed = monitor.scan(state['dry_run'], fetch_only)
                scan_ms = int((time.perf_counter() - scan_start) * 1000)
                log_file(
                    'SCAN_TIMING',
                    f"kind={'fetch' if fetch_only else 'scan'}; scanned={scanned}; processed={processed}; scan_ms={scan_ms}"
                )

                sla_start = time.perf_counter()
                warnings = self.check_sla(force_first_alert_for_existing=force_first_alert_for_existing)
                sla_ms = int((time.perf_counter() - sla_start) * 1000)
                total_ms = int((time.perf_counter() - run_started) * 1000)
                log_file(
                    'SCAN_TIMING',
                    f"kind={'fetch' if fetch_only else 'scan'}; warnings={warnings}; sla_ms={sla_ms}; total_ms={total_ms}"
                )

                self.emit('scan_result', {
                    'scanned': scanned,
                    'processed': processed,
                    'warnings': warnings,
                    'fetch_only': fetch_only,
                    'incidents': self.store.incidents(),
                    'actions': self.store.actions(),
                    'settings': self.settings_dict(),
                    'target_url': page.url
                })
                self.store.log_system('FETCH' if fetch_only else 'SCAN', 'SUCCESS', f'scanned={scanned}, processed={processed}, warnings={warnings}')
                self.emit('status', {
                    'message': f"{'Fetch' if fetch_only else 'Scan'} completato: {scanned} eventi, {processed} processati, {warnings} avvisi",
                    'settings': self.settings_dict()
                })
                log_file("RUN_SCAN_SUCCESS", f"run_id={run_id};fetch_only={fetch_only};scanned={scanned};processed={processed};warnings={warnings};kind={state.get('operation_kind')}")
                log_file("RUN_SCAN_STATE", f"run_id={run_id};state={self.get_runtime_state()}")
                return scanned, processed

            except Exception as e:
                details = f'fetch_only={fetch_only}; error={type(e).__name__}: {e}'
                log_file('RUN_SCAN_ERROR', details, e)
                self.store.log_system('FETCH' if fetch_only else 'SCAN', 'ERROR', details)
                self.emit('error', {'message': details, 'actions': self.store.actions()})
                self.emit('status', {'message': f"{'Fetch' if fetch_only else 'Scan'} fallito: {type(e).__name__}", 'settings': self.settings_dict()})
                log_file("RUN_SCAN_ERROR", f"{type(e).__name__}")
                return 0, 0
            finally:
                log_file("RUN_SCAN_END", f"run_id={run_id};fetch_only={fetch_only}")
                self.set_runtime_state(operation_in_progress=False, operation_kind='')

    def cleanup_browsers_connections(self):
        if not self.browsers:
            return

        for _, br in list(self.browsers):
            try:
                br.close()
            except Exception as e:
                log_file('BROWSER_CONNECTION_CLOSE_ERROR', '', e)
        self.browsers = []

    def cleanup_playwright(self):
        try:
            self.cleanup_browsers_connections()
            self.pages = {}
        except Exception as e:
            log_file('CLEANUP_BROWSERS_ERROR', '', e)

        try:
            if self.playwright is not None:
                self.playwright.stop()
                self.playwright = None
        except Exception as e:
            log_file('PLAYWRIGHT_STOP_ERROR', '', e)

    def handle(self,cmd):
        a = cmd.get('action')
        log_file("HANDLE", f"action={a}")
        try:
            if a == 'refresh_pages':
                log_file("HANDLE_REFRESH_PAGES", "")
                self.refresh_pages()

            elif a == 'select_page':
                self.target_page_id = cmd.get('page_id')
                self.store.log_system('SELECT_PAGE', 'SUCCESS', str(self.target_page_id))
                self.emit('status', {'message':f'Selected page: {self.target_page_id}', 'settings':self.settings_dict()})
                log_file("HANDLE_SELECT_PAGE", f"target={self.target_page_id}")

            elif a == 'fetch':
                # Manual fetch is allowed, but still serialized with every other browser operation.
                state = self.get_runtime_state()
                log_file("HANDLE_FETCH_STATE", f"running={state.get('running_monitor')};paused={state.get('paused')};operation_in_progress={state.get('operation_in_progress')}")
                if state.get('operation_in_progress'):
                    log_file("HANDLE_FETCH_SKIP", "operation_in_progress")
                    self.emit('status', {'message':'Operazione già in corso, attendi il completamento prima di un nuovo fetch.', 'settings':self.settings_dict()})
                    return
                if state.get('running_monitor') and not state.get('paused'):
                    log_file("HANDLE_FETCH_SKIP", "monitor_running")
                    self.emit('status', {'message':'Fetch non disponibile mentre il monitor è in esecuzione.', 'settings':self.settings_dict()})
                    return
                self.set_runtime_state(stop_requested=False, starting=False)
                log_file("HANDLE_FETCH", f"target={self.target_page_id}")
                self.emit('status', {'message':'Fetching selected Sentinel tab without refreshing page...', 'settings':self.settings_dict()})
                self.run_scan(fetch_only=True, force_first_alert_for_existing=True)
                self.last_fetch_ts = time.time()
                log_file("HANDLE_FETCH_DONE", f"target={self.target_page_id};last_fetch_ts={self.last_fetch_ts}")

            elif a == 'start':
                state = self.get_runtime_state()
                if state.get('operation_in_progress'):
                    log_file("HANDLE_START_SKIP", "operation_in_progress")
                    self.emit('status', {'message':'Operazione già in corso, attendi il completamento.', 'settings':self.settings_dict()})
                    return
                self.set_runtime_state(stop_requested=False)
                dry = bool(cmd.get('dry_run', True))
                self.set_runtime_state(dry_run=dry, running_monitor=False, paused=False, starting=True, auto_fetch_enabled=False, last_scan_ts=0)
                self.store.log_system('monitor_START_REQUEST', 'RECEIVED', 'mode=' + ('dry-run' if dry else 'real'))
                self.emit('status', {'message':'Initial fetch before monitor start...', 'settings':self.settings_dict()})

                # Initial fetch first, then enable the real/dry-run monitor.
                self.run_scan(fetch_only=True, force_first_alert_for_existing=True)
                if not self.get_runtime_state().get('shutdown_requested') and not self.get_runtime_state().get('stop_requested'):
                    self.set_runtime_state(dry_run=dry, running_monitor=True, paused=False, starting=False, auto_fetch_enabled=False, last_scan_ts=0)
                    self.emit('status', {'message':'monitor started in '+('dry-run' if dry else 'real')+' mode after initial fetch', 'settings':self.settings_dict()})
                    self.store.log_system('monitor_START', 'SUCCESS', 'mode=' + ('dry-run' if dry else 'real'))
                    log_file("HANDLE_START_OK", f"dry={dry}")
                log_file("HANDLE_START_DONE", f"state={self.get_runtime_state()}")

            elif a == 'pause':
                self.set_runtime_state(paused=True, auto_fetch_enabled=False)
                self.store.log_system('monitor_PAUSE', 'SUCCESS', '')
                self.emit('status', {'message':'Monitor paused. Auto-fetch disabled.', 'settings':self.settings_dict()})
                log_file("HANDLE_PAUSE", "")

            elif a == 'resume':
                self.set_runtime_state(stop_requested=False)
                self.set_runtime_state(paused=False, running_monitor=True, auto_fetch_enabled=False)
                self.store.log_system('monitor_RESUME', 'SUCCESS', '')
                self.emit('status', {'message':'Monitor resumed. Auto-fetch disabled while monitor is running.', 'settings':self.settings_dict()})
                log_file("HANDLE_RESUME", "")
                log_file("HANDLE_RESUME_DONE", f"state={self.get_runtime_state()}")

            elif a == 'stop':
                # Stop means stop monitor and stop background auto-fetch.
                self.set_runtime_state(running_monitor=False, paused=False, starting=False, auto_fetch_enabled=False, stop_requested=True)
                self.session_first_notified_keys.clear()
                self.store.log_system('monitor_STOP', 'SUCCESS', 'Monitor stopped; auto-fetch disabled')
                self.emit('status', {'message':'Monitor stopped. Auto-fetch disabled; use FETCH CURRENT VIEW for manual refresh.', 'settings':self.settings_dict()})
                log_file("HANDLE_STOP", "stop_requested=true")
                log_file("HANDLE_STOP_DONE", f"state={self.get_runtime_state()}")

            elif a == 'settings':
                self.update_settings(cmd.get('values',{}))
                log_file("HANDLE_SETTINGS", f"keys={list((cmd.get('values') or {}).keys())}")
                self.emit('status', {'message':'Impostazioni aggiornate', 'settings':self.settings_dict()})

            elif a == 'ignore_incident':
                key = str(cmd.get('incident_key') or '').strip()
                self.store.ignore_incident(key, 'manual')
                self.emit('scan_result', {'scanned':0,'processed':0,'warnings':0,'fetch_only':True,'incidents':self.store.incidents(),'actions':self.store.actions(),'settings':self.settings_dict(),'target_url':''})
                log_file("HANDLE_IGNORE", f"key={key}")

            elif a == 'dismiss_incident':
                key = str(cmd.get('incident_key') or '').strip()
                self.store.delete_incident(key, reason='manual_dismiss')
                self.emit('scan_result', {'scanned':0,'processed':0,'warnings':0,'fetch_only':True,'incidents':self.store.incidents(),'actions':self.store.actions(),'settings':self.settings_dict(),'target_url':''})
                self.emit('status', {'message': f"Incidento {key or '-'} rimosso dal database.", 'settings':self.settings_dict()})
                log_file("HANDLE_DISMISS", f"key={key}")

            elif a == 'unignore_all':
                self.store.unignore_all()
                self.emit('scan_result', {'scanned':0,'processed':0,'warnings':0,'fetch_only':True,'incidents':self.store.incidents(),'actions':self.store.actions(),'settings':self.settings_dict(),'target_url':''})
                log_file("HANDLE_UNIGNORE_ALL", "")

            elif a == 'shutdown':
                self.set_runtime_state(running_monitor=False, paused=False, starting=False, auto_fetch_enabled=False, shutdown_requested=True)
                self.session_first_notified_keys.clear()
                self.store.log_system('APP_SHUTDOWN', 'REQUESTED', '')
                self.cleanup_playwright()
                self.emit('status', {'message':'Shutdown complete', 'settings':self.settings_dict()})
                log_file("HANDLE_SHUTDOWN", "requested")

        except Exception as e:
            details = f'action={a}; error={type(e).__name__}: {e}'
            log_file('HANDLE_ERROR', details, e)
            self.store.log_system('HANDLE', 'ERROR', details)
            self.emit('error', {'message': details, 'actions': self.store.actions()})

    def run(self):
        self.emit('status', {'message':'Worker ready. Click Launch Chrome/Edge for monitor: the app will open and auto-link the new tab.','settings':self.settings_dict()})
        self.store.log_system('WORKER', 'READY', '')
        while True:
            try:
                try:
                    cmd = self.in_q.get(timeout=1)
                    self.handle(cmd)
                except queue.Empty:
                    pass

                state = self.get_runtime_state()
                if state.get('shutdown_requested'):
                    break

                # Auto-fetch runs only when explicitly enabled and when the monitor is fully stopped.
                # It never runs while starting/running/paused to avoid touching the same tab together with the monitor.
                state = self.get_runtime_state()
                if (
                    state.get('auto_fetch_enabled')
                    and not state.get('running_monitor')
                    and not state.get('paused')
                    and not state.get('starting')
                    and not state.get('operation_in_progress')
                    and self.target_page_id
                    and time.time() - self.last_fetch_ts >= self.settings.auto_fetch_interval_seconds
                ):
                    self.last_fetch_ts = time.time()
                    self.emit('status', {'message':'Auto-fetch current Sentinel view...', 'settings':self.settings_dict()})
                    log_file("RUN_LOOP_TRIGGER", f"auto_fetch_interval={self.settings.auto_fetch_interval_seconds};target={self.target_page_id}")
                    self.run_scan(fetch_only=True, force_first_alert_for_existing=False)

                state = self.get_runtime_state()
                if (
                    state.get('running_monitor')
                    and not state.get('paused')
                    and not state.get('starting')
                    and not state.get('operation_in_progress')
                    and self.target_page_id
                    and time.time() - state.get('last_scan_ts', 0) >= self.settings.scan_interval_seconds
                ):
                    self.set_runtime_state(last_scan_ts=time.time())
                    self.emit('status', {'message':'Automatic monitor scan running...', 'settings':self.settings_dict()})
                    log_file("RUN_LOOP_TRIGGER", f"auto_scan_interval={self.settings.scan_interval_seconds};target={self.target_page_id}")
                    self.run_scan(fetch_only=False)

            except Exception as e:
                details = f'worker loop error={type(e).__name__}: {e}'
                log_file('WORKER_LOOP_ERROR', details, e)
                try:
                    self.store.log_system('WORKER_LOOP', 'ERROR', details)
                except Exception:
                    pass
                if 'Tab selezionata' in str(e):
                    self.set_runtime_state(running_monitor=False, paused=False, starting=False, auto_fetch_enabled=False)
                    self.target_page_id = None
                    self.emit('status', {'message':'Browser tab disconnected: please refresh pages and re-select a Sentinel tab.', 'settings': self.settings_dict()})
                self.emit('error', {'message': details, 'actions': self.store.actions() if hasattr(self, 'store') else []})

        self.cleanup_playwright()
        self.store.log_system('WORKER', 'EXIT', '')

def find_chrome_path():
    for c in [os.path.join(os.environ.get('ProgramFiles',''),'Google','Chrome','Application','chrome.exe'), os.path.join(os.environ.get('ProgramFiles(x86)',''),'Google','Chrome','Application','chrome.exe'), shutil.which('chrome.exe')]:
        if c and Path(c).exists(): return c
    return None

def find_edge_path():
    for c in [os.path.join(os.environ.get('ProgramFiles',''),'Microsoft','Edge','Application','msedge.exe'), os.path.join(os.environ.get('ProgramFiles(x86)',''),'Microsoft','Edge','Application','msedge.exe'), shutil.which('msedge.exe')]:
        if c and Path(c).exists(): return c
    return None

def _debug_port_alive(port):
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=1) as resp:
            return 200 <= getattr(resp, "status", 0) < 400
    except Exception:
        return False

def launch_browser_debug(browser):
    """
    Avvia un'istanza Chromium debuggabile e separata dalle finestre normali.
    Questo evita il problema principale: se Chrome e' gia' aperto normalmente,
    Windows/Chrome tende a riusare il processo esistente e la porta 9222 non viene attivata.
    """
    exe=find_chrome_path() if browser=='chrome' else find_edge_path()
    port=CHROME_DEBUG_PORT if browser=='chrome' else EDGE_DEBUG_PORT
    profile_dir=browser_profile_dir(browser)

    if not exe:
        messagebox.showerror('Browser non trovato', f'{browser} non trovato.')
        return False

    if _debug_port_alive(port):
        log_file("LAUNCH_BROWSER_SKIP", f"browser={browser};port={port};reason=already_listening")
        return True

    profile_dir.mkdir(parents=True, exist_ok=True)

    args=[
        exe,
        f'--remote-debugging-port={port}',
        '--remote-debugging-address=127.0.0.1',
        '--remote-allow-origins=*',
        f'--user-data-dir={str(profile_dir)}',
        '--no-first-run',
        '--no-default-browser-check',
        '--restore-last-session',
        '--hide-crash-restore-bubble',
        '--start-minimized',
        '--new-window',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-background-timer-throttling',
        '--disable-features=CalculateNativeWinOcclusion',
        'https://portal.azure.com/'
    ]

    log_file("LAUNCH_BROWSER_START", f"browser={browser};port={port}")
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_file("LAUNCH_BROWSER_OK", f"browser={browser};profile={profile_dir};pid={proc.pid}")
        return True
    except Exception as e:
        log_file("LAUNCH_BROWSER_FAIL", f"browser={browser};err={str(e)}")
        messagebox.showerror('Errore avvio browser', str(e))
        return False

class NotifierApp(tk.Tk):
    def __init__(self):
        super().__init__()
        enable_windows_background_runtime()
        self.title('Sentinel Notifier - Desktop (UI UX Pro Max)')
        self.geometry('1280x860')
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.minsize(1020,680)
        self._setup_style()
        log_file('APP_INIT', f"startup={now_iso()}; db_path={DB_PATH}; exists={DB_PATH.exists()}")
        self.store=Storage(DB_PATH)
        log_file("APP_STORE_READY", f"tables_ready")
        try:
            self.store.clear_runtime_data()
            log_file('DB_CLEAR', 'startup clear runtime tables requested and completed')
        except Exception as e:
            log_file('DB_CLEAR_FAIL', 'startup clear runtime tables failed', e)
            pass
        self.in_q=queue.Queue()
        self.out_q=queue.Queue()
        log_file("APP_QUEUES_READY", f"in_q_size={self.in_q.qsize()};out_q_size={self.out_q.qsize()}")
        set_windows_notification_action_sink(self._enqueue_windows_action)
        self.worker=NotifierWorker(self.in_q,self.out_q,self.store)
        log_file("APP_WORKER_CREATED", "")
        self.worker.start()
        log_file("APP_WORKER_STARTED", "")
        self.page_items={}
        self.pending_auto_browser=None
        self.pending_auto_attempts=0
        self.auto_check_text = tk.StringVar(value='Auto-check: 60s')
        self.build_ui()
        self.after(500,self.poll_worker)

    def _setup_style(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use('clam')
        except Exception:
            pass

        self.palette = {
            'page': '#f2f5f9',
            'surface': '#ffffff',
            'surface_soft': '#f8fafc',
            'line': '#d7deea',
            'text': '#111827',
            'muted': '#5d6980',
            'muted_strong': '#344054',
            'primary': '#2563eb',
            'primary_hover': '#1d4ed8',
            'secondary': '#f8fafc',
            'secondary_hover': '#edf2f7',
            'danger': '#dc2626',
            'danger_hover': '#b91c1c',
            'warning': '#d97706',
            'ok': '#16a34a',
            'title': '#111827',
            'accent': '#2563eb'
        }

        self.configure(bg=self.palette['page'])
        self.style.configure('App.TFrame', background=self.palette['page'])
        self.style.configure('Card.TFrame', background=self.palette['surface'], relief='flat', borderwidth=0)
        self.style.configure('Card.TLabelframe', background=self.palette['surface'], borderwidth=1, relief='flat', padding=12, bordercolor=self.palette['line'])
        self.style.configure('Card.TLabelframe.Label', background=self.palette['surface'], foreground=self.palette['muted_strong'], font=('Inter', 10, 'bold'))
        self.style.configure('Header.TFrame', background=self.palette['surface'], relief='flat')
        self.style.configure('HeaderAccent.TFrame', background=self.palette['surface_soft'], borderwidth=1, relief='solid')
        self.style.configure('SectionHeader.TLabel', background=self.palette['page'], foreground=self.palette['muted_strong'], font=('Inter', 9, 'bold'))
        self.style.configure(
            'Primary.TButton',
            font=('Inter', 10, 'bold'),
            padding=(12, 7),
            foreground='white',
            background=self.palette['primary'],
            bordercolor=self.palette['primary'],
            borderwidth=1,
            relief='flat'
        )
        self.style.map('Primary.TButton', background=[('active', self.palette['primary_hover'])], foreground=[('disabled', '#94a3b8')])
        self.style.configure('Danger.TButton', font=('Inter', 10, 'bold'), padding=(11, 7), background=self.palette['danger'], foreground='white', bordercolor=self.palette['danger'])
        self.style.map('Danger.TButton', background=[('active', self.palette['danger_hover']), ('pressed', self.palette['danger_hover'])], foreground=[('disabled', '#fee2e2')])
        self.style.configure('Secondary.TButton', font=('Inter', 10), padding=(11, 7), background=self.palette['secondary'], foreground=self.palette['text'], bordercolor=self.palette['line'], relief='flat')
        self.style.map('Secondary.TButton', background=[('active', self.palette['secondary_hover']), ('pressed', self.palette['surface_soft'])], relief=[('pressed', 'flat')])
        self.style.configure('Section.TLabel', background=self.palette['page'], foreground=self.palette['muted'], font=('Inter', 9))
        self.style.configure('Body.TLabel', background=self.palette['surface'], foreground=self.palette['muted_strong'], font=('Inter', 9))
        self.style.configure('BodyText.TLabel', background=self.palette['page'], foreground=self.palette['text'], font=('Inter', 10))
        self.style.configure('Title.TLabel', background=self.palette['page'], foreground=self.palette['title'], font=('Inter', 22, 'bold'))
        self.style.configure('Subtitle.TLabel', background=self.palette['page'], foreground=self.palette['muted'], font=('Inter', 10))
        self.style.configure('KPIKey.TLabel', background=self.palette['surface_soft'], foreground=self.palette['muted'], font=('Inter', 8))
        self.style.configure('KPIValue.TLabel', background=self.palette['surface_soft'], foreground=self.palette['muted_strong'], font=('Inter', 9, 'bold'))
        self.style.configure('Badge.TLabel', background=self.palette['surface_soft'], foreground=self.palette['text'], font=('Inter', 8, 'bold'))
        self.style.configure('HeaderBadge.TLabel', background='#dcfce7', foreground='#166534', font=('Inter', 9, 'bold'))
        self.style.configure('App.Treeview', font=('Inter', 8), rowheight=26, background=self.palette['surface'], foreground=self.palette['text'], fieldbackground=self.palette['surface'], bordercolor=self.palette['line'])
        self.style.configure('App.Treeview.Heading', font=('Inter', 8, 'bold'), background=self.palette['surface_soft'], foreground=self.palette['muted_strong'], relief='flat', borderwidth=0)
        self.style.map('App.Treeview', background=[('selected', '#dbeafe')], foreground=[('selected', self.palette['text'])])
        self.style.configure('Card.TNotebook', background=self.palette['surface'])
        self.style.configure('Card.TNotebook.Tab', font=('Inter', 10, 'bold'), padding=(14, 7), background=self.palette['surface_soft'], foreground=self.palette['muted_strong'])
        self.style.map('Card.TNotebook.Tab', background=[('selected', self.palette['surface'])], foreground=[('selected', self.palette['text'])], relief=[('selected', 'flat')])
        self.style.configure('Info.TLabel', background=self.palette['surface_soft'], foreground=self.palette['muted_strong'], font=('Inter', 9))

    def send(self, action, **kw):
        payload = {'action': action, **kw}
        log_file("UI_QUEUE_IN", f"action={action};before={self.in_q.qsize()};after={self.in_q.qsize()+1}")
        self.in_q.put(payload)
        log_file("UI_SEND", f"action={action};keys={list(kw.keys())};after={self.in_q.qsize()}")
    def build_ui(self):
        root = ttk.Frame(self, style='App.TFrame', padding=(16, 14))
        root.pack(fill='both', expand=True)

        self.status_var = tk.StringVar(value='Ready')
        self.chrome_state_var = tk.StringVar(value='Chrome: offline')
        self.edge_state_var = tk.StringVar(value='Edge: offline')
        self.auto_fetch_text = tk.StringVar(value='Auto-fetch: 60s')
        self.advanced_sla_open = False

        hero = ttk.Frame(root, style='HeaderAccent.TFrame', padding=(14, 10))
        hero.pack(fill='x', pady=(0, 12))
        ttk.Label(hero, text='Sentinel Notifier', style='Title.TLabel').pack(anchor='w')
        ttk.Label(
            hero,
            text='Dashboard semplificata: 3 blocchi in alto, incidenti in basso',
            style='Subtitle.TLabel'
        ).pack(anchor='w', pady=(4, 0))
        badge_row = ttk.Frame(hero, style='Header.TFrame')
        badge_row.pack(fill='x', pady=(8, 0))
        self.status_badge = tk.Label(
            badge_row,
            textvariable=self.status_var,
            font=('Segoe UI', 9, 'bold'),
            bg='#dcfce7',
            fg=self.palette['ok'],
            padx=10,
            pady=4,
            relief='flat',
            borderwidth=0
        )
        self.status_badge.pack(side='left')
        ttk.Label(
            badge_row,
            text='Notifiche Windows: priorita alta per critical/high (solo click di conferma)',
            style='HeaderBadge.TLabel'
        ).pack(side='left', padx=(10, 0))
        ttk.Label(
            badge_row,
            text='Logs: data/bot_state.sqlite3 / logs/app.log',
            style='Section.TLabel'
        ).pack(side='right')

        top_grid = ttk.Frame(root, style='App.TFrame')
        top_grid.pack(fill='x', pady=(0, 12))
        for c in range(3):
            top_grid.columnconfigure(c, weight=1, uniform='top')

        workspace = ttk.LabelFrame(top_grid, text='Workspace', style='Card.TLabelframe', padding=14)
        workspace.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        monitor = ttk.LabelFrame(top_grid, text='Stato notifier', style='Card.TLabelframe', padding=14)
        monitor.grid(row=0, column=1, sticky='nsew', padx=(0, 8))
        sla = ttk.LabelFrame(top_grid, text='SLA', style='Card.TLabelframe', padding=14)
        sla.grid(row=0, column=2, sticky='nsew')

        ws_badges = ttk.Frame(workspace, style='App.TFrame')
        ws_badges.pack(fill='x')
        ttk.Label(ws_badges, text='Stato browser', style='Section.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(ws_badges, textvariable=self.chrome_state_var, style='Badge.TLabel').grid(row=0, column=1, padx=(6, 10), sticky='w')
        ttk.Label(ws_badges, textvariable=self.edge_state_var, style='Badge.TLabel').grid(row=0, column=2, padx=(0, 6), sticky='w')

        ttk.Label(
            workspace,
            text='Seleziona la tab Sentinel aperta per agganciare il monitor.',
            style='Section.TLabel'
        ).pack(anchor='w', pady=(8, 8))
        ws_btns = ttk.Frame(workspace, style='App.TFrame')
        ws_btns.pack(fill='x')
        ttk.Button(ws_btns, text='Lancia Chrome Debug', style='Primary.TButton', command=lambda: self.launch_and_link('chrome')).pack(side='left', padx=(0, 8), pady=(0, 6))
        ttk.Button(ws_btns, text='Lancia Edge Debug', style='Primary.TButton', command=lambda: self.launch_and_link('edge')).pack(side='left', padx=(0, 8), pady=(0, 6))
        ttk.Button(ws_btns, text='Aggiorna tab', style='Secondary.TButton', command=lambda: self.send('refresh_pages')).pack(side='left', padx=(0, 8), pady=(0, 6))

        self.pages_tree = ttk.Treeview(workspace, columns=('browser', 'sentinel', 'title', 'url'), show='headings', height=9, style='App.Treeview')
        for col,w in [('browser', 95), ('sentinel', 80), ('title', 260), ('url', 420)]:
            self.pages_tree.heading(col, text=col.title())
            self.pages_tree.column(col, width=w, anchor='w')
        self.pages_tree.pack(fill='both', expand=True, pady=(8, 0))
        self.pages_tree.bind('<<TreeviewSelect>>', self.on_page_select)

        monitor_kpis = ttk.Frame(monitor, style='App.TFrame')
        monitor_kpis.pack(fill='x')
        ttk.Label(monitor_kpis, text='Scan', style='Section.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(monitor_kpis, textvariable=self.auto_check_text, style='KPIKey.TLabel').grid(row=0, column=1, sticky='w', padx=(6, 16))
        ttk.Label(monitor_kpis, text='Auto fetch', style='Section.TLabel').grid(row=0, column=2, sticky='w')
        ttk.Label(monitor_kpis, textvariable=self.auto_fetch_text, style='KPIKey.TLabel').grid(row=0, column=3, sticky='w')

        monitor_btns = ttk.Frame(monitor, style='App.TFrame')
        monitor_btns.pack(fill='x', pady=(12, 0))
        for text, cmd in [
            ('START MONITOR', lambda: self.start_monitor(False)),
            ('DRY-RUN', lambda: self.start_monitor(True)),
            ('FETCH CURRENT VIEW', lambda: self.send('fetch')),
            ('PAUSE', self.pause_monitor),
            ('RESUME', self.resume_monitor),
            ('STOP', self.stop_monitor)
        ]:
            style = 'Primary.TButton' if text.startswith('START') else 'Danger.TButton' if text == 'STOP' else 'Secondary.TButton'
            ttk.Button(monitor_btns, text=text, style=style, command=cmd).pack(side='left', padx=(0, 8), pady=(0, 8))

        monitor_extra = ttk.Frame(monitor, style='App.TFrame')
        monitor_extra.pack(fill='x', pady=(8, 0))
        ttk.Button(monitor_extra, text='IGNORE SELECTED', style='Secondary.TButton', command=self.ignore_selected_incident).pack(side='left', padx=(0, 8))
        ttk.Button(monitor_extra, text='UNIGNORE ALL', style='Secondary.TButton', command=self.unignore_all_incidents).pack(side='left')

        self.sla_vars = {
            'sla_critical_minutes': tk.IntVar(value=30), 'sla_high_minutes': tk.IntVar(value=30), 'sla_medium_minutes': tk.IntVar(value=60), 'sla_low_minutes': tk.IntVar(value=60), 'sla_informational_minutes': tk.IntVar(value=60),
            'resolution_critical_minutes': tk.IntVar(value=60), 'resolution_high_minutes': tk.IntVar(value=120), 'resolution_medium_minutes': tk.IntVar(value=480), 'resolution_low_minutes': tk.IntVar(value=720), 'resolution_informational_minutes': tk.IntVar(value=720),
            'misclassification_percent': tk.IntVar(value=1),
            'notification_critical_minutes': tk.IntVar(value=30), 'notification_high_minutes': tk.IntVar(value=60), 'notification_medium_minutes': tk.IntVar(value=240), 'notification_low_minutes': tk.IntVar(value=480), 'notification_informational_minutes': tk.IntVar(value=480),
            'notification_warning_percent': tk.IntVar(value=75), 'notification_repeat_minutes': tk.IntVar(value=30),
            'scan_interval_seconds': tk.IntVar(value=60), 'auto_fetch_interval_seconds': tk.IntVar(value=60),
        }

        self.sla_matrix = ttk.Treeview(
            sla,
            columns=('severity', 'taking', 'notify', 'resolution', 'mis'),
            show='headings',
            height=6,
            style='App.Treeview'
        )
        for col,w in [('severity', 82), ('taking', 110), ('notify', 110), ('resolution', 130), ('mis', 146)]:
            header = {
                'severity': 'Severity',
                'taking': 'Taking Charge',
                'notify': 'Notification',
                'resolution': 'Resolution',
                'mis': 'Misclassification KPI'
            }.get(col, col.title())
            self.sla_matrix.heading(col, text=header)
            self.sla_matrix.column(col, width=w, anchor='center')
        self.sla_matrix.pack(fill='x')
        self.sla_matrix.tag_configure('sev_critical', background='#fef2f2', foreground='#991b1b')
        self.sla_matrix.tag_configure('sev_high', background='#ffedd5', foreground='#9a3412')
        self.sla_matrix.tag_configure('sev_medium', background='#fef9c3', foreground='#854d0e')
        self.sla_matrix.tag_configure('sev_low', background='#ecfccb', foreground='#365314')
        self.sla_matrix.tag_configure('sev_informational', background='#dbeafe', foreground='#1e40af')

        self.sla_advanced_btn = ttk.Button(sla, text='Apri impostazioni avanzate', style='Secondary.TButton', command=self.toggle_sla_settings)
        self.sla_advanced_btn.pack(anchor='w', pady=(10, 8))

        self.sla_advanced = ttk.LabelFrame(sla, text='Impostazioni avanzate', style='Card.TLabelframe', padding=12)
        self.sla_advanced.pack_forget()
        settings_grid = ttk.Frame(self.sla_advanced)
        settings_grid.pack(fill='x')

        def add_setting_row(label_text, var_key, column, row_pos, from_=1, to_=10080):
            ttk.Label(settings_grid, text=label_text, style='Section.TLabel').grid(row=row_pos, column=column * 2, sticky='w', padx=(0, 6), pady=3)
            ttk.Spinbox(settings_grid, from_=from_, to=to_, textvariable=self.sla_vars[var_key], width=8).grid(row=row_pos, column=(column * 2) + 1, padx=(0, 18), pady=3, sticky='w')

        add_setting_row('Critical - Taking charge (min)', 'sla_critical_minutes', 0, 0)
        add_setting_row('Critical - Notification (min)', 'notification_critical_minutes', 0, 1)
        add_setting_row('Critical - Resolution (min)', 'resolution_critical_minutes', 0, 2)
        add_setting_row('High - Taking charge (min)', 'sla_high_minutes', 1, 0)
        add_setting_row('High - Notification (min)', 'notification_high_minutes', 1, 1)
        add_setting_row('High - Resolution (min)', 'resolution_high_minutes', 1, 2)
        add_setting_row('Medium - Taking charge (min)', 'sla_medium_minutes', 2, 0)
        add_setting_row('Medium - Notification (min)', 'notification_medium_minutes', 2, 1)
        add_setting_row('Medium - Resolution (min)', 'resolution_medium_minutes', 2, 2)
        add_setting_row('Low - Taking charge (min)', 'sla_low_minutes', 3, 0)
        add_setting_row('Low - Notification (min)', 'notification_low_minutes', 3, 1)
        add_setting_row('Low - Resolution (min)', 'resolution_low_minutes', 3, 2)
        add_setting_row('Misclassification %', 'misclassification_percent', 4, 0, 0, 100)
        add_setting_row('Windows notification %', 'notification_warning_percent', 4, 1, 1, 100)
        add_setting_row('Ripeti notifica (min)', 'notification_repeat_minutes', 4, 2, 1, 10080)
        add_setting_row('Scan interval (s)', 'scan_interval_seconds', 5, 0, 5, 3600)
        add_setting_row('Auto fetch interval (s)', 'auto_fetch_interval_seconds', 5, 1, 5, 3600)

        actions = ttk.Frame(self.sla_advanced)
        actions.pack(fill='x', pady=(10, 0))
        ttk.Button(actions, text='Salva tutte le impostazioni', style='Primary.TButton', command=self.save_sla).pack(side='left', padx=(0, 8))
        ttk.Button(actions, text='Chiudi', style='Secondary.TButton', command=self.toggle_sla_settings).pack(side='left')

        self.refresh_sla_matrix()

        tabs = ttk.Notebook(root, style='Card.TNotebook')
        tabs.pack(fill='both', expand=True)
        incidents_tab = ttk.Frame(tabs, padding=6, style='App.TFrame')
        logs_tab = ttk.Frame(tabs, padding=6, style='App.TFrame')
        tabs.add(incidents_tab, text='Incidenti')
        tabs.add(logs_tab, text='Actions / logs')

        incident_cols = ('incident', 'severity', 'status', 'owner', 'title', 'created', 'take', 'notify', 'last_warning', 'last_update')
        self.inc_tree = ttk.Treeview(incidents_tab, columns=incident_cols, show='headings', height=14, style='App.Treeview')
        for col,w in [
            ('incident', 95), ('severity', 72), ('status', 72), ('owner', 88), ('title', 250),
            ('created', 95), ('take', 88), ('notify', 88), ('last_warning', 112), ('last_update', 90)
        ]:
            self.inc_tree.heading(col, text=col.title())
            self.inc_tree.column(col, width=w, anchor='center')
        self.inc_tree.pack(fill='both', expand=True, pady=(4, 0))
        self.inc_tree.bind('<Configure>', self._fit_incident_columns)

        self.act_tree = ttk.Treeview(logs_tab, columns=('ts', 'incident', 'action', 'result', 'details'), show='headings', height=14, style='App.Treeview')
        for col,w in [('ts', 120), ('incident', 120), ('action', 170), ('result', 110), ('details', 520)]:
            self.act_tree.heading(col, text=col.title())
            self.act_tree.column(col, width=w, anchor='center')
        self.act_tree.pack(fill='both', expand=True, pady=(4, 0))
        self.act_tree.bind('<Configure>', self._fit_action_columns)

        if hasattr(self.worker, 'settings'):
            self.apply_settings(self.worker.settings_dict())

    def refresh_sla_matrix(self):
        s = getattr(self.worker, 'settings', RuntimeSettings())
        self.sla_matrix.delete(*self.sla_matrix.get_children())

        rows = [
            ('Critical', s.sla_critical_minutes, s.notification_critical_minutes, s.resolution_critical_minutes, 'critical'),
            ('High', s.sla_high_minutes, s.notification_high_minutes, s.resolution_high_minutes, 'high'),
            ('Medium', s.sla_medium_minutes, s.notification_medium_minutes, s.resolution_medium_minutes, 'medium'),
            ('Low', s.sla_low_minutes, s.notification_low_minutes, s.resolution_low_minutes, 'low'),
        ]

        for sev,take,notify,res,tag in rows:
            tag_key = 'sev_' + tag
            self.sla_matrix.insert('', 'end', values=(
                sev,
                f'{take} min',
                f'{notify} min',
                f'{res} min',
                f'<= {s.misclassification_percent}% mensile'
            ), tags=(tag_key,))

    def toggle_sla_settings(self):
        self.advanced_sla_open = not self.advanced_sla_open
        if self.advanced_sla_open:
            self.sla_advanced.pack(fill='x', padx=0, pady=(6, 0))
            self.sla_advanced_btn.config(text='Chiudi impostazioni avanzate')
        else:
            self.sla_advanced.pack_forget()
            self.sla_advanced_btn.config(text='Apri impostazioni avanzate')

    def launch_and_link(self, browser):
        log_file("UI_LAUNCH", f"browser={browser}")
        ok=launch_browser_debug(browser)
        if not ok:
            log_file("UI_LAUNCH_FAIL", f"browser={browser}")
            return

        self.pending_auto_browser='Chrome' if browser=='chrome' else 'Edge'
        self.pending_auto_attempts=8
        self.status_var.set(f"{self.pending_auto_browser} avviato. Collegamento automatico in corso...")

        # Prova piu' volte: Chrome/Edge puo' impiegare alcuni secondi prima di esporre la porta CDP.
        for delay in (1500, 3000, 5000, 8000, 12000, 16000, 20000):
            self.after(delay, lambda:self.send('refresh_pages'))


    def on_close(self):
        log_file("UI_CLOSE", "requested")
        try:
            self.worker.set_runtime_state(running_monitor=False, paused=False, starting=False, auto_fetch_enabled=False, shutdown_requested=True)
        except Exception:
            pass

        try:
            self.send('shutdown')
        except Exception:
            pass

        # Give Playwright/Node a short window to close the pipe cleanly.
        def _finish_close():
            try:
                self.worker.join(timeout=1)
            except Exception:
                pass
            try:
                self.destroy()
            except Exception:
                pass
            log_file("UI_CLOSE", "done")

        self.after(1200, _finish_close)


    def start_monitor(self, dry_run):
        log_file("UI_START", f"dry={dry_run}")
        self.worker.set_runtime_state(dry_run=bool(dry_run), running_monitor=False, paused=False, starting=True, auto_fetch_enabled=False, last_scan_ts=0)
        self.status_var.set('Starting monitor: initial fetch first...')
        self.send('start', dry_run=dry_run)

    def pause_monitor(self):
        log_file("UI_PAUSE", "")
        self.worker.set_runtime_state(paused=True, auto_fetch_enabled=False)
        self.status_var.set('Monitor paused. Auto-fetch disabled.')
        self.send('pause')

    def resume_monitor(self):
        log_file("UI_RESUME", "")
        self.worker.set_runtime_state(paused=False, running_monitor=True, auto_fetch_enabled=False)
        self.status_var.set('Monitor resumed.')
        self.send('resume')

    def stop_monitor(self):
        log_file("UI_STOP", "")
        self.worker.set_runtime_state(running_monitor=False, paused=False, starting=False, auto_fetch_enabled=False)
        self.status_var.set('Monitor stopped. Auto-fetch disabled.')
        self.send('stop')

    def ignore_selected_incident(self):
        log_file("UI_IGNORE_CLICK", "")
        sel = self.inc_tree.selection()
        if not sel:
            messagebox.showinfo('Ignore incident', 'Seleziona prima una riga nella dashboard incident.')
            return
        vals = self.inc_tree.item(sel[0], 'values')
        if not vals:
            return
        incident_key = vals[0]
        if not incident_key:
            return
        log_file("UI_IGNORE_SELECTED", f"incident_key={incident_key}")
        self.send('ignore_incident', incident_key=incident_key)
        self.status_var.set(f'Incident {incident_key} ignored locally.')
    def _enqueue_windows_action(self, payload):
        if not isinstance(payload, dict):
            return
        self.out_q.put({'kind': 'sla_action', **payload})
    def _log_sla_action(self, payload, result):
        key = payload.get('incident_key') or '-'
        title = payload.get('incident_title') or '-'
        sev = (payload.get('severity') or '').strip().lower()
        action = (payload.get('action') or '')
        self.store.log_action(
            key,
            title,
            'SLA_NOTIFICATION_ACTION',
            result,
            f'action={action};severity={sev}'
        )

    def unignore_all_incidents(self):
        self.send('unignore_all')
        self.status_var.set('All ignored incidents restored. Press FETCH CURRENT VIEW to reload visible incidents.')

    def save_sla(self):
        payload = {k:v.get() for k,v in self.sla_vars.items()}
        log_file("UI_SAVE_SLA", f"keys={len(payload)}")
        self.send('settings', values=payload)
    def on_page_select(self,_=None):
        log_file("UI_PAGE_SELECT_CLICK", "")
        sel=self.pages_tree.selection()
        if not sel: return
        meta=self.page_items.get(sel[0]);
        if meta: self.send('select_page', page_id=meta['page_id']); self.status_var.set(f"Selected: {meta.get('browser')} - {meta.get('title','')[:70]}")
    def refresh_pages(self,pages, connected=None):
        log_file("UI_REFRESH_PAGES", f"incoming={len(pages)}")
        self.pages_tree.delete(*self.pages_tree.get_children()); self.page_items={}
        connected = connected or []
        connected_set = set(connected)
        self.chrome_state_var.set('Chrome: connesso' if 'Chrome' in connected_set else 'Chrome: offline')
        self.edge_state_var.set('Edge: connesso' if 'Edge' in connected_set else 'Edge: offline')

        first_candidate=None
        first_same_browser=None

        for i,p in enumerate(pages):
            iid=f'page_{i}'
            self.pages_tree.insert('', 'end', iid=iid, values=(p.get('browser'), 'Yes' if p.get('is_sentinel') else 'No', p.get('title'), p.get('url')))
            self.page_items[iid]=p

            if self.pending_auto_browser and p.get('browser')==self.pending_auto_browser:
                if first_same_browser is None:
                    first_same_browser=iid
                url=(p.get('url') or '').lower()
                title=(p.get('title') or '').lower()
                if p.get('is_sentinel') or 'portal.azure.com' in url or 'sentinel' in title:
                    first_candidate=iid

        # Auto-link: dopo Launch Chrome/Edge seleziona automaticamente la nuova tab Azure/Sentinel.
        if self.pending_auto_browser:
            target=first_candidate or first_same_browser
            if target:
                self.pages_tree.selection_set(target)
                self.pages_tree.focus(target)
                self.pages_tree.see(target)
                self.on_page_select()
                meta=self.page_items.get(target,{})
                self.status_var.set(f"Auto-linked: {meta.get('browser')} - {meta.get('title','')[:90]}")
                self.pending_auto_browser=None
                self.pending_auto_attempts=0
            else:
                self.pending_auto_attempts-=1
                if self.pending_auto_attempts>0:
                    self.status_var.set(f"Waiting for {self.pending_auto_browser} debug tab...")
                else:
                    self.status_var.set(f"Impossibile collegare automaticamente {self.pending_auto_browser}. Premi Refresh browser tabs.")
                    self.pending_auto_browser=None
    def sla_view(self, inc):
        created = inc.get('created_time') or ''
        age_min = created_age_minutes(created)
        if age_min is None:
            return '-', '-'
        return f'{age_min} min', '-'

    def refresh_incidents(self,incs):
        self.inc_tree.delete(*self.inc_tree.get_children())
        incident_settings = self.worker.settings if hasattr(self, 'worker') and getattr(self.worker, 'settings', None) else RuntimeSettings()

        for idx, inc in enumerate(incs):
            created_time = inc.get('created_time','')
            severity = inc.get('severity','')
            status = (inc.get('status') or '').strip().lower()
            sev = (severity or '').strip().lower()
            sev_tag = {
                'critical': 'sev_critical',
                'high': 'sev_high',
                'medium': 'sev_medium',
                'low': 'sev_low',
                'informational': 'sev_informational'
            }.get(sev, 'sev_medium')
            status_tag = 'status_active' if status == 'active' else 'status_closed' if status == 'closed' else None
            tags = ['row_even' if idx % 2 == 0 else 'row_odd', sev_tag]
            if status_tag:
                tags.append(status_tag)

            self.inc_tree.insert('', 'end', values=(
                inc.get('incident_key',''),
                severity,
                inc.get('status',''),
                inc.get('owner',''),
                inc.get('title',''),
                created_time,
                format_remaining_minutes(sla_remaining_from_created(created_time, severity, incident_settings)),
                format_remaining_minutes(customer_notification_remaining_from_created(created_time, severity, incident_settings)),
                format_time_only(inc.get('last_sla_warning_at','')),
                inc.get('last_update_time','')
            ), tags=tuple(tags))
        self._fit_incident_columns()

    def refresh_actions(self,acts):
        self.act_tree.delete(*self.act_tree.get_children())
        for idx, a in enumerate(acts):
            result = (a.get('result') or '').strip().lower()
            action_tags = ['row_even' if idx % 2 == 0 else 'row_odd']
            if result in ('success', 'sent', 'verified', 'would_do'):
                action_tags.append('act_success')
            elif result in ('failed', 'error', 'skip', 'skip_other_owner', 'not_found'):
                action_tags.append('act_failed')
            self.act_tree.insert('', 'end', values=(a.get('ts',''),a.get('incident_key',''),a.get('action',''),a.get('result',''),a.get('details','')), tags=tuple(action_tags))
        self._fit_action_columns()

    def _fit_incident_columns(self, _event=None):
        if not hasattr(self, 'inc_tree'):
            return
        try:
            width = self.inc_tree.winfo_width()
        except Exception:
            return
        if width <= 0:
            return
        fixed = 95 + 72 + 72 + 88 + 95 + 88 + 88 + 112 + 90
        title_w = max(250, int(width - fixed - 24))
        self.inc_tree.column('title', width=title_w)

    def _fit_action_columns(self, _event=None):
        if not hasattr(self, 'act_tree'):
            return
        try:
            width = self.act_tree.winfo_width()
        except Exception:
            return
        if width <= 0:
            return
        fixed = 120 + 120 + 170 + 110
        details_w = max(220, int(width - fixed - 24))
        self.act_tree.column('details', width=details_w)
    def apply_settings(self,s):
        log_file("UI_APPLY_SETTINGS", f"keys={list((s or {}).keys())}")
        scan_interval = None
        auto_fetch_interval = None
        for k,v in (s or {}).items():
            if k in self.sla_vars:
                try: self.sla_vars[k].set(int(v))
                except Exception: pass
                if k == 'scan_interval_seconds':
                    try: scan_interval = int(v)
                    except Exception: scan_interval = None
                if k == 'auto_fetch_interval_seconds':
                    try: auto_fetch_interval = int(v)
                    except Exception: auto_fetch_interval = None

        if scan_interval is None:
            try:
                scan_interval = int(self.sla_vars['scan_interval_seconds'].get())
            except Exception:
                scan_interval = None
        if scan_interval is not None and scan_interval > 0:
            self.auto_check_text.set(f'Auto-check: {scan_interval}s')
        if auto_fetch_interval is None:
            try:
                auto_fetch_interval = int(self.sla_vars['auto_fetch_interval_seconds'].get())
            except Exception:
                auto_fetch_interval = None
        if auto_fetch_interval is not None and auto_fetch_interval > 0:
            self.auto_fetch_text.set(f'Auto-fetch: {auto_fetch_interval}s')
        self.refresh_sla_matrix()
    def poll_worker(self):
        try:
            _winotify_update()
            while True:
                msg=self.out_q.get_nowait(); kind=msg.get('kind')
                if kind=='pages':
                    log_file("UI_POLL", f"kind=pages;count={len(msg.get('pages',[]))}")
                    self.refresh_pages(msg.get('pages',[]), msg.get('connected',[]));
                    if not self.pending_auto_browser and not self.pages_tree.selection():
                        self.status_var.set('Browser connected: '+(', '.join(msg.get('connected',[])) or 'none')+'. Select the Sentinel tab.')
                elif kind=='status':
                    log_file("UI_POLL", f"kind=status;message={msg.get('message','')[:120]}")
                    self.status_var.set(msg.get('message','')); self.apply_settings(msg.get('settings',{}))
                elif kind=='scan_result':
                    log_file("UI_POLL", f"kind=scan_result;scanned={msg.get('scanned')};processed={msg.get('processed')};warnings={msg.get('warnings')}")
                    self.status_var.set(f"Scan done. Seen={msg.get('scanned')}, processed={msg.get('processed')}, SLA notifications={msg.get('warnings')}"); self.refresh_incidents(msg.get('incidents',[])); self.refresh_actions(msg.get('actions',[])); self.apply_settings(msg.get('settings',{}))
                elif kind=='sla_confirm':
                    log_file("UI_POLL", "kind=sla_confirm")
                    key = msg.get('incident_key') or '-'
                    title = msg.get('incident_title') or '-'
                    severity = (msg.get('severity') or '').strip().lower()
                    age = msg.get('age')
                    threshold = msg.get('threshold')
                    confirm = messagebox.askyesno(
                        'Conferma notifica',
                        f'Allerta {severity.upper()} rilevata per {key}\\n{title}\\nEtà: {age}/{threshold} minuti\\n\\nConfermi ricezione e presa in carico?'
                    )
                    self._log_sla_action(msg, 'CONFIRMED' if confirm else 'DISMISSED')
                elif kind=='sla_action':
                    log_file("UI_POLL", f"kind=sla_action;action={msg.get('action')};severity={msg.get('severity')}")
                    action = msg.get('action') or '-'
                    sev = (msg.get('severity') or '').strip().lower()
                    if action in ('confirm', 'dismiss'):
                        self.status_var.set(f"Notifica Windows {action} - {sev.upper()} {msg.get('incident_key','-')}")
                elif kind=='error':
                    log_file("UI_POLL", f"kind=error;message={msg.get('message','')[:120]}")
                    self.status_var.set('ERROR: '+msg.get('message','')); self.refresh_actions(msg.get('actions',[])); messagebox.showwarning('monitor error', msg.get('message','Unknown error'))
        except queue.Empty: pass
        self.after(700,self.poll_worker)

if __name__=='__main__': NotifierApp().mainloop()



