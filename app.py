
import math, os, queue, re, shutil, sqlite3, subprocess, threading, time, tkinter as tk, sys, traceback
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

APP_LOG_PATH = LOG_DIR / "app.log"

def log_file(event, details="", exc=None):
    """
    Append diagnostic information to logs/app.log.
    This is intentionally simple and dependency-free so it also works when UI/DB logging fails.
    """
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        msg = f"[{ts}] {event}"
        if details:
            msg += f" | {details}"
        if exc is not None:
            msg += "\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with APP_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

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


def minutes_since_timestamp(value):
    """
    Handles both old UTC-aware timestamps and new local system timestamps.
    """
    dt = parse_iso(value)
    if not dt:
        return None

    if getattr(dt, "tzinfo", None) is not None:
        return int((now_utc() - dt).total_seconds() // 60)

    return int((datetime.now() - dt).total_seconds() // 60)


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
        "%m/%d/%y %I:%M %p",
        "%m/%d/%Y %I:%M %p",
        "%d/%m/%y %I:%M %p",
        "%d/%m/%Y %I:%M %p",
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


def notify_remaining_from_created(created_time, severity, settings):
    return remaining_minutes_from_created(created_time, settings.warning_at(severity))


def customer_notification_remaining_from_created(created_time, severity, settings):
    return remaining_minutes_from_created(created_time, settings.notification_for(severity))


def clamp_int(v, default, lo, hi):
    try: x = int(v)
    except Exception: x = default
    return max(lo, min(hi, x))

def notify_windows(title, message):
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=15, app_name="Sentinel Auto Assign Bot")
    except Exception:
        pass
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass

class Storage:
    def __init__(self, path: Path):
        self.path = path
        self.init_db()
    def connect(self): return sqlite3.connect(self.path)
    def init_db(self):
        with self.connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS incidents(
                incident_key TEXT PRIMARY KEY, title TEXT, severity TEXT, status TEXT, owner TEXT,
                created_time TEXT, last_update_time TEXT, activated_at TEXT, activated_by_bot INTEGER DEFAULT 0,
                first_seen_active TEXT, last_seen TEXT, sla_warning_sent INTEGER DEFAULT 0,
                last_sla_warning_at TEXT, workspace_hint TEXT, source_page TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS actions(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, incident_key TEXT, title TEXT,
                action TEXT, result TEXT, details TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY, value TEXT)''')
    def load_settings(self):
        with self.connect() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT key,value FROM settings").fetchall()
        return {r['key']: r['value'] for r in rows}
    def save_settings(self, settings):
        with self.connect() as con:
            for k,v in settings.items():
                con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(k), str(v)))
    def log_action(self, key, title, action, result, details=""):
        with self.connect() as con:
            con.execute("INSERT INTO actions(ts,incident_key,title,action,result,details) VALUES(?,?,?,?,?,?)", (now_iso(), key, title, action, result, details))

    def log_system(self, action, result, details=""):
        try:
            self.log_action("__SYSTEM__", "System", action, result, details)
        except Exception as e:
            log_file("DB_LOG_SYSTEM_FAILED", f"{action} {result} {details}", e)
    def upsert_seen(self, key, title, severity, status, owner, created="", last_update="", workspace="", source=""):
        ts = now_iso(); first_active = ts if (status or '').lower() == 'active' else None
        with self.connect() as con:
            con.execute('''INSERT INTO incidents(incident_key,title,severity,status,owner,created_time,last_update_time,first_seen_active,last_seen,workspace_hint,source_page)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(incident_key) DO UPDATE SET
                title=excluded.title, severity=COALESCE(NULLIF(excluded.severity,''),incidents.severity),
                status=excluded.status, owner=excluded.owner, created_time=COALESCE(NULLIF(excluded.created_time,''),incidents.created_time),
                last_update_time=COALESCE(NULLIF(excluded.last_update_time,''),incidents.last_update_time),
                first_seen_active=CASE WHEN excluded.status='Active' THEN COALESCE(incidents.first_seen_active, excluded.first_seen_active) ELSE incidents.first_seen_active END,
                last_seen=excluded.last_seen, workspace_hint=COALESCE(NULLIF(excluded.workspace_hint,''),incidents.workspace_hint),
                source_page=COALESCE(NULLIF(excluded.source_page,''),incidents.source_page)''',
                (key,title,severity,status,owner,created,last_update,first_active,ts,workspace,source))
    def mark_activated(self, key, title, severity="", created="", last_update="", workspace="", source=""):
        ts = now_iso()
        with self.connect() as con:
            con.execute('''INSERT INTO incidents(incident_key,title,severity,status,owner,created_time,last_update_time,activated_at,activated_by_bot,first_seen_active,last_seen,workspace_hint,source_page)
                VALUES(?,?,?,'Active','me',?,?,?,1,?,?,?,?)
                ON CONFLICT(incident_key) DO UPDATE SET title=excluded.title, severity=COALESCE(NULLIF(excluded.severity,''),incidents.severity),
                status='Active', owner='me', created_time=COALESCE(NULLIF(excluded.created_time,''),incidents.created_time),
                last_update_time=COALESCE(NULLIF(excluded.last_update_time,''),incidents.last_update_time),
                activated_at=COALESCE(incidents.activated_at,excluded.activated_at), activated_by_bot=1,
                first_seen_active=COALESCE(incidents.first_seen_active,excluded.first_seen_active), last_seen=excluded.last_seen,
                workspace_hint=COALESCE(NULLIF(excluded.workspace_hint,''),incidents.workspace_hint), source_page=COALESCE(NULLIF(excluded.source_page,''),incidents.source_page)''',
                (key,title,severity,created,last_update,ts,ts,ts,workspace,source))
    def sync_visible_incidents(self, visible_keys):
        keys = [str(k) for k in visible_keys if k]
        if not keys:
            return
        with self.connect() as con:
            placeholders = ','.join(['?'] * len(keys))
            con.execute(f"DELETE FROM incidents WHERE incident_key NOT IN ({placeholders})", keys)

    def incidents(self, limit=500):

        with self.connect() as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute("SELECT * FROM incidents ORDER BY last_seen DESC LIMIT ?", (limit,)).fetchall()]
    def active_incidents(self):
        with self.connect() as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute("SELECT * FROM incidents WHERE status='Active' ORDER BY COALESCE(activated_at,first_seen_active) ASC").fetchall()]
    def actions(self, limit=100):
        with self.connect() as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    def mark_sla_warning(self, key):
        with self.connect() as con:
            con.execute("UPDATE incidents SET sla_warning_sent=1,last_sla_warning_at=? WHERE incident_key=?", (local_now_iso(), key))

@dataclass
class RuntimeSettings:
    # Taking Charge Time KPI: time to take ownership/assign the incident.
    scan_interval_seconds:int=45
    sla_critical_minutes:int=30; sla_high_minutes:int=30; sla_medium_minutes:int=60; sla_low_minutes:int=60; sla_informational_minutes:int=60

    # Notification Time KPI: customer/user notification timing. Popup notifications are based on this KPI.
    notification_critical_minutes:int=30; notification_high_minutes:int=60; notification_medium_minutes:int=240; notification_low_minutes:int=480; notification_informational_minutes:int=480

    repeat_notification_minutes:int=10; auto_fetch_interval_seconds:int=20; my_owner_identity:str=''

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
        return self.notification_for(sev)


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

    for key in [
        'scan_interval_seconds',
        'sla_critical_minutes','sla_high_minutes','sla_medium_minutes','sla_low_minutes','sla_informational_minutes',
        'notification_critical_minutes','notification_high_minutes','notification_medium_minutes','notification_low_minutes','notification_informational_minutes',
        'repeat_notification_minutes','auto_fetch_interval_seconds'
    ]:
        if key in saved:
            default = getattr(s, key)
            lo, hi = (5, 3600) if key == 'auto_fetch_interval_seconds' else (10, 3600) if key == 'scan_interval_seconds' else (1, 10080)
            setattr(s, key, clamp_int(saved.get(key), default, lo, hi))

    s.my_owner_identity = saved.get('my_owner_identity', '') or ''
    return s

class SentinelPageBot:
    def __init__(self, page, store, settings):
        self.page = page
        self.store = store
        self.settings = settings
        self.can_continue = lambda: True

    def wait(self, ms=1000):
        self.page.wait_for_timeout(ms)

    def body(self):
        try:
            return self.page.locator('body').inner_text(timeout=15000)
        except Exception:
            return ''

    def is_incidents_page(self):
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
            return m.group(2), normalize_text(m.group(3)), severity

        m = re.search(r"\b(\d{3,})\b", text)
        if m:
            key = m.group(1)
            idx = text.find(key)
            return key, (text[idx + len(key):].strip()[:160] or key), severity

        return None, '', severity

    def visible_incident_snapshot(self, max_rows=80):
        """
        Snapshot iniziale degli incident visibili.
        Salva gli ID prima di fare qualsiasi click. Così, se una riga sparisce,
        cambia posizione o la lista si riordina dopo l'assegnazione, il bot lavora
        comunque per ID e non per indice statico.
        """
        rows = self.page.get_by_role('row')
        out = []
        seen = set()

        try:
            count = min(rows.count(), max_rows)
        except Exception:
            return out

        for i in range(count):
            try:
                txt = rows.nth(i).inner_text(timeout=1200)
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

        return out

    def find_row_index_by_incident_id(self, incident_key, max_rows=120):
        """
        Cerca dinamicamente la riga con l'ID richiesto nella vista corrente.
        Non usa l'indice vecchio, perché dopo assign/status la lista può cambiare.
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
            if line.lower() == 'last update time' and i + 1 < len(lines):
                last_update = lines[i + 1]

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
        Verifica reale dalla UI: owner non deve più essere Unassigned.
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
        self.wait(300)

    def click_status_fallback(self):
        # Zoom/screen safe: locate Status label and click its value above it.
        if self.click_field_value_by_label('Status', ['New'], timeout=1200):
            return
        # Fallback: click any New text in the actual detail pane.
        self.click_text_in_right_pane(['New'], exact_first=True, timeout=1200, max_y_ratio=0.55)
        self.wait(300)

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

    def assign_to_me_current_open_id(self, incident_key):
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
            # Fallback: clicca valore Unassigned solo dopo aver già verificato che l'owner è Unassigned.
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
            # Fallback: clicca valore New solo dopo aver già verificato che lo status è New.
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

        panel, d = self.open_incident_by_id(expected_key)
        if panel is None or d is None:
            self.store.log_action(expected_key, fallback_title, 'OPEN_BY_ID', 'SKIP', 'row not found or opened ID mismatch')
            return False, False

        key = expected_key
        title = fallback_title
        severity = fallback_severity or d['severity']
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
            return True, False

        # Dry-run: ragiona come il real bot, ma non clicca.
        if dry_run:
            planned = []
            if self.owner_is_unassigned(owner):
                planned.append('AssignToMe')
            if self.status_is_new(status):
                planned.append('SetActive')
            if planned:
                self.store.log_action(key, title, 'DRY_RUN', 'WOULD_DO', ','.join(planned))
                return True, True
            self.store.log_action(key, title, 'DRY_RUN', 'NO_ACTION', f'status={status}, owner={owner}')
            return True, False

        processed = False

        # 1. Owner check: se è davvero Unassigned, assegna a me.
        # Se non è Unassigned, non tocca l'owner.
        if self.owner_is_unassigned(owner):
            owner_before = owner
            ok, result = self.assign_to_me_current_open_id(key)
            if not ok:
                self.store.log_action(key, title, 'ASSIGN_TO_ME', 'FAILED', str(result))
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
            self.store.log_action(key, title, 'ASSIGN_TO_ME', 'SUCCESS_VERIFIED', f'owner_before={owner_before}, owner_after={owner}')

        else:
            self.store.log_action(key, title, 'ASSIGN_TO_ME', 'SKIP', f'owner={owner}')

        # 2. Status check: change Status only if the incident is now assigned to me.
        # If it is assigned to another user, do not assign and do not change status.
        if (not self.owner_is_unassigned(owner)) and (not self.owner_is_me(owner)):
            self.store.log_action(key, title, 'SET_ACTIVE', 'SKIP_OTHER_OWNER', f'owner={owner}')
            return True, processed

        # Prima di cliccare ricontrolla il detail pane dello stesso ID, perché la UI può aggiornarsi.
        panel2, d2 = self.read_open_incident_details(key)
        if panel2 is None or d2 is None:
            self.store.log_action(key, title, 'SET_ACTIVE', 'SKIP', 'ID mismatch before final status check')
            return True, processed

        status = d2.get('status', status)
        owner = d2.get('owner', owner)
        severity = d2.get('severity') or severity

        if (not self.owner_is_unassigned(owner)) and (not self.owner_is_me(owner)):
            self.store.log_action(key, title, 'SET_ACTIVE', 'SKIP_OTHER_OWNER_AFTER_REREAD', f'owner={owner}')
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
                self.click_toolbar_refresh()
            else:
                self.store.upsert_seen(
                    key, title, severity, status, owner,
                    d2.get('created_time', ''), d2.get('last_update_time', ''),
                    workspace, source
                )
                self.store.log_action(key, title, 'SET_ACTIVE', 'FAILED_VERIFY', f'status_before={status_before}, status_after={status}')

        else:
            if self.status_is_active(status):
                # Traccia comunque gli Active per SLA.
                self.store.mark_activated(
                    key, title, severity,
                    d2.get('created_time', ''), d2.get('last_update_time', ''),
                    workspace, source
                )
            self.store.log_action(key, title, 'SET_ACTIVE', 'SKIP', f'status={status}')

        return True, processed

    def scan(self, dry_run, fetch_only):
        if not self.is_incidents_page():
            raise RuntimeError('La tab selezionata non sembra essere Microsoft Sentinel > Incidents.')

        # Non ricaricare la pagina: usa la vista corrente, senza cambiare filtri o refreshare la blade.
        self.wait(300)

        snapshot = self.visible_incident_snapshot()
        scanned = 0
        processed = 0

        for target in snapshot:
            if (not fetch_only) and not self.can_continue():
                break
            s, p = self.process_incident_by_id(target, dry_run, fetch_only)
            scanned += 1 if s else 0
            processed += 1 if p else 0

        # Remove stale incidents from dashboard that are no longer present in the current Sentinel view.
        self.store.sync_visible_incidents([x.get('incident_key') for x in snapshot])

        return scanned, processed


class BotWorker(threading.Thread):
    def __init__(self, in_q, out_q, store):
        super().__init__(daemon=True); self.in_q=in_q; self.out_q=out_q; self.store=store; self.settings=runtime_settings_from_storage(store); self.state_lock=threading.RLock(); self.operation_lock=threading.RLock(); self.running_bot=False; self.paused=False; self.dry_run=True; self.auto_fetch_enabled=True; self.starting=False; self.shutdown_requested=False; self.target_page_id=None; self.pages={}; self.browsers=[]; self.playwright=None; self.last_scan_ts=0; self.last_fetch_ts=0
    def emit(self,kind,payload): self.out_q.put({'kind':kind, **payload})
    def set_runtime_state(self, **changes):
        with self.state_lock:
            for key, value in changes.items():
                setattr(self, key, value)

    def get_runtime_state(self):
        with self.state_lock:
            return {
                'running_bot': self.running_bot,
                'paused': self.paused,
                'dry_run': self.dry_run,
                'last_scan_ts': self.last_scan_ts,
                'auto_fetch_enabled': self.auto_fetch_enabled,
                'starting': self.starting,
                'shutdown_requested': self.shutdown_requested,
            }

    def can_continue_flag(self):
        with self.state_lock:
            return self.running_bot and not self.paused and not self.shutdown_requested

    def connect_browsers(self):
        if self.playwright is None: self.playwright=sync_playwright().start()
        self.pages={}; self.browsers=[]; connected=[]
        for name,port in [('Chrome',CHROME_DEBUG_PORT),('Edge',EDGE_DEBUG_PORT)]:
            try:
                br=self.playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{port}'); self.browsers.append((name,br)); connected.append(name)
            except Exception: pass
        return connected
    def refresh_pages(self):
        connected=self.connect_browsers(); rows=[]; self.pages={}
        for bname,br in self.browsers:
            for cidx,ctx in enumerate(br.contexts):
                for pidx,page in enumerate(ctx.pages):
                    url=page.url or ''
                    try: title=page.title()
                    except Exception: title=''
                    pid=f'{bname}:{cidx}:{pidx}:{abs(hash(url+title))}'; self.pages[pid]=page
                    is_sentinel=('portal.azure.com' in url or 'security.microsoft.com' in url or 'sentinel' in title.lower())
                    rows.append({'page_id':pid,'browser':bname,'title':title[:160],'url':url,'is_sentinel':is_sentinel})
        self.emit('pages', {'pages':rows,'connected':connected})
    def selected_page(self):
        if not self.target_page_id: raise RuntimeError('Nessuna tab Sentinel selezionata.')
        page=self.pages.get(self.target_page_id)
        if page is None:
            raise RuntimeError('Tab selezionata non più disponibile. Premi Refresh browser tabs.')
        try:
            if page.is_closed():
                raise RuntimeError('Tab selezionata chiusa. Premi Refresh browser tabs e seleziona di nuovo Sentinel.')
        except AttributeError:
            pass
        return page
    def settings_dict(self): return self.settings.__dict__.copy()
    def update_settings(self, vals):
        int_fields = [
            'scan_interval_seconds',
            'sla_critical_minutes','sla_high_minutes','sla_medium_minutes','sla_low_minutes','sla_informational_minutes',
            'notification_critical_minutes','notification_high_minutes','notification_medium_minutes','notification_low_minutes','notification_informational_minutes',
            'repeat_notification_minutes','auto_fetch_interval_seconds'
        ]
        for key in int_fields:
            default = getattr(self.settings, key)
            lo, hi = (5, 3600) if key == 'auto_fetch_interval_seconds' else (10, 3600) if key == 'scan_interval_seconds' else (1, 10080)
            setattr(self.settings, key, clamp_int(vals.get(key), default, lo, hi))

        self.store.save_settings(self.settings_dict()); self.emit('status', {'message':'Taking Charge / Notification SLA settings saved','settings':self.settings_dict()})
    def check_sla(self):
        warnings = 0
        for inc in self.store.incidents():
            status = (inc.get('status') or '').lower()
            if status == 'closed':
                continue
            created = inc.get('created_time') or ''
            age = created_age_minutes(created)
            if age is None:
                continue
            sev = inc.get('severity') or 'Medium'
            notify_due = self.settings.notification_for(sev)
            if age < notify_due:
                continue
            last_minutes = minutes_since_timestamp(inc.get('last_sla_warning_at'))
            if last_minutes is not None and last_minutes < self.settings.repeat_notification_minutes:
                continue
            key = inc.get('incident_key') or '-'
            title = inc.get('title') or '-'
            nt = 'Sentinel Notification Time reached'
            message = f'Incident {key} reached Notification Time: {age}/{notify_due} min ({sev}). {title}'
            notify_windows(nt, message)
            self.emit('sla_alert', {
                'title': nt,
                'message': message,
                'incident_key': key,
                'incident_title': title,
                'severity': sev,
                'age': age,
                'sla': notify_due,
                'warning_at': notify_due,
            })
            self.store.mark_sla_warning(key)
            self.store.log_action(key, title, 'SLA_NOTIFICATION', 'SENT', f'age={age}, notification_due={notify_due}, severity={sev}, created={created}')
            warnings += 1
        return warnings
    def run_scan(self, fetch_only=False):
        """
        Runs exactly one browser operation at a time.
        This prevents auto-fetch and bot actions from touching the same Sentinel tab together.
        """
        with self.operation_lock:
            state = self.get_runtime_state()
            if state.get('shutdown_requested'):
                self.store.log_system('SCAN', 'SKIP_SHUTDOWN', f'fetch_only={fetch_only}')
                return 0, 0

            if (not fetch_only) and (not self.can_continue_flag()):
                self.store.log_system('SCAN', 'SKIP_STOPPED', 'Bot stopped or paused before scan start')
                return 0, 0

            page = self.selected_page()
            self.store.log_system('FETCH' if fetch_only else 'SCAN', 'START', f'url={getattr(page, "url", "")}')

            try:
                bot = SentinelPageBot(page, self.store, self.settings)
                bot.can_continue = (lambda: not self.get_runtime_state().get('shutdown_requested')) if fetch_only else self.can_continue_flag
                scanned, processed = bot.scan(state['dry_run'], fetch_only)
                warnings = self.check_sla()

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
                return scanned, processed

            except Exception as e:
                details = f'fetch_only={fetch_only}; error={type(e).__name__}: {e}'
                log_file('RUN_SCAN_ERROR', details, e)
                self.store.log_system('FETCH' if fetch_only else 'SCAN', 'ERROR', details)
                self.emit('error', {'message': details, 'actions': self.store.actions()})
                return 0, 0

    def cleanup_playwright(self):
        try:
            for _, br in list(self.browsers):
                try:
                    br.close()
                except Exception as e:
                    log_file('BROWSER_CONNECTION_CLOSE_ERROR', '', e)
            self.browsers = []
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
        try:
            if a == 'refresh_pages':
                self.refresh_pages()

            elif a == 'select_page':
                self.target_page_id = cmd.get('page_id')
                self.store.log_system('SELECT_PAGE', 'SUCCESS', str(self.target_page_id))
                self.emit('status', {'message':f'Selected page: {self.target_page_id}', 'settings':self.settings_dict()})

            elif a == 'fetch':
                # Manual fetch is allowed, but still serialized with every other browser operation.
                self.set_runtime_state(auto_fetch_enabled=True, starting=False)
                self.emit('status', {'message':'Fetching selected Sentinel tab without refreshing page...', 'settings':self.settings_dict()})
                self.run_scan(fetch_only=True)
                self.last_fetch_ts = time.time()

            elif a == 'start':
                dry = bool(cmd.get('dry_run', True))
                self.set_runtime_state(dry_run=dry, running_bot=False, paused=False, starting=True, auto_fetch_enabled=False, last_scan_ts=0)
                self.store.log_system('BOT_START_REQUEST', 'RECEIVED', 'mode=' + ('dry-run' if dry else 'real'))
                self.emit('status', {'message':'Initial fetch before bot start...', 'settings':self.settings_dict()})

                # Initial fetch first, then enable the real/dry-run bot.
                self.run_scan(fetch_only=True)
                if not self.get_runtime_state().get('shutdown_requested'):
                    self.set_runtime_state(dry_run=dry, running_bot=True, paused=False, starting=False, auto_fetch_enabled=False, last_scan_ts=0)
                    self.emit('status', {'message':'Bot started in '+('dry-run' if dry else 'real')+' mode after initial fetch', 'settings':self.settings_dict()})
                    self.store.log_system('BOT_START', 'SUCCESS', 'mode=' + ('dry-run' if dry else 'real'))

            elif a == 'pause':
                self.set_runtime_state(paused=True, auto_fetch_enabled=False)
                self.store.log_system('BOT_PAUSE', 'SUCCESS', '')
                self.emit('status', {'message':'Bot paused. Auto-fetch disabled.', 'settings':self.settings_dict()})

            elif a == 'resume':
                self.set_runtime_state(paused=False, running_bot=True, auto_fetch_enabled=False)
                self.store.log_system('BOT_RESUME', 'SUCCESS', '')
                self.emit('status', {'message':'Bot resumed. Auto-fetch disabled while bot is running.', 'settings':self.settings_dict()})

            elif a == 'stop':
                # Stop means stop bot and stop background auto-fetch.
                self.set_runtime_state(running_bot=False, paused=False, starting=False, auto_fetch_enabled=False)
                self.store.log_system('BOT_STOP', 'SUCCESS', 'Bot stopped; auto-fetch disabled')
                self.emit('status', {'message':'Bot stopped. Auto-fetch disabled; use FETCH CURRENT VIEW NOW for manual refresh.', 'settings':self.settings_dict()})

            elif a == 'settings':
                self.update_settings(cmd.get('values',{}))

            elif a == 'shutdown':
                self.set_runtime_state(running_bot=False, paused=False, starting=False, auto_fetch_enabled=False, shutdown_requested=True)
                self.store.log_system('APP_SHUTDOWN', 'REQUESTED', '')
                self.cleanup_playwright()
                self.emit('status', {'message':'Shutdown complete', 'settings':self.settings_dict()})

        except Exception as e:
            details = f'action={a}; error={type(e).__name__}: {e}'
            log_file('HANDLE_ERROR', details, e)
            self.store.log_system('HANDLE', 'ERROR', details)
            self.emit('error', {'message': details, 'actions': self.store.actions()})

    def run(self):
        self.emit('status', {'message':'Worker ready. Click Launch Chrome/Edge for bot: the app will open and auto-link the new tab.','settings':self.settings_dict()})
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

                # Auto-fetch runs only when explicitly enabled and when the bot is fully stopped.
                # It never runs while starting/running/paused to avoid touching the same tab together with the bot.
                state = self.get_runtime_state()
                if (
                    state.get('auto_fetch_enabled')
                    and not state.get('running_bot')
                    and not state.get('paused')
                    and not state.get('starting')
                    and self.target_page_id
                    and time.time() - self.last_fetch_ts >= self.settings.auto_fetch_interval_seconds
                ):
                    self.last_fetch_ts = time.time()
                    self.emit('status', {'message':'Auto-fetch current Sentinel view...', 'settings':self.settings_dict()})
                    self.run_scan(fetch_only=True)

                state = self.get_runtime_state()
                if (
                    state.get('running_bot')
                    and not state.get('paused')
                    and not state.get('starting')
                    and self.target_page_id
                    and time.time() - state.get('last_scan_ts', 0) >= self.settings.scan_interval_seconds
                ):
                    self.set_runtime_state(last_scan_ts=time.time())
                    self.emit('status', {'message':'Automatic bot scan running...', 'settings':self.settings_dict()})
                    self.run_scan(fetch_only=False)

            except Exception as e:
                details = f'worker loop error={type(e).__name__}: {e}'
                log_file('WORKER_LOOP_ERROR', details, e)
                try:
                    self.store.log_system('WORKER_LOOP', 'ERROR', details)
                except Exception:
                    pass
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

def launch_browser_debug(browser):
    """
    Avvia un'istanza Chromium debuggabile e separata dalle finestre normali.
    Questo evita il problema principale: se Chrome è già aperto normalmente,
    Windows/Chrome tende a riusare il processo esistente e la porta 9222 non viene attivata.
    """
    exe=find_chrome_path() if browser=='chrome' else find_edge_path()
    port=CHROME_DEBUG_PORT if browser=='chrome' else EDGE_DEBUG_PORT
    profile_name='chrome_bot_profile' if browser=='chrome' else 'edge_bot_profile'
    profile_dir=(BROWSER_PROFILE_DIR/profile_name).resolve()

    if not exe:
        messagebox.showerror('Browser non trovato', f'{browser} non trovato.')
        return False

    profile_dir.mkdir(parents=True, exist_ok=True)

    args=[
        exe,
        f'--remote-debugging-port={port}',
        '--remote-debugging-address=127.0.0.1',
        '--remote-allow-origins=*',
        f'--user-data-dir={str(profile_dir)}',
        '--no-first-run',
        '--no-default-browser-check',
        '--new-window',
        'https://portal.azure.com/'
    ]

    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        messagebox.showerror('Errore avvio browser', str(e))
        return False

class BotApp(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('Sentinel Auto Assign Bot - Desktop'); self.geometry('1450x880'); self.protocol('WM_DELETE_WINDOW', self.on_close); self.minsize(1150,760)
        self.store=Storage(DB_PATH); self.in_q=queue.Queue(); self.out_q=queue.Queue(); self.worker=BotWorker(self.in_q,self.out_q,self.store); self.worker.start(); self.page_items={}; self.pending_auto_browser=None; self.pending_auto_attempts=0; self.build_ui(); self.after(500,self.poll_worker)
    def send(self, action, **kw): self.in_q.put({'action':action, **kw})
    def build_ui(self):
        root=ttk.Frame(self,padding=10); root.pack(fill='both',expand=True)
        ttk.Label(root,text='Sentinel Auto Assign Bot',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(root,text="App desktop esterna: selezioni la tab Sentinel già aperta. Chrome/Edge supportati; Firefox non può essere agganciato in modo affidabile.",foreground='#475569').pack(anchor='w',pady=(0,8))
        top=ttk.LabelFrame(root,text='1) Browser / workspace selection',padding=10); top.pack(fill='x',pady=(0,8))
        bf=ttk.Frame(top); bf.pack(fill='x')
        ttk.Button(bf,text='Launch Chrome for bot',command=lambda:self.launch_and_link('chrome')).pack(side='left',padx=(0,6))
        ttk.Button(bf,text='Launch Edge for bot',command=lambda:self.launch_and_link('edge')).pack(side='left',padx=(0,6))
        ttk.Button(bf,text='Refresh browser tabs',command=lambda:self.send('refresh_pages')).pack(side='left',padx=(0,6))
        ttk.Label(top,text="Clicca Launch: l\'app apre il browser e lo collega automaticamente. Poi fai login, MFA, PIM e apri Sentinel > Incidents. Con più workspace, seleziona la tab corretta.",foreground="#475569").pack(anchor="w",pady=(8,4))
        self.pages_tree=ttk.Treeview(top,columns=('browser','sentinel','title','url'),show='headings',height=6)
        for col,w in [('browser',90),('sentinel',80),('title',420),('url',760)]: self.pages_tree.heading(col,text=col.title()); self.pages_tree.column(col,width=w,anchor='w')
        self.pages_tree.pack(fill='x'); self.pages_tree.bind('<<TreeviewSelect>>', self.on_page_select)
        ctr=ttk.LabelFrame(root,text='2) Bot controls',padding=10); ctr.pack(fill='x',pady=(0,8))
        for text,cmd in [
            ('FETCH CURRENT VIEW NOW',lambda:self.send('fetch')),
            ('START REAL BOT',lambda:self.start_bot(False)),
            ('START DRY-RUN',lambda:self.start_bot(True)),
            ('PAUSE',self.pause_bot),
            ('RESUME',self.resume_bot),
            ('STOP',self.stop_bot)
        ]: ttk.Button(ctr,text=text,command=cmd).pack(side='left',padx=(0,6))
        self.status_var=tk.StringVar(value='Ready'); ttk.Label(ctr,textvariable=self.status_var,foreground='#0f172a').pack(side='left',padx=(16,0)); ttk.Label(ctr,text='Logs: data/bot_state.sqlite3 + logs/app.log',foreground='#64748b').pack(side='right',padx=(8,0))
        sla=ttk.LabelFrame(root,text='3) SLA settings',padding=10); sla.pack(fill='x',pady=(0,8))
        self.sla_vars={
            'sla_critical_minutes':tk.IntVar(value=30),'sla_high_minutes':tk.IntVar(value=30),'sla_medium_minutes':tk.IntVar(value=60),'sla_low_minutes':tk.IntVar(value=60),'sla_informational_minutes':tk.IntVar(value=60),
            'notification_critical_minutes':tk.IntVar(value=30),'notification_high_minutes':tk.IntVar(value=60),'notification_medium_minutes':tk.IntVar(value=240),'notification_low_minutes':tk.IntVar(value=480),'notification_informational_minutes':tk.IntVar(value=480),
            'scan_interval_seconds':tk.IntVar(value=45),'repeat_notification_minutes':tk.IntVar(value=10),'auto_fetch_interval_seconds':tk.IntVar(value=20)
        }
        sla_grid = ttk.Frame(sla); sla_grid.pack(fill='x')
        headers = ['', 'Critical', 'High', 'Medium', 'Low', 'Info']
        for c, h in enumerate(headers): ttk.Label(sla_grid, text=h, font=('Segoe UI', 9, 'bold')).grid(row=0, column=c, padx=4, pady=2, sticky='w')
        kpi_rows = [
            ('Taking Charge', ['sla_critical_minutes','sla_high_minutes','sla_medium_minutes','sla_low_minutes','sla_informational_minutes']),
            ('Notification', ['notification_critical_minutes','notification_high_minutes','notification_medium_minutes','notification_low_minutes','notification_informational_minutes']),
        ]
        for r, (row_name, keys) in enumerate(kpi_rows, start=1):
            ttk.Label(sla_grid, text=row_name).grid(row=r, column=0, padx=4, pady=2, sticky='w')
            for c, key in enumerate(keys, start=1): ttk.Spinbox(sla_grid, from_=1, to=10080, textvariable=self.sla_vars[key], width=7).grid(row=r, column=c, padx=4, pady=2, sticky='w')
        bot_grid = ttk.Frame(sla); bot_grid.pack(fill='x', pady=(8,0))
        for c, (label, key) in enumerate([('Scan sec','scan_interval_seconds'),('Repeat notif min','repeat_notification_minutes'),('Auto fetch sec','auto_fetch_interval_seconds')]):
            ttk.Label(bot_grid, text=label).grid(row=0, column=c*2, padx=(4,2), pady=2, sticky='w')
            ttk.Spinbox(bot_grid, from_=1, to=10080, textvariable=self.sla_vars[key], width=7).grid(row=0, column=c*2+1, padx=(0,12), pady=2, sticky='w')
        ttk.Button(bot_grid,text='SAVE SLA SETTINGS',command=self.save_sla).grid(row=0, column=8, padx=(8,0), pady=2, sticky='w')
        tabs=ttk.Notebook(root); tabs.pack(fill='both',expand=True); f1=ttk.Frame(tabs,padding=6); f2=ttk.Frame(tabs,padding=6); tabs.add(f1,text='Incidents seen by bot'); tabs.add(f2,text='Actions / logs')
        self.inc_tree=ttk.Treeview(f1,columns=('incident','severity','status','owner','title','created','taking_charge_remaining','customer_notify_remaining','last_notified','last_update','active_since','age','workspace'),show='headings')
        for col,w in [('incident',90),('severity',100),('status',90),('owner',130),('title',360),('created',150),('taking_charge_remaining',160),('customer_notify_remaining',160),('last_notified',120),('last_update',150),('active_since',150),('age',80),('workspace',180)]: self.inc_tree.heading(col,text=col.replace('_',' ').title()); self.inc_tree.column(col,width=w,anchor='w')
        self.inc_tree.heading('taking_charge_remaining', text='Min To Taking Charge')
        self.inc_tree.heading('customer_notify_remaining', text='Min To Notify')
        self.inc_tree.heading('last_notified', text='Last Notified')
        self.inc_tree.pack(fill='both',expand=True)
        self.act_tree=ttk.Treeview(f2,columns=('ts','incident','action','result','details'),show='headings')
        for col,w in [('ts',170),('incident',90),('action',180),('result',120),('details',820)]: self.act_tree.heading(col,text=col.title()); self.act_tree.column(col,width=w,anchor='w')
        self.act_tree.pack(fill='both',expand=True)
    def launch_and_link(self, browser):
        ok=launch_browser_debug(browser)
        if not ok:
            return

        self.pending_auto_browser='Chrome' if browser=='chrome' else 'Edge'
        self.pending_auto_attempts=8
        self.status_var.set(f"{self.pending_auto_browser} avviato. Collegamento automatico in corso...")

        # Prova più volte: Chrome/Edge può impiegare alcuni secondi prima di esporre la porta CDP.
        for delay in (1500, 3000, 5000, 8000, 12000, 16000, 20000):
            self.after(delay, lambda:self.send('refresh_pages'))


    def on_close(self):
        try:
            self.worker.set_runtime_state(running_bot=False, paused=False, starting=False, auto_fetch_enabled=False, shutdown_requested=True)
        except Exception:
            pass
        try:
            self.send('shutdown')
        except Exception:
            pass

        # Give Playwright/Node a short window to close the pipe cleanly.
        def _finish_close():
            try:
                self.destroy()
            except Exception:
                pass
            try:
                os._exit(0)
            except Exception:
                pass

        self.after(1200, _finish_close)


    def start_bot(self, dry_run):
        self.worker.set_runtime_state(dry_run=bool(dry_run), running_bot=False, paused=False, starting=True, auto_fetch_enabled=False, last_scan_ts=0)
        self.status_var.set('Starting bot: initial fetch first...')
        self.send('start', dry_run=dry_run)

    def pause_bot(self):
        self.worker.set_runtime_state(paused=True, auto_fetch_enabled=False)
        self.status_var.set('Bot paused. Auto-fetch disabled.')
        self.send('pause')

    def resume_bot(self):
        self.worker.set_runtime_state(paused=False, running_bot=True, auto_fetch_enabled=False)
        self.status_var.set('Bot resumed.')
        self.send('resume')

    def stop_bot(self):
        self.worker.set_runtime_state(running_bot=False, paused=False, starting=False, auto_fetch_enabled=False)
        self.status_var.set('Bot stopped. Auto-fetch disabled.')
        self.send('stop')

    def save_sla(self): self.send('settings', values={k:v.get() for k,v in self.sla_vars.items()})
    def on_page_select(self,_=None):
        sel=self.pages_tree.selection()
        if not sel: return
        meta=self.page_items.get(sel[0]);
        if meta: self.send('select_page', page_id=meta['page_id']); self.status_var.set(f"Selected: {meta.get('browser')} - {meta.get('title','')[:70]}")
    def refresh_pages(self,pages):
        self.pages_tree.delete(*self.pages_tree.get_children()); self.page_items={}
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
        for inc in incs:
            age,sla=self.sla_view(inc); ref=inc.get('activated_at') or inc.get('first_seen_active') or ''
            self.inc_tree.insert('', 'end', values=(inc.get('incident_key',''),inc.get('severity',''),inc.get('status',''),inc.get('owner',''),inc.get('title',''),inc.get('created_time',''),format_remaining_minutes(sla_remaining_from_created(inc.get('created_time',''), inc.get('severity',''), RuntimeSettings(sla_critical_minutes=self.sla_vars['sla_critical_minutes'].get(), sla_high_minutes=self.sla_vars['sla_high_minutes'].get(), sla_medium_minutes=self.sla_vars['sla_medium_minutes'].get(), sla_low_minutes=self.sla_vars['sla_low_minutes'].get(), sla_informational_minutes=self.sla_vars['sla_informational_minutes'].get()))),format_remaining_minutes(customer_notification_remaining_from_created(inc.get('created_time',''), inc.get('severity',''), RuntimeSettings(notification_critical_minutes=self.sla_vars['notification_critical_minutes'].get(), notification_high_minutes=self.sla_vars['notification_high_minutes'].get(), notification_medium_minutes=self.sla_vars['notification_medium_minutes'].get(), notification_low_minutes=self.sla_vars['notification_low_minutes'].get(), notification_informational_minutes=self.sla_vars['notification_informational_minutes'].get()))),format_time_only(inc.get('last_sla_warning_at','')),inc.get('last_update_time',''),ref,age,inc.get('workspace_hint','')))
    def refresh_actions(self,acts):
        self.act_tree.delete(*self.act_tree.get_children())
        for a in acts: self.act_tree.insert('', 'end', values=(a.get('ts',''),a.get('incident_key',''),a.get('action',''),a.get('result',''),a.get('details','')))
    def show_sla_popup(self, title, message, severity='Medium'):
        """
        Persistent topmost popup: it closes only when the user clicks ACKNOWLEDGE.
        """
        try:
            popup = tk.Toplevel(self)
            popup.title(title)
            popup.attributes('-topmost', True)
            popup.lift()
            popup.focus_force()
            popup.geometry('520x220')

            frame = ttk.Frame(popup, padding=16)
            frame.pack(fill='both', expand=True)

            sev = (severity or '').lower()
            color = '#7f1d1d' if sev == 'critical' else '#b91c1c' if sev == 'high' else '#b45309' if sev == 'medium' else '#0369a1'
            ttk.Label(frame, text=title, font=('Segoe UI', 13, 'bold'), foreground=color).pack(anchor='w', pady=(0, 10))
            ttk.Label(frame, text=message, wraplength=480, justify='left').pack(anchor='w', fill='x', pady=(0, 14))

            ttk.Button(frame, text='ACKNOWLEDGE', command=popup.destroy).pack(anchor='e')

            try:
                popup.bell()
            except Exception:
                pass
        except Exception:
            messagebox.showwarning(title, message)

    def apply_settings(self,s):
        for k,v in (s or {}).items():
            if k in self.sla_vars:
                try: self.sla_vars[k].set(int(v))
                except Exception: pass
    def poll_worker(self):
        try:
            while True:
                msg=self.out_q.get_nowait(); kind=msg.get('kind')
                if kind=='pages':
                    self.refresh_pages(msg.get('pages',[]));
                    if not self.pending_auto_browser and not self.pages_tree.selection():
                        self.status_var.set('Browser connected: '+(', '.join(msg.get('connected',[])) or 'none')+'. Select the Sentinel tab.')
                elif kind=='status': self.status_var.set(msg.get('message','')); self.apply_settings(msg.get('settings',{}))
                elif kind=='scan_result': self.status_var.set(f"Scan done. Seen={msg.get('scanned')}, processed={msg.get('processed')}, SLA notifications={msg.get('warnings')}"); self.refresh_incidents(msg.get('incidents',[])); self.refresh_actions(msg.get('actions',[])); self.apply_settings(msg.get('settings',{}))
                elif kind=='sla_alert': self.show_sla_popup(msg.get('title','SLA warning'), msg.get('message',''), msg.get('severity','Medium'))
                elif kind=='error': self.status_var.set('ERROR: '+msg.get('message','')); self.refresh_actions(msg.get('actions',[])); messagebox.showwarning('Bot error', msg.get('message','Unknown error'))
        except queue.Empty: pass
        self.after(700,self.poll_worker)

if __name__=='__main__': BotApp().mainloop()
