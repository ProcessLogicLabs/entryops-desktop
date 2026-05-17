"""Qt widgets specific to the ISF Filing tab.

Currently just `ISFDropZone` — a sibling of OCRMill's `PDFDropZone` that
accepts PDF, XLS, XLSX, and ZIP (extracted-on-drop). Kept here rather than
in dochopper.py so the giant main file doesn't grow further.
"""

from __future__ import annotations

import logging
import struct
import tempfile
import uuid
import zipfile
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import QFileDialog, QLabel, QMessageBox, QSizePolicy

logger = logging.getLogger(__name__)


_ACCEPTED_EXTS = (".pdf", ".xls", ".xlsx")
_ARCHIVE_EXTS = (".zip",)
_ALL_DRAG_EXTS = _ACCEPTED_EXTS + _ARCHIVE_EXTS

_DROPZONE_HINT = "Drop ISF source (PDF, XLS, or ZIP) here, or click to browse"

_STYLE_IDLE = """
QLabel {
    background: #fafafa;
    border: 3px dashed #bdbdbd;
    border-radius: 10px;
    font-weight: bold;
    color: #757575;
    padding: 15px;
    font-size: 13px;
}
"""

_STYLE_HOVER = """
QLabel {
    background: #e8f5e9;
    border: 3px dashed #4CAF50;
    border-radius: 10px;
    font-weight: bold;
    color: #2E7D32;
    padding: 15px;
    font-size: 13px;
}
"""


class ISFDropZone(QLabel):
    """Drag-and-drop zone for ISF source files."""

    files_dropped = pyqtSignal(list)

    def __init__(self, browse_folder: str | None = None, parent=None):
        super().__init__(parent)
        self.browse_folder = browse_folder or str(Path.home())
        self.setText(_DROPZONE_HINT)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._update_style(False)

    # ----- styling -----

    def _update_style(self, hover: bool) -> None:
        self.setStyleSheet(_STYLE_HOVER if hover else _STYLE_IDLE)

    # ----- Outlook drag handling -----
    #
    # Outlook attachments don't drop with standard file URLs — they use the
    # Microsoft proprietary FileGroupDescriptorW + FileContents clipboard
    # formats. This mirrors OCRMill's PDFDropZone implementation so a user
    # can drag a supplier ISF email attachment straight into the drop zone
    # without saving to disk first.

    @staticmethod
    def _has_outlook_data(mime_data) -> bool:
        for fmt in mime_data.formats():
            if 'FileGroupDescriptor' in fmt:
                return True
        return False

    @staticmethod
    def _get_outlook_filenames(mime_data) -> list[str]:
        """Extract attachment filenames from Outlook FileGroupDescriptorW.

        Format: 4-byte little-endian count, then N FILEGROUPDESCRIPTORW
        entries of 592 bytes each. The cFileName field starts at offset 76
        within an entry and holds 260 wchar_t (= 520 bytes), null-terminated.
        """
        for fmt in mime_data.formats():
            if 'FileGroupDescriptorW' in fmt:
                data = bytes(mime_data.data(fmt))
                if len(data) < 4:
                    return []
                count = struct.unpack('<I', data[:4])[0]
                names: list[str] = []
                offset = 4
                entry_size = 592
                for _ in range(count):
                    if offset + entry_size > len(data):
                        break
                    name_offset = offset + 76
                    name_bytes = data[name_offset:name_offset + 520]
                    try:
                        name = name_bytes.decode('utf-16-le').split('\x00')[0]
                        names.append(name)
                    except Exception:
                        pass
                    offset += entry_size
                return names
        return []

    @staticmethod
    def _get_outlook_file_contents(mime_data, index: int) -> bytes | None:
        """Return the file contents blob from the Outlook drag for a given
        attachment index. Qt collapses multi-attachment FileContents into a
        single format on most builds, so we just take the first non-empty
        blob — same caveat OCRMill's PDFDropZone has."""
        for fmt in mime_data.formats():
            if 'FileContents' in fmt:
                data = bytes(mime_data.data(fmt))
                if data and len(data) > 100:
                    return data
        return None

    def _extract_outlook_attachments(self, mime_data) -> list[str]:
        """Save matching ISF attachments from an Outlook drag to disk.

        Filenames are filtered to PDF / XLS / XLSX / ZIP. ZIPs are unpacked
        the same way as a dropped ZIP. Returns absolute paths that can be
        emitted to files_dropped.
        """
        filenames = self._get_outlook_filenames(mime_data)
        if not filenames:
            return []

        save_dir = Path(self.browse_folder)
        if not save_dir.exists():
            save_dir = Path(tempfile.gettempdir())

        saved: list[str] = []
        for i, name in enumerate(filenames):
            low = name.lower()
            if not low.endswith(_ALL_DRAG_EXTS):
                continue
            data = self._get_outlook_file_contents(mime_data, i)
            if not data or len(data) < 100:
                continue
            target = save_dir / name
            counter = 1
            while target.exists():
                target = save_dir / f"{Path(name).stem}_{counter}{Path(name).suffix}"
                counter += 1
            try:
                with open(target, 'wb') as f:
                    f.write(data)
                logger.info("Saved Outlook attachment: %s", target)
            except OSError as exc:
                logger.error("Failed to save Outlook attachment %s: %s", name, exc)
                continue

            if str(target).lower().endswith(_ARCHIVE_EXTS):
                saved.extend(self._extract_zip(str(target)))
            else:
                saved.append(str(target))
        return saved

    # ----- drag-drop -----

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if url.toLocalFile().lower().endswith(_ALL_DRAG_EXTS):
                    event.accept()
                    self._update_style(True)
                    return
        if self._has_outlook_data(mime):
            names = self._get_outlook_filenames(mime)
            if any(n.lower().endswith(_ALL_DRAG_EXTS) for n in names):
                event.accept()
                self._update_style(True)
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._update_style(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._update_style(False)
        mime = event.mimeData()
        files: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                fp = url.toLocalFile()
                low = fp.lower()
                if low.endswith(_ACCEPTED_EXTS):
                    files.append(fp)
                elif low.endswith(_ARCHIVE_EXTS):
                    files.extend(self._extract_zip(fp))
        if not files and self._has_outlook_data(mime):
            files = self._extract_outlook_attachments(mime)
        if files:
            self.files_dropped.emit(files)
            event.accept()
        else:
            QMessageBox.warning(
                self, "No ISF source found",
                "Drop a PDF, XLS, XLSX, or a ZIP containing one of those file types.",
            )
            event.ignore()

    def mousePressEvent(self, event) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ISF source file", self.browse_folder,
            "ISF source (*.pdf *.xls *.xlsx *.zip);;PDF (*.pdf);;Excel (*.xls *.xlsx);;ZIP (*.zip)",
        )
        if not path:
            return
        files: list[str] = []
        if path.lower().endswith(_ARCHIVE_EXTS):
            files = self._extract_zip(path)
        else:
            files = [path]
        if files:
            self.files_dropped.emit(files)

    # ----- ZIP unpack -----

    @staticmethod
    def _is_isf_filename(name: str) -> bool:
        n = name.upper()
        return any(token in n for token in ("10_PLUS_2", "10+2", "ISF"))

    def _extract_zip(self, zip_path: str) -> list[str]:
        """Extract candidate ISF files from a ZIP to a temp dir.

        Heuristic ordering returned to the caller:
          1) Files whose filename suggests ISF data (10+2 / ISF in name)
          2) Other PDFs / Excel files in the archive
        """
        out: list[str] = []
        try:
            zp = Path(zip_path)
            tmp = Path(tempfile.gettempdir()) / f"dochopper_isf_zip_{zp.stem}_{uuid.uuid4().hex[:8]}"
            tmp.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(str(zp), "r") as zf:
                for entry in zf.namelist():
                    if entry.endswith("/"):
                        continue
                    low = entry.lower()
                    if not low.endswith(_ACCEPTED_EXTS):
                        continue
                    flat = Path(entry).name or f"f{uuid.uuid4().hex[:6]}"
                    target = tmp / flat
                    counter = 1
                    while target.exists():
                        stem = Path(flat).stem
                        sfx = Path(flat).suffix
                        target = tmp / f"{stem}_{counter}{sfx}"
                        counter += 1
                    with zf.open(entry) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    out.append(str(target))
        except (zipfile.BadZipFile, OSError) as exc:
            QMessageBox.warning(self, "ZIP error", f"Could not read archive:\n{exc}")
            return []

        out.sort(key=lambda p: (0 if self._is_isf_filename(Path(p).name) else 1, p))
        return out
