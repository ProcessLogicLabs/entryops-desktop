"""
Auto-Update Module for EntryOps

Handles automatic application updates from GitHub Releases:
- Checks for new versions on startup
- Downloads updates in the background
- Applies updates silently
- Preserves user data and settings
"""

import os
import sys
import json
import tempfile
import subprocess
import shutil
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import logging

from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from PyQt5.QtWidgets import QMessageBox, QProgressDialog

# Configure logging
logger = logging.getLogger(__name__)


class UpdateChecker(QThread):
    """Background thread to check for updates without blocking UI."""

    update_available = pyqtSignal(dict)  # Emits release info
    check_complete = pyqtSignal(bool)  # Emits True if update available
    error_occurred = pyqtSignal(str)  # Emits error message

    def __init__(self, current_version, github_repo=None):
        super().__init__()
        if github_repo is None:
            try:
                from entryops._branding import UPDATE_REPO
            except ImportError:
                from _branding import UPDATE_REPO  # type: ignore[no-redef]
            github_repo = UPDATE_REPO
        self.current_version = current_version.lstrip('v')  # Remove 'v' prefix
        self.github_repo = github_repo
        # Fetch all releases to filter by edition (0.x.x vs 1.x.x)
        self.api_url = f"https://api.github.com/repos/{github_repo}/releases"

        # Determine major version to filter releases by compatibility
        try:
            self.major_version = int(self.current_version.split('.')[0])
        except:
            self.major_version = 0

    def run(self):
        """Check GitHub for the latest release matching current edition."""
        try:
            # Create request with User-Agent header (required by GitHub API)
            request = Request(
                self.api_url,
                headers={'User-Agent': 'EntryOps-AutoUpdater'}
            )

            # Fetch all releases
            with urlopen(request, timeout=10) as response:
                all_releases = json.loads(response.read().decode())

            # Filter releases to only those matching current major version
            compatible_releases = []
            for release in all_releases:
                if release.get('draft') or release.get('prerelease'):
                    continue  # Skip drafts and pre-releases

                tag = release['tag_name'].lstrip('v')
                try:
                    release_major = int(tag.split('.')[0])
                    if release_major == self.major_version:
                        compatible_releases.append(release)
                except:
                    continue  # Skip releases with invalid version format

            if not compatible_releases:
                self.check_complete.emit(False)
                return

            # Get the latest compatible release (first in the filtered list)
            release_data = compatible_releases[0]
            latest_version = release_data['tag_name'].lstrip('v')

            # Compare versions
            if self._is_newer_version(latest_version, self.current_version):
                # Find the installer asset
                installer_asset = None
                edition_marker = "Setup"

                for asset in release_data.get('assets', []):
                    if asset['name'].endswith('.exe') and edition_marker in asset['name']:
                        installer_asset = asset
                        break

                if installer_asset:
                    update_info = {
                        'version': latest_version,
                        'tag_name': release_data['tag_name'],
                        'name': release_data.get('name', f"Version {latest_version}"),
                        'body': release_data.get('body', 'No release notes available.'),
                        'download_url': installer_asset['browser_download_url'],
                        'download_size': installer_asset['size'],
                        'filename': installer_asset['name']
                    }
                    self.update_available.emit(update_info)
                    self.check_complete.emit(True)
                else:
                    self.check_complete.emit(False)
            else:
                self.check_complete.emit(False)

        except URLError as e:
            logger.warning(f"Failed to check for updates: {e}")
            self.error_occurred.emit(f"Could not connect to update server: {e}")
            self.check_complete.emit(False)
        except Exception as e:
            logger.error(f"Update check error: {e}")
            self.error_occurred.emit(f"Update check failed: {e}")
            self.check_complete.emit(False)

    def _is_newer_version(self, latest, current):
        """
        Compare version strings.
        Returns True if latest > current.
        Handles versions like: 0.97.57
        """
        try:
            latest_parts = [int(x) for x in latest.split('.')]
            current_parts = [int(x) for x in current.split('.')]

            # Pad to same length
            max_len = max(len(latest_parts), len(current_parts))
            latest_parts += [0] * (max_len - len(latest_parts))
            current_parts += [0] * (max_len - len(current_parts))

            return latest_parts > current_parts
        except:
            return False


class UpdateDownloader(QThread):
    """Background thread to download updates."""

    progress_changed = pyqtSignal(int, int)  # current, total
    download_complete = pyqtSignal(str)  # local file path
    download_failed = pyqtSignal(str)  # error message

    def __init__(self, download_url, filename):
        super().__init__()
        self.download_url = download_url
        self.filename = filename
        self._cancel_requested = False

    def run(self):
        """Download the update installer."""
        try:
            # Create temp directory for download
            temp_dir = Path(tempfile.gettempdir()) / "EntryOps_Updates"
            temp_dir.mkdir(exist_ok=True)

            local_path = temp_dir / self.filename

            # Download with progress
            request = Request(
                self.download_url,
                headers={'User-Agent': 'EntryOps-AutoUpdater'}
            )

            with urlopen(request, timeout=30) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                chunk_size = 8192

                with open(local_path, 'wb') as f:
                    while not self._cancel_requested:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break

                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress_changed.emit(downloaded, total_size)

            if self._cancel_requested:
                local_path.unlink(missing_ok=True)
                self.download_failed.emit("Download cancelled")
            else:
                self.download_complete.emit(str(local_path))

        except Exception as e:
            logger.error(f"Download error: {e}")
            self.download_failed.emit(str(e))

    def cancel(self):
        """Cancel the download."""
        self._cancel_requested = True


class AutoUpdateManager:
    """
    Manages the auto-update process for EntryOps.

    Usage:
        update_manager = AutoUpdateManager(main_window, current_version)
        update_manager.check_for_updates()
    """

    def __init__(self, parent_window, current_version):
        self.parent = parent_window
        self.current_version = current_version
        self.update_info = None
        self.checker = None
        self.downloader = None

    def check_for_updates(self, silent=False):
        """
        Check for updates.

        Args:
            silent: If True, don't show "no updates" message
        """
        self.silent = silent

        # Create and start checker thread
        self.checker = UpdateChecker(self.current_version)
        self.checker.update_available.connect(self._on_update_available)
        self.checker.check_complete.connect(self._on_check_complete)
        self.checker.error_occurred.connect(self._on_error)
        self.checker.start()

    def _on_update_available(self, update_info):
        """Called when an update is available."""
        self.update_info = update_info

        # Show update notification dialog
        msg = QMessageBox(self.parent)
        msg.setWindowTitle("Update Available")
        msg.setIcon(QMessageBox.Information)

        # Format message with release notes
        version = update_info['version']
        release_notes = update_info['body'][:500]  # Truncate if too long
        size_mb = update_info['download_size'] / (1024 * 1024)

        text = f"<h3>EntryOps {version} is now available!</h3>"
        text += f"<p>You are currently using version {self.current_version}</p>"
        text += f"<p><b>Download size:</b> {size_mb:.1f} MB</p>"
        text += f"<details><summary><b>What's New:</b></summary><pre>{release_notes}</pre></details>"

        msg.setText(text)
        msg.setInformativeText("Would you like to download and install this update?")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)

        if msg.exec_() == QMessageBox.Yes:
            self._download_update()

    def _on_check_complete(self, update_available):
        """Called when update check completes."""
        if not update_available and not self.silent:
            QMessageBox.information(
                self.parent,
                "No Updates",
                f"You are running the latest version ({self.current_version})."
            )

    def _on_error(self, error_msg):
        """Called when an error occurs during update check."""
        if not self.silent:
            logger.warning(f"Update check error: {error_msg}")
            # Don't bother the user with update check errors

    def _download_update(self):
        """Download the update installer."""
        # Create progress dialog
        progress = QProgressDialog(
            "Downloading update...",
            "Cancel",
            0,
            100,
            self.parent
        )
        progress.setWindowTitle("Downloading Update")
        progress.setWindowModality(2)  # Qt.WindowModal
        progress.setMinimumDuration(0)
        progress.setValue(0)

        # Create and start downloader thread
        self.downloader = UpdateDownloader(
            self.update_info['download_url'],
            self.update_info['filename']
        )

        def update_progress(current, total):
            if total > 0:
                percent = int((current / total) * 100)
                progress.setValue(percent)
                # Update label with MB downloaded
                current_mb = current / (1024 * 1024)
                total_mb = total / (1024 * 1024)
                progress.setLabelText(
                    f"Downloading update... {current_mb:.1f} MB / {total_mb:.1f} MB"
                )

        self.downloader.progress_changed.connect(update_progress)
        self.downloader.download_complete.connect(
            lambda path: self._on_download_complete(path, progress)
        )
        self.downloader.download_failed.connect(
            lambda err: self._on_download_failed(err, progress)
        )

        # Handle cancel
        progress.canceled.connect(self.downloader.cancel)

        self.downloader.start()

    def _on_download_complete(self, installer_path, progress_dialog):
        """Called when download completes successfully."""
        progress_dialog.close()

        msg = QMessageBox(self.parent)
        msg.setWindowTitle("Update Ready")
        msg.setIcon(QMessageBox.Information)
        msg.setText("The update has been downloaded successfully.")
        msg.setInformativeText(
            "EntryOps will now close and install the update. "
            "Your data and settings will be preserved."
        )
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Ok)

        if msg.exec_() == QMessageBox.Ok:
            self._install_update(installer_path)

    def _on_download_failed(self, error_msg, progress_dialog):
        """Called when download fails."""
        progress_dialog.close()

        QMessageBox.critical(
            self.parent,
            "Download Failed",
            f"Failed to download update:\n{error_msg}\n\n"
            "Please try again later or download manually from GitHub."
        )

    def _install_update(self, installer_path):
        """
        Install the update and restart the application.

        The installer runs silently and preserves user data.
        """
        try:
            # Run installer with silent flag
            # /VERYSILENT = completely silent
            # /SUPPRESSMSGBOXES = no message boxes
            # /NORESTART = don't restart computer
            # /CLOSEAPPLICATIONS = close running instances
            # /RESTARTAPPLICATIONS = restart apps closed by /CLOSEAPPLICATIONS
            subprocess.Popen(
                [
                    installer_path,
                    '/VERYSILENT',
                    '/SUPPRESSMSGBOXES',
                    '/NORESTART',
                    '/CLOSEAPPLICATIONS',
                    '/RESTARTAPPLICATIONS'
                ],
                shell=False
            )

            # Close the application
            # The installer will handle restarting if needed
            QTimer.singleShot(1000, self.parent.close)

        except Exception as e:
            QMessageBox.critical(
                self.parent,
                "Installation Failed",
                f"Failed to start installer:\n{e}\n\n"
                f"You can manually run the installer at:\n{installer_path}"
            )


def check_for_updates_on_startup(parent_window, current_version, delay_ms=3000):
    """
    Convenience function to check for updates on application startup.

    Args:
        parent_window: Main application window
        current_version: Current version string (e.g., "v0.97.57")
        delay_ms: Delay in milliseconds before checking (default 3 seconds)
    """
    manager = AutoUpdateManager(parent_window, current_version)

    # Delay the check so it doesn't slow down startup
    QTimer.singleShot(delay_ms, lambda: manager.check_for_updates(silent=True))

    return manager
