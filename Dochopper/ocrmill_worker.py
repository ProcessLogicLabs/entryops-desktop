"""
OCRMill Background Worker for DocHopper
Handles folder monitoring and background PDF processing.
"""

import time
import os
import sqlite3
import zipfile
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition

import pandas as pd


# Suffixes the folder-monitor + parallel-folder workers will treat as
# processable. Mirrors PDFDropZone.INVOICE_EXTS in dochopper.py.
_INVOICE_EXTS = ('.pdf', '.xlsx', '.xls')


def _read_last_output_profile(db_path) -> str:
    """Read the user's last-selected export profile from app_config.

    Returns empty string if the table doesn't exist or no profile is set —
    callers treat that as "use the default column ordering".
    """
    if db_path is None:
        return ""
    try:
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("SELECT value FROM app_config WHERE key = 'last_output_profile'")
        row = c.fetchone()
        conn.close()
        return (row[0] or "") if row else ""
    except sqlite3.Error:
        return ""


def _export_with_profile(processor, items, output_folder, pdf_name, log=None):
    """Run process_and_export with the user's saved profile, with safe defaults.

    Used by the headless folder-monitor + ParallelFolderWorker paths — there's
    no UI to prompt for net weight or to surface missing parts, so we:
      - Default net_weight to 0 (and log a one-line warning per file)
      - Pass override_mid='' so the BaseTemplate auto-MID logic stays in charge
      - Fall back to save_to_csv if process_and_export raises

    Returns the list of created XLSX paths on success, or the list of CSV
    paths from the fallback. Empty list if both paths produce nothing.
    """
    db_path = getattr(getattr(processor, 'parts_db', None), 'db_path', None)
    profile_name = _read_last_output_profile(db_path)

    if log:
        if profile_name:
            log(f"  Using export profile: {profile_name}")
        else:
            log("  No export profile saved — falling back to default column order")

    try:
        result = processor.process_and_export(
            items,
            output_folder,
            pdf_name,
            net_weight=0.0,           # silent default — user can edit XLSX afterwards
            profile_name=profile_name,
            db_path=db_path,
            override_mid='',          # rely on template + BaseTemplate auto-MID
        )
        # Both 3-tuple (legacy) and 4-tuple (current) signatures supported.
        xlsx_paths = result[0] if result else []
        if xlsx_paths:
            return list(xlsx_paths)
    except Exception as exc:
        if log:
            log(f"  process_and_export failed ({exc}); falling back to raw CSV")

    # Fallback path — preserves legacy behavior so a profile/enrichment failure
    # doesn't leave the operator with nothing.
    try:
        return processor.save_to_csv(items, output_folder, pdf_name=pdf_name) or []
    except Exception as exc:
        if log:
            log(f"  save_to_csv fallback also failed: {exc}")
        return []


def _expand_zip_archive(zip_path: Path, log=None) -> List[Path]:
    """Extract invoice files (PDFs, XLSX, XLS) from a ZIP archive.

    Files are extracted next to the zip (in the same directory), so the
    folder-monitor pass picks them up on the next iteration. Returns the
    list of extracted file paths. Conflicts get an auto-numbered suffix
    so a re-run that hits the same zip doesn't clobber prior output.
    """
    extracted: List[Path] = []
    if not zip_path.exists() or zip_path.suffix.lower() != '.zip':
        return extracted

    target_dir = zip_path.parent
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for entry in zf.infolist():
                if entry.is_dir():
                    continue
                inner_name = Path(entry.filename).name  # strip nested dirs
                if not inner_name:
                    continue
                if Path(inner_name).suffix.lower() not in _INVOICE_EXTS:
                    continue

                dest = target_dir / inner_name
                # Avoid overwriting existing files — append _1, _2, ...
                stem = dest.stem
                ext = dest.suffix
                counter = 1
                while dest.exists():
                    dest = target_dir / f"{stem}_{counter}{ext}"
                    counter += 1

                with zf.open(entry, 'r') as src, open(dest, 'wb') as out:
                    out.write(src.read())
                extracted.append(dest)
                if log:
                    log(f"  Extracted {entry.filename} -> {dest.name}")
    except (zipfile.BadZipFile, OSError) as exc:
        if log:
            log(f"  Failed to extract {zip_path.name}: {exc}")
    return extracted


class OCRMillWorker(QThread):
    """
    Background worker for OCRMill folder monitoring and PDF processing.

    Signals:
        log_message: Emitted with log messages for display
        processing_started: Emitted when processing begins
        processing_finished: Emitted when processing completes with item count
        pdf_processed: Emitted after each PDF is processed with (filename, success, item_count)
        error: Emitted on errors with error message
        items_extracted: Emitted with extracted items for UI display
    """

    log_message = pyqtSignal(str)
    processing_started = pyqtSignal()
    processing_finished = pyqtSignal(int)  # total items processed
    pdf_processed = pyqtSignal(str, bool, int)  # filename, success, item_count
    error = pyqtSignal(str)
    items_extracted = pyqtSignal(list)  # list of item dicts

    def __init__(self, processor, parent=None):
        """
        Initialize the worker.

        Args:
            processor: ProcessorEngine instance
            parent: Parent QObject
        """
        super().__init__(parent)
        self.processor = processor
        self._running = False
        self._monitoring = False
        self._poll_interval = 60  # seconds
        self._mutex = QMutex()

        # Connect processor logging to our signal
        self.processor.log_callback = self._log

    def _log(self, message: str):
        """Log callback that emits signal."""
        self.log_message.emit(message)

    def set_poll_interval(self, seconds: int):
        """Set the polling interval for folder monitoring."""
        self._mutex.lock()
        self._poll_interval = max(10, min(300, seconds))  # clamp to 10-300 seconds
        self._mutex.unlock()

    def start_monitoring(self):
        """Start folder monitoring mode."""
        self._mutex.lock()
        self._monitoring = True
        self._mutex.unlock()
        if not self.isRunning():
            self.start()

    def stop_monitoring(self):
        """Stop folder monitoring mode."""
        self._mutex.lock()
        self._monitoring = False
        self._mutex.unlock()

    def is_monitoring(self) -> bool:
        """Check if currently monitoring."""
        self._mutex.lock()
        result = self._monitoring
        self._mutex.unlock()
        return result

    def stop(self):
        """Stop the worker thread."""
        self._mutex.lock()
        self._running = False
        self._monitoring = False
        self._mutex.unlock()
        self.wait(5000)  # Wait up to 5 seconds for thread to finish

    def run(self):
        """Main thread loop for folder monitoring."""
        self._running = True

        while self._running:
            self._mutex.lock()
            monitoring = self._monitoring
            poll_interval = self._poll_interval
            self._mutex.unlock()

            if monitoring:
                try:
                    self._process_folder()
                except Exception as e:
                    self.error.emit(f"Monitoring error: {str(e)}")

                # Sleep in small increments to allow for stopping
                for _ in range(poll_interval):
                    if not self._running or not self._monitoring:
                        break
                    time.sleep(1)
            else:
                # Not monitoring, just sleep briefly
                time.sleep(1)

    def _process_folder(self):
        """Process PDFs in the input folder."""
        input_folder = Path(self.processor.config.input_folder)
        output_folder = Path(self.processor.config.output_folder)

        if not input_folder.exists():
            return

        # Expand any .zip archives in place so the next loop picks them up
        # alongside loose PDFs/XLSX. Move processed zips out of the watch
        # directory so we don't re-extract them every poll cycle.
        processed_zip_dir = input_folder / "Processed_Zips"
        for zip_path in list(input_folder.glob("*.zip")):
            extracted = _expand_zip_archive(zip_path, log=self._log)
            if extracted:
                processed_zip_dir.mkdir(parents=True, exist_ok=True)
                try:
                    zip_path.rename(processed_zip_dir / zip_path.name)
                except OSError:
                    pass  # leave it; next pass will retry

        # Pick up loose PDFs as well as XLSX/XLS commercial invoices that
        # may have come from a zip extraction or been dropped directly.
        pdf_files: List[Path] = []
        for pat in ('*.pdf', '*.xlsx', '*.xls'):
            pdf_files.extend(input_folder.glob(pat))
        if not pdf_files:
            return

        self.processing_started.emit()
        total_items = 0

        for pdf_path in pdf_files:
            if not self._running or not self._monitoring:
                break

            try:
                items = self.processor.process_pdf(pdf_path)
                if items:
                    # Route through the export profile (XLSX) — falls back to
                    # raw save_to_csv (CSV) if enrichment/export fails.
                    _export_with_profile(
                        self.processor, items, output_folder,
                        pdf_path.name, log=self._log,
                    )
                    processed_folder = input_folder / "Processed"
                    self.processor.move_to_processed(pdf_path, processed_folder)
                    self.pdf_processed.emit(pdf_path.name, True, len(items))
                    self.items_extracted.emit(items)
                    total_items += len(items)
                else:
                    failed_folder = input_folder / "Failed"
                    self.processor.move_to_failed(pdf_path, failed_folder, "No items extracted")
                    self.pdf_processed.emit(pdf_path.name, False, 0)

            except Exception as e:
                self.error.emit(f"Error processing {pdf_path.name}: {str(e)}")
                failed_folder = input_folder / "Failed"
                self.processor.move_to_failed(pdf_path, failed_folder, str(e)[:50])
                self.pdf_processed.emit(pdf_path.name, False, 0)

        self.processing_finished.emit(total_items)

    def process_single_file(self, pdf_path: Path, output_folder: Path = None) -> List[Dict]:
        """
        Process a single PDF file (not in background thread).

        This method should be called from a separate worker thread
        or using processEvents() for responsiveness.

        Args:
            pdf_path: Path to PDF file
            output_folder: Output folder path

        Returns:
            List of extracted items
        """
        self.processing_started.emit()

        try:
            items = self.processor.process_pdf(pdf_path)
            if items:
                output = output_folder or Path(self.processor.config.output_folder)
                self.processor.save_to_csv(items, output, pdf_name=pdf_path.name)
                self.pdf_processed.emit(pdf_path.name, True, len(items))
                self.items_extracted.emit(items)
            else:
                self.pdf_processed.emit(pdf_path.name, False, 0)

            self.processing_finished.emit(len(items) if items else 0)
            return items or []

        except Exception as e:
            self.error.emit(f"Error processing {pdf_path.name}: {str(e)}")
            self.processing_finished.emit(0)
            return []


class SingleFileWorker(QThread):
    """
    Worker for processing a single PDF file without blocking the UI.
    """

    log_message = pyqtSignal(str)
    finished = pyqtSignal(list)  # list of extracted items
    error = pyqtSignal(str)

    def __init__(self, processor, pdf_path: Path, output_folder: Path = None, parent=None):
        super().__init__(parent)
        self.processor = processor
        self.pdf_path = pdf_path
        self.output_folder = output_folder
        self._original_callback = processor.log_callback

    def run(self):
        """Process the PDF file."""
        # Temporarily redirect logging
        self.processor.log_callback = lambda msg: self.log_message.emit(msg)

        try:
            items = self.processor.process_pdf(self.pdf_path)
            if items:
                output = self.output_folder or Path(self.processor.config.output_folder)
                self.processor.save_to_csv(items, output, pdf_name=self.pdf_path.name)
            self.finished.emit(items or [])

        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit([])

        finally:
            # Restore original callback
            self.processor.log_callback = self._original_callback


class MultiFileWorker(QThread):
    """
    Worker for processing multiple PDF files in parallel using ThreadPoolExecutor.

    This significantly speeds up processing when multiple PDFs are dropped at once.
    """

    log_message = pyqtSignal(str)
    file_started = pyqtSignal(str)  # filename
    file_finished = pyqtSignal(str, bool, int)  # filename, success, item_count
    all_finished = pyqtSignal(list)  # all items combined
    progress = pyqtSignal(int, int)  # completed, total
    error = pyqtSignal(str)

    def __init__(self, processor, file_paths: List[Path], output_folder: Path = None,
                 max_workers: int = None, parent=None):
        """
        Initialize the multi-file worker.

        Args:
            processor: ProcessorEngine instance
            file_paths: List of PDF file paths to process
            output_folder: Output folder for CSV files
            max_workers: Maximum parallel workers (default: CPU count or 4, whichever is smaller)
            parent: Parent QObject
        """
        super().__init__(parent)
        self.processor = processor
        self.file_paths = [Path(p) for p in file_paths]
        self.output_folder = output_folder or Path(processor.config.output_folder)
        # Limit workers to prevent overwhelming the system
        # PDF processing is I/O and CPU intensive, so don't use too many threads
        self.max_workers = max_workers or min(os.cpu_count() or 4, 4)
        self._cancelled = False
        self._mutex = QMutex()

    def cancel(self):
        """Cancel the processing."""
        self._mutex.lock()
        self._cancelled = True
        self._mutex.unlock()

    def is_cancelled(self) -> bool:
        """Check if processing was cancelled."""
        self._mutex.lock()
        result = self._cancelled
        self._mutex.unlock()
        return result

    def _process_single_pdf(self, pdf_path: Path) -> tuple:
        """
        Process a single PDF file (called from thread pool).

        Args:
            pdf_path: Path to PDF file

        Returns:
            Tuple of (pdf_path, items, error_message)
        """
        if self.is_cancelled():
            return (pdf_path, [], "Cancelled")

        try:
            # Note: We create a simple log collector instead of emitting signals
            # because signals can't be emitted from non-Qt threads safely
            items = self.processor.process_pdf(pdf_path)
            if items:
                self.processor.save_to_csv(items, self.output_folder, pdf_name=pdf_path.name)
            return (pdf_path, items or [], None)
        except Exception as e:
            return (pdf_path, [], str(e))

    def run(self):
        """Process all PDF files in parallel."""
        total = len(self.file_paths)
        if total == 0:
            self.all_finished.emit([])
            return

        self.log_message.emit(f"Starting parallel processing of {total} PDF(s) with {self.max_workers} workers...")

        all_items = []
        completed = 0

        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_path = {
                executor.submit(self._process_single_pdf, path): path
                for path in self.file_paths
            }

            # Process results as they complete
            for future in as_completed(future_to_path):
                if self.is_cancelled():
                    self.log_message.emit("Processing cancelled")
                    break

                pdf_path = future_to_path[future]

                try:
                    path, items, error = future.result()

                    if error:
                        self.log_message.emit(f"  ✗ {path.name}: {error}")
                        self.file_finished.emit(path.name, False, 0)
                    elif items:
                        self.log_message.emit(f"  ✓ {path.name}: {len(items)} items")
                        self.file_finished.emit(path.name, True, len(items))
                        all_items.extend(items)
                    else:
                        self.log_message.emit(f"  - {path.name}: No items extracted")
                        self.file_finished.emit(path.name, False, 0)

                except Exception as e:
                    self.log_message.emit(f"  ✗ {pdf_path.name}: Unexpected error - {e}")
                    self.file_finished.emit(pdf_path.name, False, 0)

                completed += 1
                self.progress.emit(completed, total)

        if not self.is_cancelled():
            self.log_message.emit(f"Completed: {len(all_items)} total items from {completed} file(s)")

        self.all_finished.emit(all_items)


class ParallelFolderWorker(QThread):
    """
    Worker for processing all PDFs in a folder in parallel.
    """

    log_message = pyqtSignal(str)
    file_finished = pyqtSignal(str, bool, int)  # filename, success, item_count
    all_finished = pyqtSignal(int)  # total items processed
    progress = pyqtSignal(int, int)  # completed, total
    error = pyqtSignal(str)

    def __init__(self, processor, input_folder: Path, output_folder: Path = None,
                 max_workers: int = None, parent=None):
        super().__init__(parent)
        self.processor = processor
        self.input_folder = Path(input_folder)
        self.output_folder = Path(output_folder) if output_folder else Path(processor.config.output_folder)
        self.max_workers = max_workers or min(os.cpu_count() or 4, 4)
        self._cancelled = False
        self._mutex = QMutex()

    def cancel(self):
        """Cancel the processing."""
        self._mutex.lock()
        self._cancelled = True
        self._mutex.unlock()

    def is_cancelled(self) -> bool:
        self._mutex.lock()
        result = self._cancelled
        self._mutex.unlock()
        return result

    def _process_single_pdf(self, pdf_path: Path) -> tuple:
        """Process a single PDF (called from thread pool)."""
        if self.is_cancelled():
            return (pdf_path, [], "Cancelled")

        try:
            items = self.processor.process_pdf(pdf_path)
            if items:
                # Route through the export profile so the output mirrors what
                # the drop-zone Direct XLSX Export path produces. Headless
                # defaults: net_weight=0, no MID override, fall back to
                # save_to_csv if enrichment/export blows up.
                _export_with_profile(
                    self.processor, items, self.output_folder,
                    pdf_path.name, log=self.log_message.emit,
                )
            return (pdf_path, items or [], None)
        except Exception as e:
            return (pdf_path, [], str(e))

    def run(self):
        """Process all PDFs in the folder in parallel."""
        # Create folders
        self.input_folder.mkdir(parents=True, exist_ok=True)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        processed_folder = self.input_folder / "Processed"
        failed_folder = self.input_folder / "Failed"

        # Expand any .zip archives in place. Move processed zips into
        # Processed_Zips/ so we don't re-extract on the next run.
        processed_zip_dir = self.input_folder / "Processed_Zips"
        for zip_path in list(self.input_folder.glob("*.zip")):
            extracted = _expand_zip_archive(zip_path, log=self.log_message.emit)
            if extracted:
                processed_zip_dir.mkdir(parents=True, exist_ok=True)
                try:
                    zip_path.rename(processed_zip_dir / zip_path.name)
                except OSError:
                    pass

        # Find loose invoice files (PDF, XLSX, XLS) — including ones we
        # just extracted above.
        pdf_files: List[Path] = []
        for pat in ('*.pdf', '*.xlsx', '*.xls'):
            pdf_files.extend(self.input_folder.glob(pat))
        total = len(pdf_files)

        if total == 0:
            self.log_message.emit("No invoice files found in input folder")
            self.all_finished.emit(0)
            return

        self.log_message.emit(f"Found {total} invoice file(s), processing with {self.max_workers} workers...")

        total_items = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_path = {
                executor.submit(self._process_single_pdf, path): path
                for path in pdf_files
            }

            for future in as_completed(future_to_path):
                if self.is_cancelled():
                    self.log_message.emit("Processing cancelled")
                    break

                pdf_path = future_to_path[future]

                try:
                    path, items, error = future.result()

                    if error:
                        self.log_message.emit(f"  ✗ {path.name}: {error}")
                        self.file_finished.emit(path.name, False, 0)
                        self.processor.move_to_failed(path, failed_folder, error[:50])
                    elif items:
                        self.log_message.emit(f"  ✓ {path.name}: {len(items)} items")
                        self.file_finished.emit(path.name, True, len(items))
                        self.processor.move_to_processed(path, processed_folder)
                        total_items += len(items)
                    else:
                        self.log_message.emit(f"  - {path.name}: No items extracted")
                        self.file_finished.emit(path.name, False, 0)
                        self.processor.move_to_failed(path, failed_folder, "No items extracted")

                except Exception as e:
                    self.log_message.emit(f"  ✗ {pdf_path.name}: {e}")
                    self.file_finished.emit(pdf_path.name, False, 0)
                    try:
                        self.processor.move_to_failed(pdf_path, failed_folder, str(e)[:50])
                    except:
                        pass

                completed += 1
                self.progress.emit(completed, total)

        self.log_message.emit(f"Folder processing complete: {total_items} items from {completed} file(s)")
        self.all_finished.emit(total_items)


class DirectExportWorker(QThread):
    """
    Worker for processing PDF(s) with full enrichment and direct XLSX export.
    Handles single or multiple files, resolves net weight, and applies output profile.
    """

    log_message = pyqtSignal(str)
    file_started = pyqtSignal(str)  # filename
    file_finished = pyqtSignal(str, bool, int)  # filename, success, item_count
    export_complete = pyqtSignal(list, object, object)  # (xlsx_paths, preview_df, enriched_df)
    weight_needed = pyqtSignal(str)  # pdf_name — emitted when net weight not found in PDF
    parts_needed = pyqtSignal(list)  # list of missing part dicts [{part_number, description}, ...]
    mid_needed = pyqtSignal(list)  # list of pdf_names needing a MID — emitted when auto-MID can't resolve
    items_extracted = pyqtSignal(str, list)  # (pdf_name, items) — emitted after extraction
    validation_summary = pyqtSignal(dict)  # enrichment stats summary
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # completed, total

    def __init__(self, processor, file_paths: List[Path], output_folder: Path,
                 db_path: Path, profile_name: str = '', net_weight: float = None,
                 override_mid: str = '', cached_items: dict = None,
                 skip_missing_parts_dialog: bool = False, parent=None):
        """
        Args:
            processor: ProcessorEngine instance
            file_paths: PDF files to process
            output_folder: Where to save XLSX output
            db_path: Path to DocHopper database
            profile_name: Output profile name (empty for default)
            net_weight: Net weight in kg (None = auto-resolve from PDF)
            override_mid: If set, force this MID on every row
            cached_items: Optional dict {pdf_name: items} to skip extraction (for reprocess)
            skip_missing_parts_dialog: When True, the worker exports rows whose
                part_number is missing/incomplete in parts_master without
                blocking on the Add/Update Parts dialog. The rows are still
                flagged via the ReviewFlag column so the operator can find
                them in the XLSX afterward.
        """
        super().__init__(parent)
        self.processor = processor
        self.file_paths = [Path(p) for p in file_paths]
        self.output_folder = Path(output_folder)
        self.db_path = Path(db_path)
        self.profile_name = profile_name
        self.net_weight = net_weight
        self.override_mid = override_mid
        self.cached_items = cached_items or {}
        self.skip_missing_parts_dialog = bool(skip_missing_parts_dialog)
        self._original_callback = processor.log_callback
        self._weight_warnings = []  # PDFs where weight defaulted to 0
        # Weight input synchronization (kept for backward compat)
        self._weight_mutex = QMutex()
        self._weight_condition = QWaitCondition()
        self._user_weight = None
        # Parts input synchronization
        self._parts_mutex = QMutex()
        self._parts_condition = QWaitCondition()
        self._parts_resolved = False
        # Fallback-MID prompt synchronization (used only when auto-MID can't
        # resolve from the document — see _resolve_missing_mids in run()).
        self._mid_mutex = QMutex()
        self._mid_condition = QWaitCondition()
        self._mid_resolved = False
        self._user_mid = ""

    def provide_weight(self, weight: float):
        """Called from UI thread to provide user-entered net weight and resume processing."""
        self._weight_mutex.lock()
        self._user_weight = weight
        self._weight_condition.wakeAll()
        self._weight_mutex.unlock()

    def _wait_for_weight(self) -> float:
        """Block worker thread until UI provides weight. Returns weight or 0 if cancelled."""
        self._weight_mutex.lock()
        self._user_weight = None
        self._weight_mutex.unlock()

        self._weight_mutex.lock()
        # Wait up to 5 minutes for user input
        if self._user_weight is None:
            self._weight_condition.wait(self._weight_mutex, 300000)
        weight = self._user_weight or 0.0
        self._weight_mutex.unlock()
        return weight

    def provide_parts_done(self):
        """Called from UI thread when user has finished adding missing parts to DB."""
        self._parts_mutex.lock()
        self._parts_resolved = True
        self._parts_condition.wakeAll()
        self._parts_mutex.unlock()

    def _wait_for_parts(self):
        """Block worker thread until UI signals that missing parts have been handled."""
        self._parts_mutex.lock()
        self._parts_resolved = False
        self._parts_mutex.unlock()

        self._parts_mutex.lock()
        if not self._parts_resolved:
            self._parts_condition.wait(self._parts_mutex, 600000)  # 10 min timeout
        self._parts_mutex.unlock()

    # -- Fallback MID prompt --------------------------------------------------
    # The drop-zone no longer requires the user to pick a MID upfront — the
    # template's auto-MID logic (BaseTemplate.lookup_mid_by_name) resolves it
    # from the supplier name in 99% of cases. Only when extraction can't
    # determine a MID for one or more files do we surface the prompt below.

    def provide_fallback_mid(self, mid: str):
        """Called from UI thread to provide a fallback MID for files that
        couldn't auto-resolve one. Empty string means user cancelled."""
        self._mid_mutex.lock()
        self._user_mid = mid or ""
        self._mid_resolved = True
        self._mid_condition.wakeAll()
        self._mid_mutex.unlock()

    def _wait_for_mid(self) -> str:
        """Block until UI calls provide_fallback_mid. Returns chosen MID or ''."""
        self._mid_mutex.lock()
        if not self._mid_resolved:
            self._mid_condition.wait(self._mid_mutex, 300000)  # 5 min timeout
        mid = self._user_mid or ""
        self._mid_mutex.unlock()
        return mid

    def _check_missing_parts(self, items: List[Dict]) -> List[Dict]:
        """Check which extracted part numbers are missing or incomplete in parts_master.

        A part is flagged if it:
        - Does not exist in parts_master at all, OR
        - Exists but is missing hts_code, qty_unit, or client_code

        Returns list of dicts with part data pre-populated from DB (for incomplete)
        or from extraction (for missing).
        """
        part_numbers = list(set(
            item.get('part_number', '').strip().upper()
            for item in items if item.get('part_number', '').strip()
        ))
        if not part_numbers:
            return []

        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            placeholders = ','.join('?' * len(part_numbers))

            # Fetch existing parts with completeness data
            c.execute(
                f"SELECT UPPER(TRIM(part_number)), hts_code, qty_unit, client_code, "
                f"mid, country_origin, country_of_melt, country_of_cast, country_of_smelt, "
                f"steel_pct, aluminum_pct, copper_pct, wood_pct, auto_pct, non_steel_pct, "
                f"description "
                f"FROM parts_master WHERE UPPER(TRIM(part_number)) IN ({placeholders})",
                part_numbers
            )
            existing = {}
            for row in c.fetchall():
                existing[row[0]] = {
                    'hts_code': (row[1] or '').strip(),
                    'qty_unit': (row[2] or '').strip(),
                    'client_code': (row[3] or '').strip(),
                    'mid': (row[4] or '').strip(),
                    'country_origin': (row[5] or '').strip(),
                    'country_of_melt': (row[6] or '').strip(),
                    'country_of_cast': (row[7] or '').strip(),
                    'country_of_smelt': (row[8] or '').strip(),
                    'steel_pct': row[9] or 0, 'aluminum_pct': row[10] or 0,
                    'copper_pct': row[11] or 0, 'wood_pct': row[12] or 0,
                    'auto_pct': row[13] or 0, 'non_steel_pct': row[14] or 0,
                    'description': (row[15] or '').strip(),
                }
            # Load part-alias mappings keyed by canonical_part_number (uppercase)
            aliases = {}
            try:
                c.execute("SELECT UPPER(TRIM(canonical_part_number)), hts_code, country_origin, default_client_code "
                          "FROM part_aliases WHERE canonical_part_number IS NOT NULL")
                for row in c.fetchall():
                    if row[0] and row[1]:
                        aliases[row[0]] = {
                            'hts_code': (row[1] or '').strip(),
                            'country_origin': (row[2] or '').strip(),
                            'default_client_code': (row[3] or '').strip(),
                        }
            except Exception:
                pass  # Table may not exist (or is still on the pre-migration schema)

            # Auto-fix incomplete parts from alias mappings
            auto_fixed = 0
            for pn, db in existing.items():
                incomplete = not db['hts_code'] or not db['qty_unit'] or not db['client_code']
                if incomplete and pn in aliases:
                    alias = aliases[pn]
                    updates = {}
                    if not db['hts_code'] and alias['hts_code']:
                        updates['hts_code'] = alias['hts_code']
                    if not db['country_origin'] and alias['country_origin']:
                        updates['country_origin'] = alias['country_origin']
                    if not db['client_code'] and alias['default_client_code']:
                        updates['client_code'] = alias['default_client_code']
                    # Look up qty_unit from hts_units if we have an HTS code
                    hts_for_lookup = updates.get('hts_code') or db['hts_code']
                    if not db['qty_unit'] and hts_for_lookup:
                        c.execute("SELECT qty_unit FROM hts_units WHERE hts_code = ?", (hts_for_lookup,))
                        hts_row = c.fetchone()
                        if hts_row and hts_row[0]:
                            updates['qty_unit'] = hts_row[0]

                    if updates:
                        set_clause = ', '.join(f"{k} = ?" for k in updates)
                        c.execute(f"UPDATE parts_master SET {set_clause} "
                                  f"WHERE UPPER(TRIM(part_number)) = ?",
                                  list(updates.values()) + [pn])
                        # Update local dict so it passes completeness check below
                        db.update(updates)
                        auto_fixed += 1

            if auto_fixed:
                conn.commit()
                self.log_message.emit(f"  Auto-fixed {auto_fixed} part(s) from part-alias mappings")

            conn.close()

            missing = []
            seen = set()
            for item in items:
                pn = item.get('part_number', '').strip().upper()
                if not pn or pn in seen:
                    continue

                if pn not in existing:
                    # Not in DB at all — check if an alias row has data to auto-create
                    if pn in aliases:
                        alias = aliases[pn]
                        qty_unit = ''
                        if alias['hts_code']:
                            try:
                                conn2 = sqlite3.connect(str(self.db_path))
                                c2 = conn2.cursor()
                                c2.execute("SELECT qty_unit FROM hts_units WHERE hts_code = ?", (alias['hts_code'],))
                                hts_row = c2.fetchone()
                                if hts_row and hts_row[0]:
                                    qty_unit = hts_row[0]
                                c2.execute("""INSERT INTO parts_master
                                            (part_number, hts_code, qty_unit, country_origin, client_code)
                                            VALUES (?, ?, ?, ?, ?)""",
                                         (pn, alias['hts_code'], qty_unit, alias['country_origin'], alias['default_client_code']))
                                conn2.commit()
                                conn2.close()
                                self.log_message.emit(f"  Auto-created {pn} from part alias (HTS: {alias['hts_code']})")
                                seen.add(pn)
                                continue  # Skip adding to missing list
                            except Exception as e:
                                self.log_message.emit(f"  Failed to auto-create {pn}: {e}")

                    seen.add(pn)
                    missing.append({
                        'part_number': pn,
                        'description': item.get('description', ''),
                        'quantity': item.get('quantity', ''),
                        'total_price': item.get('total_price', ''),
                        'hts_code': item.get('hts_code', ''),
                        'mid': item.get('mid', ''),
                        'country': item.get('country', ''),
                        '_reason': 'Not in database',
                    })
                else:
                    # In DB — check if still incomplete after auto-fix
                    db = existing[pn]
                    incomplete_fields = []
                    if not db['hts_code']:
                        incomplete_fields.append('hts_code')
                    if not db['qty_unit']:
                        incomplete_fields.append('qty_unit')
                    if not db['client_code']:
                        incomplete_fields.append('client_code')

                    if incomplete_fields:
                        seen.add(pn)
                        entry = dict(db)
                        entry['part_number'] = pn
                        entry['_reason'] = f"Missing: {', '.join(incomplete_fields)}"
                        if not entry.get('description'):
                            entry['description'] = item.get('description', '')
                        if not entry.get('hts_code'):
                            entry['hts_code'] = item.get('hts_code', '')
                        if not entry.get('mid'):
                            entry['mid'] = item.get('mid', '')
                        missing.append(entry)

            if missing:
                not_in_db = sum(1 for m in missing if m.get('_reason', '').startswith('Not'))
                incomplete = len(missing) - not_in_db
                if not_in_db:
                    self.log_message.emit(f"  {not_in_db} part(s) not in database")
                if incomplete:
                    self.log_message.emit(f"  {incomplete} part(s) incomplete in database")

            return missing
        except Exception as e:
            self.log_message.emit(f"  Error checking parts_master: {e}")
            return []

    def _extract_single(self, pdf_path: Path):
        """Extract items from a single PDF (called from thread pool or main thread).
        Returns (pdf_path, items, error_message)."""
        try:
            items = self.processor.process_pdf(pdf_path)
            return (pdf_path, items or [], None)
        except Exception as e:
            return (pdf_path, [], str(e))

    def run(self):
        """Process all PDF files with parallel extraction, batch missing parts,
        enrichment, and export."""
        self.processor.log_callback = lambda msg: self.log_message.emit(msg)

        try:
            total = len(self.file_paths)
            all_xlsx_paths = []
            last_preview_df = pd.DataFrame()
            last_enriched_df = pd.DataFrame()
            all_stats = {}  # Accumulate enrichment stats across files

            # ── Phase 1: Parallel PDF extraction ──
            extraction_results = {}  # {pdf_path: items}
            extraction_errors = {}   # {pdf_path: error_msg}

            # Separate cached vs uncached files
            uncached_paths = []
            for pdf_path in self.file_paths:
                if pdf_path.name in self.cached_items:
                    extraction_results[pdf_path] = self.cached_items[pdf_path.name]
                    self.log_message.emit(f"  Using cached extraction for {pdf_path.name} ({len(extraction_results[pdf_path])} items)")
                else:
                    uncached_paths.append(pdf_path)

            if uncached_paths:
                if len(uncached_paths) == 1:
                    # Single file — extract directly (no thread pool overhead)
                    pdf_path = uncached_paths[0]
                    self.file_started.emit(pdf_path.name)
                    path, items, err = self._extract_single(pdf_path)
                    if err:
                        extraction_errors[path] = err
                    else:
                        extraction_results[path] = items
                        self.items_extracted.emit(path.name, items)
                else:
                    # Multiple files — parallel extraction
                    max_workers = min(os.cpu_count() or 4, 4, len(uncached_paths))
                    self.log_message.emit(f"Extracting {len(uncached_paths)} PDF(s) in parallel ({max_workers} workers)...")
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        future_to_path = {
                            executor.submit(self._extract_single, p): p
                            for p in uncached_paths
                        }
                        for future in as_completed(future_to_path):
                            path, items, err = future.result()
                            self.file_started.emit(path.name)
                            if err:
                                extraction_errors[path] = err
                                self.log_message.emit(f"  Extraction failed: {path.name}: {err}")
                            else:
                                extraction_results[path] = items
                                self.items_extracted.emit(path.name, items)
                                if items:
                                    self.log_message.emit(f"  Extracted {len(items)} items from {path.name}")
                                else:
                                    self.log_message.emit(f"  No items extracted from {path.name}")

            # ── Phase 1.4: Fallback-MID prompt for files that auto-MID couldn't resolve ──
            # Auto-MID via BaseTemplate.lookup_mid_by_name handles 99% of cases.
            # For the remainder (template can't extract supplier name, supplier
            # not in mid_table, etc.) we surface a single prompt listing the
            # affected files. The user picks one MID; it's only applied to
            # items that are still missing one — items that auto-MID resolved
            # are preserved as-is. The combo's pre-set value (if any) takes
            # priority over the prompt — that's the explicit-override path.
            if not self.override_mid:
                files_needing_mid = []
                for pdf_path in self.file_paths:
                    items = extraction_results.get(pdf_path, [])
                    if items and any(not (it.get('mid') or '').strip() for it in items):
                        files_needing_mid.append(pdf_path.name)
                if files_needing_mid:
                    self.log_message.emit(
                        f"  Auto-MID could not resolve a MID for {len(files_needing_mid)} file(s) — prompting user..."
                    )
                    self.mid_needed.emit(files_needing_mid)
                    chosen_mid = self._wait_for_mid()
                    if chosen_mid:
                        self.log_message.emit(f"  User provided fallback MID: {chosen_mid}")
                        # Apply only to items missing a MID — don't clobber items
                        # that auto-MID already resolved correctly.
                        applied = 0
                        for pdf_path, items in extraction_results.items():
                            for it in items:
                                if not (it.get('mid') or '').strip():
                                    it['mid'] = chosen_mid
                                    applied += 1
                        self.log_message.emit(f"  Fallback MID applied to {applied} row(s)")
                    else:
                        self.log_message.emit("  No MID provided — affected rows will export with empty MID")

            # ── Phase 1.5: Batch missing parts check (all files at once) ──
            # Skip pre-flight check on reprocess (cached_items means user already handled missing parts)
            # Also skip if the operator has enabled "skip missing parts dialog" — in that
            # mode the rows still export but get flagged via ReviewFlag so the
            # operator can fix them post-export.
            if not self.cached_items and not self.skip_missing_parts_dialog:
                all_items_for_check = []
                for pdf_path in self.file_paths:
                    if pdf_path in extraction_results:
                        all_items_for_check.extend(extraction_results[pdf_path])

                if all_items_for_check:
                    missing_parts = self._check_missing_parts(all_items_for_check)
                    if missing_parts:
                        self.log_message.emit(f"  {len(missing_parts)} part(s) not in parts_master — waiting for user input...")
                        self.parts_needed.emit(missing_parts)
                        self._wait_for_parts()
                        self.log_message.emit(f"  Parts input complete — continuing enrichment")
            elif self.skip_missing_parts_dialog:
                self.log_message.emit("  Missing-parts dialog disabled — rows will export with ReviewFlag set for any unmapped/incomplete parts")

            # ── Phase 2: Sequential enrichment + export per file ──
            for idx, pdf_path in enumerate(self.file_paths):
                # Handle extraction errors
                if pdf_path in extraction_errors:
                    self.log_message.emit(f"  Skipping {pdf_path.name}: {extraction_errors[pdf_path]}")
                    self.error.emit(f"{pdf_path.name}: {extraction_errors[pdf_path]}")
                    self.file_finished.emit(pdf_path.name, False, 0)
                    self.progress.emit(idx + 1, total)
                    continue

                items = extraction_results.get(pdf_path, [])
                if not items:
                    self.file_finished.emit(pdf_path.name, False, 0)
                    self.progress.emit(idx + 1, total)
                    continue

                try:
                    # Resolve net weight — prompt user if not found
                    net_weight = self.net_weight
                    if net_weight is None or net_weight <= 0:
                        net_weight_resolved = self.processor.resolve_net_weight(items)
                        if net_weight_resolved and net_weight_resolved > 0:
                            net_weight = net_weight_resolved
                        else:
                            # Prompt user for net weight
                            self.log_message.emit(f"  Net weight not found in {pdf_path.name} — prompting user...")
                            self.weight_needed.emit(pdf_path.name)
                            net_weight = self._wait_for_weight()
                            if net_weight and net_weight > 0:
                                self.log_message.emit(f"  User provided net weight: {net_weight} kg")
                            else:
                                net_weight = 0.0
                                self._weight_warnings.append(pdf_path.name)
                                self.log_message.emit(f"  Net weight set to 0.0 for {pdf_path.name} (flagged for review)")

                    # Run enrichment + export
                    result = self.processor.process_and_export(
                        items, self.output_folder, pdf_path.name,
                        net_weight, self.profile_name, self.db_path,
                        override_mid=self.override_mid
                    )

                    # Handle both old 3-tuple and new 4-tuple returns
                    if len(result) == 4:
                        xlsx_paths, preview_df, enriched_df, stats = result
                        # Accumulate stats
                        for k, v in stats.items():
                            if isinstance(v, (int, float)):
                                all_stats[k] = all_stats.get(k, 0) + v
                            elif isinstance(v, list):
                                all_stats.setdefault(k, []).extend(v)
                            elif isinstance(v, dict):
                                all_stats.setdefault(k, {}).update(v)
                    else:
                        xlsx_paths, preview_df, enriched_df = result[:3]

                    if xlsx_paths:
                        all_xlsx_paths.extend(xlsx_paths)
                        last_preview_df = preview_df
                        last_enriched_df = enriched_df
                        self.file_finished.emit(pdf_path.name, True, len(enriched_df))

                        # Move PDF to Processed folder
                        processed_folder = pdf_path.parent / "Processed"
                        self.processor.move_to_processed(pdf_path, processed_folder)
                    else:
                        self.file_finished.emit(pdf_path.name, False, 0)

                except Exception as e:
                    self.log_message.emit(f"  Error processing {pdf_path.name}: {e}")
                    self.error.emit(f"{pdf_path.name}: {str(e)}")
                    self.file_finished.emit(pdf_path.name, False, 0)

                self.progress.emit(idx + 1, total)

            # ── Validation Summary ──
            self._emit_validation_summary(all_xlsx_paths, last_enriched_df, all_stats)

            self.log_message.emit(f"Direct export complete: {len(all_xlsx_paths)} file(s)")
            self.export_complete.emit(all_xlsx_paths, last_preview_df, last_enriched_df)

        except Exception as e:
            self.error.emit(str(e))
            self.export_complete.emit([], pd.DataFrame(), pd.DataFrame())

        finally:
            self.processor.log_callback = self._original_callback

    def _emit_validation_summary(self, xlsx_paths, enriched_df, stats):
        """Build and emit a validation summary after all files are processed."""
        total_rows = len(enriched_df) if not enriched_df.empty else 0
        not_found = 0
        incomplete = 0
        if not enriched_df.empty:
            if '_not_in_db' in enriched_df.columns:
                not_found = int(enriched_df['_not_in_db'].sum())
            if '_232_flag' in enriched_df.columns:
                incomplete = int((enriched_df['_232_flag'] == 'Incomplete').sum())

        hts_hits = stats.get('hts_hits', 0)
        hts_misses = stats.get('hts_misses', 0)
        hts_total = hts_hits + hts_misses
        hts_rate = f"{hts_hits}/{hts_total} ({hts_hits / hts_total * 100:.0f}%)" if hts_total > 0 else "N/A"
        unresolved = stats.get('unresolved_countries', [])
        unresolved_unique = sorted(set(unresolved)) if unresolved else []

        section_232 = stats.get('section_232_updates', {})

        summary = {
            'files_processed': len(xlsx_paths),
            'total_rows': total_rows,
            'not_found_parts': not_found,
            'incomplete_parts': incomplete,
            'zero_weight_files': self._weight_warnings,
            'unresolved_countries': unresolved_unique,
            'hts_hits': hts_hits,
            'hts_misses': hts_misses,
            'section_232_updates': section_232,
        }

        # Build formatted log block
        lines = [
            "",
            "=" * 45,
            "  VALIDATION SUMMARY",
            "=" * 45,
            f"  Files exported:       {len(xlsx_paths)}",
            f"  Total rows:           {total_rows}",
            f"  Not-found parts:      {not_found}",
            f"  Incomplete parts:     {incomplete}",
        ]
        if self._weight_warnings:
            lines.append(f"  Zero-weight files:    {len(self._weight_warnings)} ({', '.join(self._weight_warnings)})")
        if unresolved_unique:
            lines.append(f"  Unresolved countries: {len(unresolved_unique)} ({', '.join(unresolved_unique)})")
        lines.append(f"  HTS lookup:           {hts_rate}")
        if section_232:
            lines.append(f"  Section 232 data:     {len(section_232)} SKU(s) — review pending")
        lines.append("=" * 45)

        for line in lines:
            self.log_message.emit(line)

        self.validation_summary.emit(summary)
