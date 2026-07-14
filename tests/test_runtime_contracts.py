import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
sys.path.insert(0, str(APP_DIR))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load_module("sentinel_contract_core", APP_DIR / "app.py")
browser_runtime = load_module("sentinel_browser_runtime", APP_DIR / "browser_runtime.py")


class RuntimeContractsTest(unittest.TestCase):
    def test_assignment_workflow_is_enabled(self):
        self.assertTrue(core.ENABLE_ASSIGNMENT_WORKFLOW)

    def test_row_severity_is_authoritative(self):
        self.assertEqual(core.resolve_incident_severity("Medium", "High", "16552"), "Medium")

    def test_detail_severity_is_only_a_fallback(self):
        self.assertEqual(core.resolve_incident_severity("", "Low", "x"), "Low")

    def test_accessibility_owner_is_rejected(self):
        self.assertEqual(core.clean_owner_identity("Use 'Space' or 'Enter' key to enable edit mode"), "")

    def test_browser_args_preserve_background_and_profile(self):
        args = browser_runtime.build_browser_args(
            "chrome.exe",
            9222,
            APP_DIR / "browser_profiles" / "chrome_notifier_profile",
        )
        self.assertIn("--start-minimized", args)
        self.assertIn("--disable-renderer-backgrounding", args)
        self.assertIn("--disable-background-timer-throttling", args)
        self.assertTrue(any(arg.startswith("--user-data-dir=") for arg in args))


if __name__ == "__main__":
    unittest.main()
