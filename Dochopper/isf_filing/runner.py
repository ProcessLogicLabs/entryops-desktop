"""Playwright orchestrator that drives the e2open ISF web UI.

Lifecycle (single run, cancellable):
    1. UI thread instantiates ISFRunner(payload, field_map) and connects signals.
    2. UI calls .start() — runner's QThread launches, opens Chromium (headed,
       channel='chrome'), navigates to the ISF URL, then emits awaiting_login.
    3. Operator logs in manually in the Chromium window. UI calls
       .continue_after_login() — runner unblocks and clicks the "New ISF"
       action, then iterates the field map filling each field.
    4. On finish, runner emits awaiting_submit and idles. The runner does
       NOT click Submit — operator verifies the form and submits themselves.
    5. UI may call .cancel() or .finish() to close the browser; cancel can
       happen at any phase (login, fill, idle).

Design notes:
    - Playwright's sync API is incompatible with Qt's event loop unless we
      run it in a worker thread. We use QThread for that.
    - All inter-thread coordination uses QMutex + QWaitCondition; the UI
      thread never blocks.
    - Selector-miss errors are surfaced as status messages with the field
      name, so the operator knows where the form drift is and can update
      field_map.json without code changes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt5.QtCore import QMutex, QObject, QThread, QWaitCondition, pyqtSignal

from .field_map import FieldEntry, FieldMap


class _RunnerSignals(QObject):
    status_changed = pyqtSignal(str)
    awaiting_login = pyqtSignal()
    fill_started = pyqtSignal()
    awaiting_submit = pyqtSignal()
    finished = pyqtSignal(bool, str)
    field_filled = pyqtSignal(str)
    field_error = pyqtSignal(str, str)  # (field_name, error_message)


class ISFRunner(QThread):
    """Background thread that owns the Playwright lifecycle for one ISF."""

    def __init__(self, payload: Dict[str, Any], field_map: FieldMap, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.payload = payload
        self.field_map = field_map
        self.signals = _RunnerSignals()

        self._mutex = QMutex()
        self._login_done = QWaitCondition()
        self._finish_signal = QWaitCondition()
        self._login_acked = False
        self._user_finished = False
        self._cancelled = False

    # ---- public control surface (called from the UI thread) ----

    def continue_after_login(self) -> None:
        self._mutex.lock()
        self._login_acked = True
        self._login_done.wakeAll()
        self._mutex.unlock()

    def finish(self) -> None:
        self._mutex.lock()
        self._user_finished = True
        self._finish_signal.wakeAll()
        self._mutex.unlock()

    def cancel(self) -> None:
        self._mutex.lock()
        self._cancelled = True
        self._login_acked = True       # unblock login wait if still in it
        self._user_finished = True     # unblock final wait if in it
        self._login_done.wakeAll()
        self._finish_signal.wakeAll()
        self._mutex.unlock()

    # ---- worker thread entry ----

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as exc:
            self.signals.finished.emit(False, f"Runner crashed: {exc}")

    def _run_inner(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.signals.finished.emit(
                False,
                "Playwright is not installed. Run: pip install playwright && python -m playwright install chromium",
            )
            return

        self.signals.status_changed.emit("Launching browser...")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                channel=self._browser_channel(),
            )
            try:
                ctx = browser.new_context(accept_downloads=True)
                page = ctx.new_page()

                self.signals.status_changed.emit(f"Opening {self.field_map.isf_url}")
                page.goto(self.field_map.isf_url, wait_until="domcontentloaded")

                self.signals.awaiting_login.emit()
                self.signals.status_changed.emit("Log in to e2open in the browser, then click 'Continue'.")
                self._wait_for_login()
                if self._cancelled:
                    self.signals.finished.emit(False, "Cancelled before form fill.")
                    return

                if not self._click_action(page, "new_isf", required=False):
                    self.signals.status_changed.emit(
                        "No 'new_isf' action defined or selector empty — proceeding to current page."
                    )

                self.signals.fill_started.emit()
                ok_count, err_count = self._fill_all_fields(page)
                self.signals.status_changed.emit(
                    f"Form fill complete: {ok_count} field(s) populated, {err_count} error(s)."
                )

                self.signals.awaiting_submit.emit()
                self.signals.status_changed.emit(
                    "Verify the form in the browser, then click Submit. Click 'Done' here when finished."
                )
                self._wait_for_finish()

                self.signals.finished.emit(
                    True,
                    "Browser session closed. Confirm the ISF was accepted by e2open.",
                )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    # ---- helpers ----

    def _browser_channel(self) -> Optional[str]:
        # "chrome" = use the workstation's installed Google Chrome binary.
        # Playwright launches it with a fresh ephemeral profile, so the
        # operator's daily Chrome session (extensions, cookies, saved
        # logins) is untouched. This avoids the ~150 MB
        # `playwright install chromium` download since corp customs broker
        # workstations universally have Chrome via group policy. If a
        # workstation lacks Chrome, fall back to bundled Chromium (which
        # requires the install step).
        return "chrome"

    def _wait_for_login(self) -> None:
        self._mutex.lock()
        try:
            while not self._login_acked and not self._cancelled:
                self._login_done.wait(self._mutex)
        finally:
            self._mutex.unlock()

    def _wait_for_finish(self) -> None:
        self._mutex.lock()
        try:
            while not self._user_finished and not self._cancelled:
                self._finish_signal.wait(self._mutex)
        finally:
            self._mutex.unlock()

    def _click_action(self, page, action_name: str, required: bool) -> bool:
        action = self.field_map.actions.get(action_name)
        if not action or not action.selector:
            if required:
                self.signals.field_error.emit(action_name, "no selector configured")
            return False
        try:
            page.locator(action.selector).first.click(timeout=8000)
            return True
        except Exception as exc:
            msg = f"action '{action_name}' click failed: {exc}"
            self.signals.field_error.emit(action_name, msg)
            self.signals.status_changed.emit(msg)
            return False

    def _fill_all_fields(self, page) -> tuple[int, int]:
        ok = 0
        err = 0
        for key, entry in self.field_map.fields.items():
            if not entry.selector:
                if not entry.optional:
                    self.signals.field_error.emit(key, "no selector configured")
                continue
            value = self.payload.get(key, "")
            if entry.value_map and isinstance(value, str):
                value = entry.value_map.get(value, value)
            try:
                self._dispatch_fill(page, entry, value)
                self.signals.field_filled.emit(key)
                ok += 1
            except Exception as exc:
                err += 1
                self.signals.field_error.emit(key, str(exc))
                self.signals.status_changed.emit(f"  ! {key}: {exc}")
        return ok, err

    def _dispatch_fill(self, page, entry: FieldEntry, value: Any) -> None:
        if entry.type == "fill":
            page.locator(entry.selector).first.fill(str(value or ""), timeout=5000)
            return
        if entry.type == "select_option":
            page.locator(entry.selector).first.select_option(str(value or ""), timeout=5000)
            return
        if entry.type == "check":
            if value:
                page.locator(entry.selector).first.check(timeout=5000)
            return
        if entry.type == "uncheck":
            if not value:
                page.locator(entry.selector).first.uncheck(timeout=5000)
            return
        if entry.type == "click_then_fill":
            loc = page.locator(entry.selector).first
            loc.click(timeout=5000)
            loc.fill(str(value or ""), timeout=5000)
            return
        if entry.type == "list_fill":
            self._list_fill(page, entry, value)
            return
        raise ValueError(f"unsupported field type {entry.type!r}")

    def _list_fill(self, page, entry: FieldEntry, values: Any) -> None:
        if not isinstance(values, (list, tuple)):
            return
        tmpl = entry.row_template or {}
        add_btn = tmpl.get("add_row_button", "")
        code_input = tmpl.get("code_input", "")
        if not code_input:
            raise ValueError("list_fill requires row_template.code_input")
        for i, v in enumerate(values):
            if not v:
                continue
            if i > 0 and add_btn:
                page.locator(add_btn).first.click(timeout=5000)
            page.locator(code_input).nth(i).fill(str(v), timeout=5000)
