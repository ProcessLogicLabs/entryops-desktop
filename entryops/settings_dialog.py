"""
Unified Settings Dialog for EntryOps

A comprehensive settings dialog that consolidates all application configuration:
- General (theme, fonts, row height)
- PDF Processing (folders, modes, auto-start, poll interval)
- AI Provider (API keys, models)
- Templates (shared folder, sync)
- Database (path, backup settings)
- Updates (check on startup)
- Authentication (domain settings)

Author: EntryOps Team
"""

import os
import sys
import sqlite3
import shutil
import logging
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QWidget, QTabWidget, QGroupBox, QLabel, QPushButton, QLineEdit,
    QComboBox, QCheckBox, QSpinBox, QSlider, QFileDialog, QMessageBox,
    QScrollArea, QFrame, QListWidget, QListWidgetItem, QColorDialog,
    QTimeEdit, QSplitter, QAbstractItemView
)
from PyQt5.QtCore import Qt, QTime
from PyQt5.QtGui import QColor, QCursor, QIcon

logger = logging.getLogger(__name__)


class UnifiedSettingsDialog(QDialog):
    """
    Unified Settings Dialog - consolidates all application settings in one place.
    """

    def __init__(self, parent=None, settings_manager=None, db_path=None, base_dir=None):
        super().__init__(parent)
        self.parent_window = parent
        self.settings_manager = settings_manager
        self.db_path = db_path
        self.base_dir = base_dir

        self.setWindowTitle("Settings")
        self.setMinimumSize(800, 700)
        self.resize(900, 750)

        # Determine theme-aware colors
        self.is_dark = hasattr(parent, 'current_theme') and parent.current_theme in ["Fusion (Dark)", "Ocean"]
        self.info_text_color = "#aaa" if self.is_dark else "#666"

        self._setup_ui()

    def _setup_ui(self):
        """Setup the dialog UI with all tabs."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create splitter with navigation list and content area
        splitter = QSplitter(Qt.Horizontal)

        # Left side: Navigation list
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(160)
        self.nav_list.setSpacing(2)
        self.nav_list.setStyleSheet("""
            QListWidget {
                border: none;
                background: transparent;
                outline: none;
            }
            QListWidget::item {
                padding: 12px 16px;
                border-radius: 4px;
                margin: 2px 8px;
            }
            QListWidget::item:selected {
                background: #2980b9;
                color: white;
            }
            QListWidget::item:hover:!selected {
                background: rgba(52, 152, 219, 0.2);
            }
        """)

        # Add navigation items
        nav_items = [
            ("General", "general"),
            ("PDF Processing", "pdf"),
            ("AI Provider", "ai"),
            ("Templates", "templates"),
            ("Database", "database"),
            ("Updates", "updates"),
            ("Authentication", "auth"),
        ]

        for label, key in nav_items:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.nav_list.addItem(item)

        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)

        splitter.addWidget(self.nav_list)

        # Right side: Stacked content area
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(20, 20, 20, 20)

        # Create scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self.pages_container = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_container)
        self.pages_layout.setContentsMargins(0, 0, 0, 0)

        # Create all pages
        self.pages = {}
        self._create_general_page()
        self._create_pdf_processing_page()
        self._create_ai_provider_page()
        self._create_templates_page()
        self._create_database_page()
        self._create_updates_page()
        self._create_auth_page()

        # Add all pages (initially hidden except first)
        for key, page in self.pages.items():
            self.pages_layout.addWidget(page)
            page.setVisible(key == "general")

        scroll.setWidget(self.pages_container)
        self.content_layout.addWidget(scroll)

        splitter.addWidget(self.content_area)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # Bottom button row
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(20, 10, 20, 15)
        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _on_nav_changed(self, index):
        """Handle navigation selection change."""
        if index < 0:
            return
        item = self.nav_list.item(index)
        key = item.data(Qt.UserRole)

        # Hide all pages, show selected
        for page_key, page in self.pages.items():
            page.setVisible(page_key == key)

    def _get_button_style(self, style_type="primary"):
        """Get button stylesheet."""
        if style_type == "primary":
            return """
                QPushButton {
                    background-color: #3498db;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2980b9;
                }
                QPushButton:pressed {
                    background-color: #1f6dad;
                }
            """
        elif style_type == "success":
            return """
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #219a52;
                }
                QPushButton:pressed {
                    background-color: #1a8044;
                }
            """
        return ""

    # =========================================================================
    # GENERAL PAGE
    # =========================================================================

    def _create_general_page(self):
        """Create the General settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(15)

        # Page title
        title = QLabel("<h2>General Settings</h2>")
        layout.addWidget(title)

        # Appearance Group
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QFormLayout()

        # Theme selection
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([
            "System Default", "Fusion (Light)", "macOS",
            "Fusion (Dark)", "Ocean", "Light Cyan", "Muted Cyan"
        ])
        saved_theme = self.settings_manager.get_user_setting('theme', 'Muted Cyan') if self.settings_manager else 'Muted Cyan'
        idx = self.theme_combo.findText(saved_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentTextChanged.connect(self._apply_theme)
        appearance_layout.addRow("Application Theme:", self.theme_combo)

        theme_info = QLabel("<small>Theme changes apply immediately.</small>")
        theme_info.setStyleSheet(f"color: {self.info_text_color};")
        appearance_layout.addRow("", theme_info)

        # Font size slider
        font_layout = QHBoxLayout()
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setMinimum(8)
        self.font_slider.setMaximum(16)
        self.font_slider.setTickPosition(QSlider.TicksBelow)
        self.font_slider.setTickInterval(1)

        self.font_label = QLabel("9pt")
        self.font_label.setMinimumWidth(40)

        saved_font = self.settings_manager.get_user_setting_int('font_size', 9) if self.settings_manager else 9
        self.font_slider.setValue(saved_font)
        self.font_label.setText(f"{saved_font}pt")
        self.font_slider.valueChanged.connect(self._update_font_size)

        font_layout.addWidget(self.font_slider)
        font_layout.addWidget(self.font_label)
        appearance_layout.addRow("Font Size:", font_layout)

        # Row height slider
        row_height_layout = QHBoxLayout()
        self.row_height_slider = QSlider(Qt.Horizontal)
        self.row_height_slider.setMinimum(22)
        self.row_height_slider.setMaximum(40)
        self.row_height_slider.setTickPosition(QSlider.TicksBelow)
        self.row_height_slider.setTickInterval(4)

        self.row_height_label = QLabel("22px")
        self.row_height_label.setMinimumWidth(40)

        saved_row_height = self.settings_manager.get_user_setting_int('preview_row_height', 22) if self.settings_manager else 22
        self.row_height_slider.setValue(saved_row_height)
        self.row_height_label.setText(f"{saved_row_height}px")
        self.row_height_slider.valueChanged.connect(self._update_row_height)

        row_height_layout.addWidget(self.row_height_slider)
        row_height_layout.addWidget(self.row_height_label)
        appearance_layout.addRow("Preview Row Height:", row_height_layout)

        # Remember window size and position checkbox
        self.remember_window_cb = QCheckBox("Remember window size and position")
        saved_remember = self.settings_manager.get_user_setting_bool('remember_window_geometry', False) if self.settings_manager else False
        self.remember_window_cb.setChecked(saved_remember)
        self.remember_window_cb.stateChanged.connect(self._save_remember_window)
        appearance_layout.addRow("", self.remember_window_cb)

        remember_info = QLabel("<small>Restore window size and position when application reopens.</small>")
        remember_info.setStyleSheet(f"color: {self.info_text_color};")
        appearance_layout.addRow("", remember_info)

        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)

        # Excel Viewer Group
        viewer_group = QGroupBox("Excel File Viewer")
        viewer_layout = QFormLayout()

        self.viewer_combo = QComboBox()
        if sys.platform == 'linux':
            self.viewer_combo.addItems(["System Default", "Gnumeric"])
        else:
            self.viewer_combo.addItems(["System Default"])
            self.viewer_combo.setEnabled(False)

        saved_viewer = self.settings_manager.get_user_setting('excel_viewer', 'System Default') if self.settings_manager else 'System Default'
        idx = self.viewer_combo.findText(saved_viewer)
        if idx >= 0:
            self.viewer_combo.setCurrentIndex(idx)
        self.viewer_combo.currentTextChanged.connect(self._save_viewer)
        viewer_layout.addRow("Open Exported Files With:", self.viewer_combo)

        viewer_info = QLabel("<small>Choose which application opens exported Excel files. (Linux only)</small>")
        viewer_info.setStyleSheet(f"color: {self.info_text_color};")
        viewer_layout.addRow("", viewer_info)

        viewer_group.setLayout(viewer_layout)
        layout.addWidget(viewer_group)

        # Workflow Options Group
        workflow_group = QGroupBox("Workflow Options")
        workflow_layout = QFormLayout()

        self.show_division_cb = QCheckBox("Show Division selector on Invoice Processing tab")
        saved_show_div = self.settings_manager.get_user_setting_bool('show_division_selector', True) if self.settings_manager else True
        self.show_division_cb.setChecked(saved_show_div)
        self.show_division_cb.stateChanged.connect(self._save_division_visibility)
        workflow_layout.addRow("", self.show_division_cb)

        workflow_info = QLabel("<small>Division selector allows enforcing file number patterns per division.</small>")
        workflow_info.setStyleSheet(f"color: {self.info_text_color};")
        workflow_layout.addRow("", workflow_info)

        workflow_group.setLayout(workflow_layout)
        layout.addWidget(workflow_group)

        # Preview Table Colors Group
        colors_group = QGroupBox("Preview Table Row Colors")
        colors_main_layout = QVBoxLayout()
        colors_main_layout.setSpacing(12)
        colors_main_layout.setContentsMargins(15, 15, 15, 15)

        # Store color swatches for later reference
        self.color_swatches = {}

        # Section 232 Materials header
        sec232_label = QLabel("Section 232 Materials")
        sec232_label.setStyleSheet(f"font-weight: bold; color: {self.info_text_color}; margin-bottom: 4px; padding: 4px 0;")
        sec232_label.setMinimumHeight(24)
        colors_main_layout.addWidget(sec232_label)

        # First row: Steel, Aluminum, Copper
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(20)
        row1_layout.addWidget(self._create_color_swatch("Steel", 'preview_steel_color', '#4a4a4a'))
        row1_layout.addWidget(self._create_color_swatch("Aluminum", 'preview_aluminum_color', '#3498db'))
        row1_layout.addWidget(self._create_color_swatch("Copper", 'preview_copper_color', '#e67e22'))
        row1_layout.addStretch()
        colors_main_layout.addLayout(row1_layout)

        # Second row: Wood, Auto, Non-232
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(20)
        row2_layout.addWidget(self._create_color_swatch("Wood", 'preview_wood_color', '#27ae60'))
        row2_layout.addWidget(self._create_color_swatch("Auto", 'preview_auto_color', '#9b59b6'))
        row2_layout.addWidget(self._create_color_swatch("Non-232", 'preview_non232_color', '#ff0000'))
        row2_layout.addStretch()
        colors_main_layout.addLayout(row2_layout)

        # Third row: Cast Iron (zero-metal 232 — files under 9903.82.01)
        # Distinct color so filers can spot cast-iron parts that ride a
        # 232_Steel/Aluminum HTS classification but pay no Section 232 duty.
        row_castiron_layout = QHBoxLayout()
        row_castiron_layout.setSpacing(20)
        row_castiron_layout.addWidget(self._create_color_swatch("Cast Iron (9903.82.01)", 'preview_zero_metal_232_color', '#FF6600', label_width=160))
        row_castiron_layout.addStretch()
        colors_main_layout.addLayout(row_castiron_layout)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("margin: 8px 0;")
        colors_main_layout.addWidget(separator)

        # Other Indicators header
        other_label = QLabel("Other Indicators")
        other_label.setStyleSheet(f"font-weight: bold; color: {self.info_text_color}; margin-bottom: 4px; padding: 4px 0;")
        other_label.setMinimumHeight(24)
        colors_main_layout.addWidget(other_label)

        # Not Found, Incomplete, and Sec301 rows
        row3_layout = QHBoxLayout()
        row3_layout.setSpacing(20)
        row3_layout.addWidget(self._create_color_swatch("Not Found", 'preview_notfound_color', '#f39c12'))
        row3_layout.addWidget(self._create_color_swatch("Incomplete", 'preview_incomplete_color', '#e91e63'))
        row3_layout.addWidget(self._create_color_swatch("Sec 301 (BG)", 'preview_sec301_bg_color', '#ffc8c8'))
        row3_layout.addStretch()
        colors_main_layout.addLayout(row3_layout)

        # Cell Selection Highlight row
        row4_layout = QHBoxLayout()
        row4_layout.setSpacing(20)
        row4_layout.addWidget(self._create_color_swatch("Cell Highlight", 'preview_highlight_color', '#1e3c64', label_width=85))
        row4_layout.addStretch()
        colors_main_layout.addLayout(row4_layout)

        colors_group.setLayout(colors_main_layout)
        layout.addWidget(colors_group)

        # Preview Column Visibility Group
        columns_group = QGroupBox("Result Preview Column Visibility")
        columns_layout = QVBoxLayout()

        # Column names and their default visibility
        column_names = [
            "Product No", "Value", "HTS", "MID", "Qty1", "Qty2", "Qty Unit", "Dec",
            "Melt", "Cast", "Smelt", "Flag", "Steel%", "Al%", "Cu%", "Wood%", "Auto%", "Non-232%", "232 Status", "Cust Ref"
        ]

        # Create checkboxes in a grid layout
        columns_grid = QGridLayout()
        self.preview_column_checkboxes = []

        for i, col_name in enumerate(column_names):
            checkbox = QCheckBox(col_name)
            checkbox.setChecked(True)  # Default to visible

            # Load saved visibility preference
            config_key = f'preview_col_visible_{i}'
            try:
                if self.db_path:
                    conn = sqlite3.connect(str(self.db_path))
                    c = conn.cursor()
                    c.execute("SELECT value FROM app_config WHERE key = ?", (config_key,))
                    row = c.fetchone()
                    conn.close()
                    if row:
                        checkbox.setChecked(row[0] == '1')
            except Exception:
                pass

            # Save preference and apply when changed
            checkbox.stateChanged.connect(self._make_column_toggle_handler(i))
            self.preview_column_checkboxes.append(checkbox)

            # Arrange in 5 columns
            row_num = i // 5
            col_num = i % 5
            columns_grid.addWidget(checkbox, row_num, col_num)

        columns_layout.addLayout(columns_grid)

        columns_info = QLabel("<small>Toggle columns to show or hide them in the Result Preview table.</small>")
        columns_info.setWordWrap(True)
        columns_info.setStyleSheet(f"color: {self.info_text_color}; padding: 5px;")
        columns_layout.addWidget(columns_info)

        columns_group.setLayout(columns_layout)
        layout.addWidget(columns_group)

        layout.addStretch()
        self.pages["general"] = page

    def _create_color_swatch(self, label_text, config_key, default_color, label_width=70):
        """Create a label with small color swatch button (theme-specific)."""
        container = QWidget()
        container.setMinimumHeight(28)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 2, 8, 2)
        layout.setSpacing(6)

        # Text label with fixed width for alignment
        label = QLabel(label_text + ":")
        label.setFixedWidth(label_width)
        layout.addWidget(label)

        # Small color swatch button
        button = QPushButton()
        button.setFixedSize(20, 20)
        button.setCursor(QCursor(Qt.PointingHandCursor))

        # Load saved color from per-user settings (theme-specific) or use default
        saved_color = self._get_theme_color(config_key, default_color)

        def update_button_style(color_hex):
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color_hex};
                    border: 1px solid #555;
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    border: 2px solid #888;
                }}
                QPushButton:pressed {{
                    border: 2px solid #aaa;
                }}
            """)

        update_button_style(saved_color)

        def pick_color():
            current_color = self._get_theme_color(config_key, default_color)
            color = QColorDialog.getColor(QColor(current_color), self, f"Choose {label_text} Color")
            if color.isValid():
                color_hex = color.name()
                update_button_style(color_hex)
                # Save to per-user settings (theme-specific)
                self._set_theme_color(config_key, color_hex)
                logger.info(f"Saved color preference {config_key} for current theme: {color_hex}")
                # Refresh the preview table if it exists
                if self.parent_window and hasattr(self.parent_window, 'table') and self.parent_window.table.rowCount() > 0:
                    if hasattr(self.parent_window, 'refresh_preview_colors'):
                        self.parent_window.refresh_preview_colors()
                # If this is the highlight color, apply it to the application palette
                if config_key == 'preview_highlight_color':
                    if self.parent_window and hasattr(self.parent_window, 'apply_highlight_color'):
                        self.parent_window.apply_highlight_color(color_hex)

        button.clicked.connect(pick_color)
        layout.addWidget(button)

        # Store reference for potential updates
        self.color_swatches[config_key] = button

        return container

    def _get_theme_color(self, base_key, default_color):
        """Get a color setting for the current theme."""
        theme_name = self.settings_manager.get_user_setting('theme', 'Muted Cyan') if self.settings_manager else 'Muted Cyan'
        theme_suffix = theme_name.lower().replace(' ', '_').replace('(', '').replace(')', '')
        theme_key = f"{base_key}_{theme_suffix}"
        return self.settings_manager.get_user_setting(theme_key, default_color) if self.settings_manager else default_color

    def _set_theme_color(self, base_key, color_value):
        """Save a color setting for the current theme."""
        theme_name = self.settings_manager.get_user_setting('theme', 'Muted Cyan') if self.settings_manager else 'Muted Cyan'
        theme_suffix = theme_name.lower().replace(' ', '_').replace('(', '').replace(')', '')
        theme_key = f"{base_key}_{theme_suffix}"
        if self.settings_manager:
            self.settings_manager.set_user_setting(theme_key, color_value)

    def _make_column_toggle_handler(self, col_idx):
        """Create a handler for column visibility toggle."""
        def handler(state):
            try:
                if self.db_path:
                    conn = sqlite3.connect(str(self.db_path))
                    c = conn.cursor()
                    c.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)",
                              (f'preview_col_visible_{col_idx}', '1' if state else '0'))
                    conn.commit()
                    conn.close()
                    # Apply visibility to table
                    if self.parent_window and hasattr(self.parent_window, 'table'):
                        self.parent_window.table.setColumnHidden(col_idx, not state)
                    logger.info(f"Column {col_idx} visibility set to {'visible' if state else 'hidden'}")
            except Exception as e:
                logger.error(f"Failed to save column visibility: {e}")
        return handler

    def _apply_theme(self, theme_name):
        """Apply theme change."""
        if self.parent_window and hasattr(self.parent_window, 'apply_theme'):
            self.parent_window.apply_theme(theme_name)

    def _update_font_size(self, value):
        """Update font size."""
        self.font_label.setText(f"{value}pt")
        if self.parent_window and hasattr(self.parent_window, 'apply_font_size'):
            self.parent_window.apply_font_size(value)

    def _update_row_height(self, value):
        """Update row height."""
        self.row_height_label.setText(f"{value}px")
        if self.parent_window and hasattr(self.parent_window, 'apply_row_height'):
            self.parent_window.apply_row_height(value)

    def _save_viewer(self, viewer):
        """Save excel viewer preference."""
        if self.settings_manager:
            self.settings_manager.set_user_setting('excel_viewer', viewer)

    def _save_division_visibility(self, state):
        """Save division visibility setting."""
        if self.settings_manager:
            self.settings_manager.set_user_setting('show_division_selector', state == Qt.Checked)
        if self.parent_window and hasattr(self.parent_window, '_refresh_division_combo'):
            self.parent_window._refresh_division_combo()

    def _save_remember_window(self, state):
        """Save remember window geometry setting."""
        if self.settings_manager:
            self.settings_manager.set_user_setting('remember_window_geometry', state == Qt.Checked)

    # =========================================================================
    # PDF PROCESSING PAGE
    # =========================================================================

    def _create_pdf_processing_page(self):
        """Create the PDF Processing settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(15)

        title = QLabel("<h2>PDF Processing Settings</h2>")
        layout.addWidget(title)

        description = QLabel(
            "Configure folders and options for processing PDF invoices with OCRMill."
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {self.info_text_color};")
        layout.addWidget(description)

        # Folder Configuration Group
        folder_group = QGroupBox("Folder Configuration")
        folder_layout = QFormLayout()

        # Input folder
        input_layout = QHBoxLayout()
        self.pdf_input_edit = QLineEdit()
        self.pdf_input_edit.setPlaceholderText("Select folder for PDF invoices to process")
        if self.settings_manager:
            self.pdf_input_edit.setText(os.path.normpath(self.settings_manager.pdf.input_folder) if self.settings_manager.pdf.input_folder else "")
        input_layout.addWidget(self.pdf_input_edit)

        input_browse_btn = QPushButton("Browse...")
        input_browse_btn.clicked.connect(self._browse_pdf_input)
        input_layout.addWidget(input_browse_btn)
        folder_layout.addRow("Input Folder:", input_layout)

        # Output folder
        output_layout = QHBoxLayout()
        self.pdf_output_edit = QLineEdit()
        self.pdf_output_edit.setPlaceholderText("Select folder for processed CSV output")
        if self.settings_manager:
            self.pdf_output_edit.setText(os.path.normpath(self.settings_manager.pdf.output_folder) if self.settings_manager.pdf.output_folder else "")
        output_layout.addWidget(self.pdf_output_edit)

        output_browse_btn = QPushButton("Browse...")
        output_browse_btn.clicked.connect(self._browse_pdf_output)
        output_layout.addWidget(output_browse_btn)
        folder_layout.addRow("Output Folder:", output_layout)

        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)

        # Processing Options Group
        options_group = QGroupBox("Processing Options")
        options_layout = QFormLayout()

        # Poll interval
        poll_layout = QHBoxLayout()
        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setMinimum(10)
        self.poll_interval_spin.setMaximum(3600)
        self.poll_interval_spin.setSuffix(" seconds")
        if self.settings_manager:
            self.poll_interval_spin.setValue(self.settings_manager.pdf.poll_interval)
        poll_layout.addWidget(self.poll_interval_spin)
        poll_layout.addStretch()
        options_layout.addRow("Poll Interval:", poll_layout)

        poll_info = QLabel("<small>How often to check the input folder when monitoring is enabled.</small>")
        poll_info.setStyleSheet(f"color: {self.info_text_color};")
        options_layout.addRow("", poll_info)

        # Auto-start monitoring
        self.auto_start_cb = QCheckBox("Auto-start monitoring when application launches")
        if self.settings_manager:
            self.auto_start_cb.setChecked(self.settings_manager.pdf.auto_start_monitoring)
        options_layout.addRow("", self.auto_start_cb)

        # Multi-invoice handling
        multi_label = QLabel("Multi-invoice PDFs:")
        multi_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        options_layout.addRow(multi_label)

        self.split_radio = QCheckBox("Split output (one CSV per invoice)")
        self.combine_radio = QCheckBox("Combine output (all invoices in one CSV)")

        if self.settings_manager:
            if self.settings_manager.pdf.consolidate_multi_invoice:
                self.combine_radio.setChecked(True)
            else:
                self.split_radio.setChecked(True)
        else:
            self.split_radio.setChecked(True)

        # Make them mutually exclusive
        self.split_radio.stateChanged.connect(lambda s: self.combine_radio.setChecked(False) if s else None)
        self.combine_radio.stateChanged.connect(lambda s: self.split_radio.setChecked(False) if s else None)

        options_layout.addRow("", self.split_radio)
        options_layout.addRow("", self.combine_radio)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Save button
        save_btn = QPushButton("Save PDF Settings")
        save_btn.setStyleSheet(self._get_button_style("primary"))
        save_btn.clicked.connect(self._save_pdf_settings)
        layout.addWidget(save_btn)

        layout.addStretch()
        self.pages["pdf"] = page

    def _browse_pdf_input(self):
        """Browse for PDF input folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Input Folder",
            self.pdf_input_edit.text() or str(self.base_dir) if self.base_dir else ""
        )
        if folder:
            self.pdf_input_edit.setText(os.path.normpath(folder))

    def _browse_pdf_output(self):
        """Browse for PDF output folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder",
            self.pdf_output_edit.text() or str(self.base_dir) if self.base_dir else ""
        )
        if folder:
            self.pdf_output_edit.setText(os.path.normpath(folder))

    def _save_pdf_settings(self):
        """Save PDF processing settings."""
        if self.settings_manager:
            self.settings_manager.pdf.input_folder = os.path.normpath(self.pdf_input_edit.text().strip())
            self.settings_manager.pdf.output_folder = os.path.normpath(self.pdf_output_edit.text().strip())
            self.settings_manager.pdf.poll_interval = self.poll_interval_spin.value()
            self.settings_manager.pdf.auto_start_monitoring = self.auto_start_cb.isChecked()
            self.settings_manager.pdf.consolidate_multi_invoice = self.combine_radio.isChecked()
            self.settings_manager.save_pdf_settings()

            # Update the OCRMill config in the parent window if available
            if self.parent_window and hasattr(self.parent_window, 'ocrmill_config'):
                self.parent_window.ocrmill_config.input_folder = Path(self.pdf_input_edit.text().strip())
                self.parent_window.ocrmill_config.output_folder = Path(self.pdf_output_edit.text().strip())
                self.parent_window.ocrmill_config.poll_interval = self.poll_interval_spin.value()
                self.parent_window.ocrmill_config.consolidate_multi_invoice = self.combine_radio.isChecked()

                # Update UI elements
                if hasattr(self.parent_window, 'ocrmill_input_edit'):
                    self.parent_window.ocrmill_input_edit.setText(self.pdf_input_edit.text().strip())
                if hasattr(self.parent_window, 'ocrmill_output_edit'):
                    self.parent_window.ocrmill_output_edit.setText(self.pdf_output_edit.text().strip())

            QMessageBox.information(self, "Saved", "PDF processing settings saved successfully.")

    # =========================================================================
    # AI PROVIDER PAGE
    # =========================================================================

    def _create_ai_provider_page(self):
        """Create the AI Provider settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(15)

        title = QLabel("<h2>AI Provider Settings</h2>")
        layout.addWidget(title)

        description = QLabel(
            "Configure AI providers for the Template Generator. "
            "API keys are stored securely in the local database."
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {self.info_text_color};")
        layout.addWidget(description)

        # Anthropic Configuration
        anthropic_group = QGroupBox("Anthropic (Claude)")
        anthropic_layout = QFormLayout()

        # API Key
        self.anthropic_api_key = QLineEdit()
        self.anthropic_api_key.setEchoMode(QLineEdit.Password)
        self.anthropic_api_key.setPlaceholderText("sk-ant-...")
        if self.settings_manager:
            saved_key = self.settings_manager.get_ai_api_key('anthropic')
            if saved_key:
                self.anthropic_api_key.setText(saved_key)
        anthropic_layout.addRow("API Key:", self.anthropic_api_key)

        # Default Model
        self.anthropic_model = QComboBox()
        self.anthropic_model.setEditable(True)
        self.anthropic_model.addItems([
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-20250514",
        ])
        if self.settings_manager:
            saved_model = self.settings_manager.ai.anthropic_model
            idx = self.anthropic_model.findText(saved_model)
            if idx >= 0:
                self.anthropic_model.setCurrentIndex(idx)
            else:
                self.anthropic_model.setCurrentText(saved_model)
        anthropic_layout.addRow("Default Model:", self.anthropic_model)

        # Status indicator
        status_layout = QHBoxLayout()
        self.anthropic_status_indicator = QLabel("●")
        self.anthropic_status_label = QLabel("Not configured")
        status_layout.addWidget(self.anthropic_status_indicator)
        status_layout.addWidget(self.anthropic_status_label)
        status_layout.addStretch()

        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_anthropic)
        status_layout.addWidget(test_btn)
        anthropic_layout.addRow("Status:", status_layout)

        anthropic_group.setLayout(anthropic_layout)
        layout.addWidget(anthropic_group)

        # Default Provider
        default_group = QGroupBox("Default Settings")
        default_layout = QFormLayout()

        self.default_provider_combo = QComboBox()
        self.default_provider_combo.addItems(["Anthropic", "OpenAI"])
        default_layout.addRow("Default Provider:", self.default_provider_combo)

        default_group.setLayout(default_layout)
        layout.addWidget(default_group)

        # Save button
        save_btn = QPushButton("Save AI Settings")
        save_btn.setStyleSheet(self._get_button_style("primary"))
        save_btn.clicked.connect(self._save_ai_settings)
        layout.addWidget(save_btn)

        layout.addStretch()
        self.pages["ai"] = page

        # Update status indicator
        self._update_anthropic_status()

    def _test_anthropic(self):
        """Test Anthropic API key."""
        api_key = self.anthropic_api_key.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Test Failed", "Please enter an API key.")
            return

        if api_key.startswith('sk-ant-'):
            QMessageBox.information(self, "API Key Valid",
                "API key format is valid.\nThe key will be tested when generating templates.")
            self.anthropic_status_indicator.setStyleSheet("color: #27ae60; font-size: 16px; font-weight: bold;")
            self.anthropic_status_label.setText("Key configured")
            self.anthropic_status_label.setStyleSheet("color: #27ae60;")
        else:
            QMessageBox.warning(self, "Invalid Key Format",
                "Anthropic API keys should start with 'sk-ant-'")

    def _update_anthropic_status(self):
        """Update Anthropic status indicator."""
        api_key = self.anthropic_api_key.text().strip() if hasattr(self, 'anthropic_api_key') else ""
        if api_key and api_key.startswith('sk-ant-'):
            self.anthropic_status_indicator.setStyleSheet("color: #f39c12; font-size: 16px; font-weight: bold;")
            self.anthropic_status_label.setText("Key configured - test to verify")
            self.anthropic_status_label.setStyleSheet("color: #f39c12;")
        elif api_key:
            self.anthropic_status_indicator.setStyleSheet("color: #e74c3c; font-size: 16px; font-weight: bold;")
            self.anthropic_status_label.setText("Invalid key format")
            self.anthropic_status_label.setStyleSheet("color: #e74c3c;")
        else:
            self.anthropic_status_indicator.setStyleSheet("color: #95a5a6; font-size: 16px; font-weight: bold;")
            self.anthropic_status_label.setText("Not configured")
            self.anthropic_status_label.setStyleSheet("color: #95a5a6;")

    def _save_ai_settings(self):
        """Save AI provider settings."""
        if self.settings_manager:
            api_key = self.anthropic_api_key.text().strip()
            self.settings_manager.set_ai_api_key('anthropic', api_key)
            self.settings_manager.set_ai_model('anthropic', self.anthropic_model.currentText())
            self.settings_manager.ai.default_provider = self.default_provider_combo.currentText()
            self.settings_manager.save_ai_settings()

            # Update parent window's AI settings widgets if they exist
            if self.parent_window and hasattr(self.parent_window, 'ai_anthropic_api_key'):
                self.parent_window.ai_anthropic_api_key.setText(api_key)
            if self.parent_window and hasattr(self.parent_window, 'ai_anthropic_model'):
                idx = self.parent_window.ai_anthropic_model.findText(self.anthropic_model.currentText())
                if idx >= 0:
                    self.parent_window.ai_anthropic_model.setCurrentIndex(idx)

            self._update_anthropic_status()
            QMessageBox.information(self, "Saved", "AI provider settings saved successfully.")

    # =========================================================================
    # TEMPLATES PAGE
    # =========================================================================

    def _create_templates_page(self):
        """Create the Templates settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(15)

        title = QLabel("<h2>Template Settings</h2>")
        layout.addWidget(title)

        # Shared Templates Group
        shared_group = QGroupBox("Shared Templates (Network)")
        shared_layout = QVBoxLayout()

        shared_info = QLabel(
            "Configure a shared network folder to share invoice templates across users.\n"
            "Templates from the shared folder will appear with a network indicator."
        )
        shared_info.setWordWrap(True)
        shared_layout.addWidget(shared_info)

        # Shared folder input
        folder_row = QHBoxLayout()
        folder_label = QLabel("Shared Folder:")
        folder_label.setFixedWidth(90)
        folder_row.addWidget(folder_label)

        self.shared_templates_edit = QLineEdit()
        self.shared_templates_edit.setPlaceholderText("e.g., \\\\server\\entryops\\templates")
        if self.parent_window and hasattr(self.parent_window, 'get_billing_setting'):
            self.shared_templates_edit.setText(
                self.parent_window.get_billing_setting('shared_templates_folder', '')
            )
        folder_row.addWidget(self.shared_templates_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_shared_templates)
        folder_row.addWidget(browse_btn)
        shared_layout.addLayout(folder_row)

        # Save & Sync buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        save_btn = QPushButton("Save && Refresh Templates")
        save_btn.setStyleSheet(self._get_button_style("primary"))
        save_btn.clicked.connect(self._save_shared_templates)
        btn_row.addWidget(save_btn)

        sync_btn = QPushButton("Sync Templates")
        sync_btn.setStyleSheet(self._get_button_style("success"))
        sync_btn.setToolTip("Two-way sync between local and shared folders")
        sync_btn.clicked.connect(self._sync_templates)
        btn_row.addWidget(sync_btn)

        shared_layout.addLayout(btn_row)

        templates_note = QLabel(
            "<small><b>Note:</b> Shared templates are read-only. Right-click a shared template "
            "and select 'Copy to Local' to create an editable copy.</small>"
        )
        templates_note.setWordWrap(True)
        templates_note.setStyleSheet(f"color: {self.info_text_color};")
        shared_layout.addWidget(templates_note)

        shared_group.setLayout(shared_layout)
        layout.addWidget(shared_group)

        # Local Templates Info
        local_group = QGroupBox("Local Templates")
        local_layout = QFormLayout()

        templates_dir = Path(__file__).parent / "templates"
        if not templates_dir.exists() and self.base_dir:
            templates_dir = self.base_dir / "templates"

        local_path = QLabel(str(templates_dir))
        local_path.setWordWrap(True)
        local_path.setStyleSheet("font-family: monospace; font-size: 10px;")
        local_layout.addRow("Location:", local_path)

        # Count templates
        excluded = {'__init__.py', 'base_template.py', 'sample_template.py'}
        count = 0
        if templates_dir.exists():
            count = len([f for f in templates_dir.glob("*.py") if f.name not in excluded])
        self.local_templates_count = QLabel(str(count))
        local_layout.addRow("Templates:", self.local_templates_count)

        local_group.setLayout(local_layout)
        layout.addWidget(local_group)

        layout.addStretch()
        self.pages["templates"] = page

    def _browse_shared_templates(self):
        """Browse for shared templates folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Shared Templates Folder",
            self.shared_templates_edit.text() or str(Path.home())
        )
        if folder:
            self.shared_templates_edit.setText(folder)

    def _save_shared_templates(self):
        """Save shared templates folder setting."""
        folder_path = self.shared_templates_edit.text().strip()

        # Normalize path
        if folder_path:
            if sys.platform == 'win32':
                if not folder_path.startswith('\\\\'):
                    folder_path = folder_path.replace('/', '\\')
            else:
                folder_path = folder_path.replace('\\', '/')

        if self.parent_window and hasattr(self.parent_window, 'set_billing_setting'):
            self.parent_window.set_billing_setting('shared_templates_folder', folder_path)

        if folder_path and not Path(folder_path).exists():
            QMessageBox.warning(self, "Path Not Found",
                f"The folder does not exist or is not accessible:\n{folder_path}")
        else:
            if folder_path:
                QMessageBox.information(self, "Saved",
                    f"Shared templates folder saved.\n\nTemplates from:\n{folder_path}")
            else:
                QMessageBox.information(self, "Saved", "Shared templates folder cleared.")

        # Refresh templates
        if self.parent_window and hasattr(self.parent_window, 'ocrmill_refresh_templates'):
            self.parent_window.ocrmill_refresh_templates()

    def _sync_templates(self):
        """Sync templates between local and shared folders (two-way sync)."""
        if not self.parent_window or not hasattr(self.parent_window, 'get_billing_setting'):
            QMessageBox.warning(self, "Error", "Unable to access settings.")
            return

        shared_folder = self.parent_window.get_billing_setting('shared_templates_folder', '')
        if not shared_folder:
            QMessageBox.warning(self, "No Shared Folder",
                "No shared templates folder is configured.\n\nPlease configure a shared templates folder first.")
            return

        shared_path = Path(shared_folder)
        if not shared_path.exists():
            QMessageBox.warning(self, "Folder Not Found",
                f"The shared templates folder does not exist:\n{shared_folder}")
            return

        # Get local templates directory
        source_templates_dir = Path(__file__).parent / "templates"
        install_templates_dir = self.base_dir / "templates" if self.base_dir else source_templates_dir
        local_templates_dir = source_templates_dir if source_templates_dir.exists() else install_templates_dir

        # Ensure local directory exists
        local_templates_dir.mkdir(parents=True, exist_ok=True)

        excluded = {'__init__.py', 'base_template.py', 'sample_template.py', '__pycache__'}

        # Get all template files from both locations
        local_templates = {f.name: f for f in local_templates_dir.glob("*.py") if f.name not in excluded}
        shared_templates = {f.name: f for f in shared_path.glob("*.py") if f.name not in excluded}

        # Determine what needs to be synced
        to_upload = []  # Local -> Shared (newer local)
        to_download = []  # Shared -> Local (newer shared)
        new_to_shared = []  # Local only, copy to shared
        new_to_local = []  # Shared only, copy to local

        all_template_names = set(local_templates.keys()) | set(shared_templates.keys())

        for name in all_template_names:
            local_file = local_templates.get(name)
            shared_file = shared_templates.get(name)

            if local_file and shared_file:
                # Both exist - compare modification times
                local_mtime = local_file.stat().st_mtime
                shared_mtime = shared_file.stat().st_mtime

                if local_mtime > shared_mtime + 1:  # 1 second tolerance
                    to_upload.append(name)
                elif shared_mtime > local_mtime + 1:
                    to_download.append(name)
            elif local_file and not shared_file:
                # Only exists locally - upload to shared
                new_to_shared.append(name)
            elif shared_file and not local_file:
                # Only exists in shared - download to local
                new_to_local.append(name)

        # Check if anything to sync
        total_changes = len(to_upload) + len(to_download) + len(new_to_shared) + len(new_to_local)
        if total_changes == 0:
            QMessageBox.information(self, "Already Synced",
                "All templates are already in sync. No changes needed.")
            return

        # Build confirmation message
        msg_parts = []
        if to_upload:
            msg_parts.append(f"Update {len(to_upload)} newer local template(s) to shared folder")
        if new_to_shared:
            msg_parts.append(f"Copy {len(new_to_shared)} new local template(s) to shared folder")
        if to_download:
            msg_parts.append(f"Update {len(to_download)} newer shared template(s) to local folder")
        if new_to_local:
            msg_parts.append(f"Copy {len(new_to_local)} new shared template(s) to local folder")

        reply = QMessageBox.question(
            self, "Confirm Sync",
            f"The following changes will be made:\n\n" + "\n".join(f"• {p}" for p in msg_parts) + "\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Perform sync
        uploaded = 0
        downloaded = 0
        errors = []

        # Upload: Local -> Shared
        for name in to_upload + new_to_shared:
            try:
                src = local_templates[name]
                dst = shared_path / name
                shutil.copy2(src, dst)
                uploaded += 1
            except Exception as e:
                errors.append(f"Upload {name}: {e}")

        # Download: Shared -> Local
        for name in to_download + new_to_local:
            try:
                src = shared_templates[name]
                dst = local_templates_dir / name
                shutil.copy2(src, dst)
                downloaded += 1
            except Exception as e:
                errors.append(f"Download {name}: {e}")

        # Update count label
        new_count = len([f for f in local_templates_dir.glob("*.py") if f.name not in excluded])
        if hasattr(self, 'local_templates_count'):
            self.local_templates_count.setText(str(new_count))

        # Show result
        result_msg = f"Sync complete!\n\n• Uploaded to shared: {uploaded}\n• Downloaded to local: {downloaded}"
        if errors:
            QMessageBox.warning(self, "Sync Completed with Errors",
                result_msg + "\n\nErrors:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "Sync Complete", result_msg)

        # Refresh templates list if available
        if self.parent_window and hasattr(self.parent_window, 'ocrmill_refresh_templates'):
            self.parent_window.ocrmill_refresh_templates()

    # =========================================================================
    # DATABASE PAGE
    # =========================================================================

    def _create_database_page(self):
        """Create the Database settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(15)

        title = QLabel("<h2>Database Settings</h2>")
        layout.addWidget(title)

        # Import database configuration functions
        try:
            from entryops.entryops import (
                load_shared_config, save_shared_config,
                set_database_path, get_platform_database_paths,
                RESOURCES_DIR, DB_NAME
            )
        except ImportError:
            from entryops import (
                load_shared_config, save_shared_config,
                set_database_path, get_platform_database_paths,
                RESOURCES_DIR, DB_NAME
            )

        # Current Database Info
        db_info_group = QGroupBox("Current Database")
        db_info_layout = QFormLayout()

        self.db_path_label = QLabel(str(self.db_path) if self.db_path else "Not configured")
        self.db_path_label.setWordWrap(True)
        self.db_path_label.setStyleSheet("font-family: monospace;")

        # Check if using shared or local database
        config = load_shared_config()
        is_windows_platform = sys.platform == 'win32'
        platform_key = 'windows_path' if is_windows_platform else 'linux_path'
        if config.has_option('Database', platform_key):
            platform_name = "Windows" if is_windows_platform else "Linux"
            db_type_text = f"Shared ({platform_name})"
        elif config.has_option('Database', 'path'):
            db_type_text = "Shared (Network)"
        else:
            db_type_text = "Local"

        self.db_type_label = QLabel(db_type_text)
        db_info_layout.addRow("Type:", self.db_type_label)
        db_info_layout.addRow("Location:", self.db_path_label)

        db_info_group.setLayout(db_info_layout)
        layout.addWidget(db_info_group)

        # Shared Database Configuration
        shared_group = QGroupBox("Shared Database (Multi-User)")
        shared_layout = QVBoxLayout()

        # Get current platform paths
        platform_paths = get_platform_database_paths()
        is_windows = sys.platform == 'win32'
        current_platform = "Windows" if is_windows else "Linux"

        shared_info = QLabel(
            "Configure platform-specific database paths for cross-platform use.\n"
            f"Current platform: {current_platform}\n\n"
            "When running on Linux, the Linux path is used. When running on Windows, the Windows path is used.\n"
            "This allows the same config.ini to work on both platforms."
        )
        shared_info.setWordWrap(True)
        shared_layout.addWidget(shared_info)

        # Linux path input row
        linux_row = QHBoxLayout()
        linux_label = QLabel("Linux Path:")
        linux_label.setFixedWidth(85)
        if not is_windows:
            linux_label.setStyleSheet("font-weight: bold;")
        linux_row.addWidget(linux_label)

        self.linux_path_input = QLineEdit()
        self.linux_path_input.setPlaceholderText("e.g., /home/shared/entryops.db")
        self.linux_path_input.setText(platform_paths.get('linux_path', ''))
        linux_row.addWidget(self.linux_path_input)

        linux_browse_btn = QPushButton("Browse...")
        linux_browse_btn.clicked.connect(self._browse_linux_database)
        linux_row.addWidget(linux_browse_btn)
        shared_layout.addLayout(linux_row)

        # Windows path input row
        windows_row = QHBoxLayout()
        windows_label = QLabel("Windows Path:")
        windows_label.setFixedWidth(85)
        if is_windows:
            windows_label.setStyleSheet("font-weight: bold;")
        windows_row.addWidget(windows_label)

        self.windows_path_input = QLineEdit()
        self.windows_path_input.setPlaceholderText("e.g., \\\\server\\share\\entryops.db or Z:\\shared\\entryops.db")
        self.windows_path_input.setText(platform_paths.get('windows_path', ''))
        windows_row.addWidget(self.windows_path_input)

        windows_browse_btn = QPushButton("Browse...")
        windows_browse_btn.clicked.connect(self._browse_windows_database)
        windows_row.addWidget(windows_browse_btn)
        shared_layout.addLayout(windows_row)

        # Action buttons
        btn_row = QHBoxLayout()

        apply_btn = QPushButton("Apply Platform Paths")
        apply_btn.setStyleSheet(self._get_button_style("success"))
        apply_btn.clicked.connect(self._apply_platform_paths)
        btn_row.addWidget(apply_btn)

        reset_btn = QPushButton("Use Local Database")
        reset_btn.setStyleSheet(self._get_button_style("primary"))
        reset_btn.clicked.connect(self._reset_to_local)
        btn_row.addWidget(reset_btn)

        shared_layout.addLayout(btn_row)

        # Warning about concurrent access
        warning_label = QLabel(
            "<small><b>Note:</b> SQLite on network shares works best for sequential access. "
            "Avoid having multiple users edit the same record simultaneously.</small>"
        )
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet(f"color: {self.info_text_color}; padding: 5px;")
        shared_layout.addWidget(warning_label)

        shared_group.setLayout(shared_layout)
        layout.addWidget(shared_group)

        # Backup Settings - Full Configuration
        backup_group = QGroupBox("Automatic Database Backup")
        backup_layout = QVBoxLayout()

        # Load current backup settings
        try:
            from entryops.entryops import (
                get_backup_settings, set_backup_settings,
                get_current_hostname, is_backup_machine
            )
        except ImportError:
            from entryops import (
                get_backup_settings, set_backup_settings,
                get_current_hostname, is_backup_machine
            )

        backup_settings = get_backup_settings()

        # Enable backup checkbox
        self.backup_enabled_cb = QCheckBox("Enable automatic database backups")
        self.backup_enabled_cb.setChecked(backup_settings.get('enabled', False))
        backup_layout.addWidget(self.backup_enabled_cb)

        # Backup folder row
        folder_row = QHBoxLayout()
        folder_label = QLabel("Backup Folder:")
        folder_label.setFixedWidth(100)
        folder_row.addWidget(folder_label)

        self.backup_folder_edit = QLineEdit()
        self.backup_folder_edit.setPlaceholderText("e.g., C:\\Backups\\EntryOps or /home/backups")
        self.backup_folder_edit.setText(backup_settings.get('folder', ''))
        folder_row.addWidget(self.backup_folder_edit)

        backup_browse_btn = QPushButton("Browse...")
        backup_browse_btn.clicked.connect(self._browse_backup_folder)
        folder_row.addWidget(backup_browse_btn)
        backup_layout.addLayout(folder_row)

        # Schedule row
        schedule_row = QHBoxLayout()
        schedule_label = QLabel("Schedule:")
        schedule_label.setFixedWidth(100)
        schedule_row.addWidget(schedule_label)

        self.backup_schedule_combo = QComboBox()
        self.backup_schedule_combo.addItems(["On Startup", "Daily", "Weekly"])
        schedule_map = {'startup': 0, 'daily': 1, 'weekly': 2}
        self.backup_schedule_combo.setCurrentIndex(schedule_map.get(backup_settings.get('schedule', 'daily'), 1))
        schedule_row.addWidget(self.backup_schedule_combo)

        schedule_row.addSpacing(20)

        # Backup time (for daily/weekly schedules)
        self.time_label = QLabel("at")
        schedule_row.addWidget(self.time_label)

        self.backup_time_edit = QTimeEdit()
        backup_time_str = backup_settings.get('backup_time', '02:00')
        try:
            hour, minute = map(int, backup_time_str.split(':'))
            self.backup_time_edit.setTime(QTime(hour, minute))
        except Exception:
            self.backup_time_edit.setTime(QTime(2, 0))
        self.backup_time_edit.setDisplayFormat("HH:mm")
        self.backup_time_edit.setToolTip("Time of day to run backup (for Daily/Weekly schedules)")
        schedule_row.addWidget(self.backup_time_edit)

        # Enable/disable time based on schedule
        def update_time_enabled():
            is_scheduled = self.backup_schedule_combo.currentIndex() > 0  # Daily or Weekly
            self.backup_time_edit.setEnabled(is_scheduled)
            self.time_label.setEnabled(is_scheduled)
        self.backup_schedule_combo.currentIndexChanged.connect(update_time_enabled)
        update_time_enabled()

        schedule_row.addSpacing(20)

        keep_label = QLabel("Keep backups:")
        schedule_row.addWidget(keep_label)

        self.backup_keep_spin = QSpinBox()
        self.backup_keep_spin.setRange(1, 30)
        self.backup_keep_spin.setValue(backup_settings.get('keep_count', 7))
        self.backup_keep_spin.setSuffix(" files")
        schedule_row.addWidget(self.backup_keep_spin)

        schedule_row.addStretch()
        backup_layout.addLayout(schedule_row)

        # Backup machine row (only this machine will run backups)
        machine_row = QHBoxLayout()
        machine_label = QLabel("Backup Machine:")
        machine_label.setFixedWidth(100)
        machine_row.addWidget(machine_label)

        self.backup_machine_input = QLineEdit()
        self.backup_machine_input.setPlaceholderText("Enter hostname of the machine that should run backups")
        self.backup_machine_input.setText(backup_settings.get('backup_machine', ''))
        machine_row.addWidget(self.backup_machine_input)

        current_hostname = get_current_hostname()
        use_this_btn = QPushButton("Use This PC")
        use_this_btn.setToolTip(f"Set to current machine: {current_hostname}")
        use_this_btn.clicked.connect(lambda: self.backup_machine_input.setText(current_hostname))
        machine_row.addWidget(use_this_btn)
        backup_layout.addLayout(machine_row)

        # Show current machine info
        is_designated = is_backup_machine()
        if is_designated:
            machine_status = f"<small>This machine ({current_hostname}) IS the designated backup machine.</small>"
            status_color = "#00aa00"
        elif backup_settings.get('backup_machine', ''):
            machine_status = f"<small>This machine ({current_hostname}) is NOT the backup machine. Backups managed by: {backup_settings.get('backup_machine', '')}</small>"
            status_color = self.info_text_color
        else:
            machine_status = f"<small>This machine: {current_hostname}. No backup machine designated yet.</small>"
            status_color = self.info_text_color

        self.machine_status_label = QLabel(machine_status)
        self.machine_status_label.setStyleSheet(f"color: {status_color};")
        backup_layout.addWidget(self.machine_status_label)

        # Last backup info
        last_backup_str = backup_settings.get('last_backup', '')
        if last_backup_str:
            try:
                last_dt = datetime.fromisoformat(last_backup_str)
                last_backup_display = last_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                last_backup_display = "Unknown"
        else:
            last_backup_display = "Never"

        self.last_backup_label = QLabel(f"<small>Last backup: {last_backup_display}</small>")
        self.last_backup_label.setStyleSheet(f"color: {self.info_text_color};")
        backup_layout.addWidget(self.last_backup_label)

        # Backup action buttons
        backup_btn_row = QHBoxLayout()

        save_backup_btn = QPushButton("Save Backup Settings")
        save_backup_btn.setStyleSheet(self._get_button_style("success"))
        save_backup_btn.clicked.connect(self._save_backup_settings)
        backup_btn_row.addWidget(save_backup_btn)

        backup_now_btn = QPushButton("Backup Now")
        backup_now_btn.setStyleSheet(self._get_button_style("primary"))
        backup_now_btn.clicked.connect(self._backup_now)
        backup_btn_row.addWidget(backup_now_btn)

        backup_btn_row.addStretch()
        backup_layout.addLayout(backup_btn_row)

        backup_group.setLayout(backup_layout)
        layout.addWidget(backup_group)

        layout.addStretch()
        self.pages["database"] = page

    def _browse_backup_folder(self):
        """Browse for backup folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Backup Folder",
            self.backup_folder_edit.text() or str(Path.home())
        )
        if folder:
            self.backup_folder_edit.setText(folder)

    def _save_backup_settings(self):
        """Save backup settings."""
        try:
            from entryops.entryops import (
                get_backup_settings, set_backup_settings,
                get_current_hostname
            )
        except ImportError:
            from entryops import (
                get_backup_settings, set_backup_settings,
                get_current_hostname
            )

        folder = self.backup_folder_edit.text().strip()
        enabled = self.backup_enabled_cb.isChecked()
        backup_machine = self.backup_machine_input.text().strip().upper()

        if enabled and not folder:
            QMessageBox.warning(self, "Missing Folder",
                "Please specify a backup folder before enabling automatic backups.")
            return

        if enabled and not backup_machine:
            QMessageBox.warning(self, "Missing Backup Machine",
                "Please specify which machine should run backups.\n\n"
                "Click 'Use This PC' to use the current machine, or enter a hostname.")
            return

        if enabled and folder:
            # Verify folder exists or can be created
            try:
                Path(folder).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Invalid Folder",
                    f"Cannot access or create backup folder:\n{e}")
                return

        schedule_values = ['startup', 'daily', 'weekly']
        schedule = schedule_values[self.backup_schedule_combo.currentIndex()]
        keep_count = self.backup_keep_spin.value()
        backup_time = self.backup_time_edit.time().toString("HH:mm")

        set_backup_settings(enabled, folder, schedule, keep_count, backup_machine, backup_time)

        # Update the backup scheduler if parent window has one
        if self.parent_window and hasattr(self.parent_window, '_setup_backup_scheduler'):
            self.parent_window._setup_backup_scheduler()

        # Update machine status label
        current = get_current_hostname()
        if backup_machine and current == backup_machine:
            self.machine_status_label.setText(f"<small>This machine ({current}) IS the designated backup machine.</small>")
            self.machine_status_label.setStyleSheet("color: #00aa00;")
        elif backup_machine:
            self.machine_status_label.setText(f"<small>This machine ({current}) is NOT the backup machine. Backups managed by: {backup_machine}</small>")
            self.machine_status_label.setStyleSheet(f"color: {self.info_text_color};")

        time_info = f" at {backup_time}" if schedule in ['daily', 'weekly'] else ""
        QMessageBox.information(self, "Saved",
            f"Backup settings saved.\n\n"
            f"Enabled: {'Yes' if enabled else 'No'}\n"
            f"Folder: {folder or '(not set)'}\n"
            f"Schedule: {schedule.capitalize()}{time_info}\n"
            f"Keep: {keep_count} backups\n"
            f"Backup Machine: {backup_machine or '(not set)'}")

    def _backup_now(self):
        """Perform an immediate backup."""
        try:
            from entryops.entryops import perform_database_backup, DB_PATH
        except ImportError:
            from entryops import perform_database_backup, DB_PATH

        folder = self.backup_folder_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, "No Backup Folder",
                "Please specify a backup folder first.")
            return

        # Verify folder exists or can be created
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Invalid Folder",
                f"Cannot access or create backup folder:\n{e}")
            return

        keep_count = self.backup_keep_spin.value()

        try:
            success, message, backup_path = perform_database_backup(DB_PATH, folder, keep_count)
            if success:
                # Update last backup label
                self.last_backup_label.setText(f"<small>Last backup: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small>")
                QMessageBox.information(self, "Backup Complete",
                    f"Database backed up successfully to:\n{backup_path}")
            else:
                QMessageBox.warning(self, "Backup Failed", message)
        except Exception as e:
            QMessageBox.critical(self, "Backup Error",
                f"Failed to create backup:\n{str(e)}")

    def _browse_linux_database(self):
        """Browse for Linux database file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Linux Database File",
            str(Path.home()),
            "SQLite Database (*.db);;All Files (*.*)"
        )
        if path:
            self.linux_path_input.setText(path)

    def _browse_windows_database(self):
        """Browse for Windows database file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Windows Database File",
            str(Path.home()),
            "SQLite Database (*.db);;All Files (*.*)"
        )
        if path:
            self.windows_path_input.setText(path)

    def _apply_platform_paths(self):
        """Apply platform-specific database paths."""
        try:
            from entryops.entryops import (
                load_shared_config, save_shared_config,
                set_database_path, DB_PATH
            )
        except ImportError:
            from entryops import (
                load_shared_config, save_shared_config,
                set_database_path, DB_PATH
            )

        linux_path = self.linux_path_input.text().strip()
        windows_path = self.windows_path_input.text().strip()
        is_windows = sys.platform == 'win32'

        if not linux_path and not windows_path:
            QMessageBox.warning(self, "No Paths", "Please enter at least one database path.")
            return

        # Validate current platform's path exists
        current_path = windows_path if is_windows else linux_path
        if current_path:
            path_obj = Path(current_path)
            if not path_obj.exists():
                reply = QMessageBox.question(self, "Database Not Found",
                    f"The file for your current platform does not exist:\n{current_path}\n\n"
                    "Would you like to create a new database at this location?\n"
                    "(A copy of your current database will be created)",
                    QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    try:
                        path_obj.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(DB_PATH), str(path_obj))
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Failed to create database:\n{e}")
                        return
                else:
                    return

        # Save both paths to config.ini
        if linux_path:
            set_database_path(linux_path, platform='linux')
        if windows_path:
            set_database_path(windows_path, platform='windows')

        # Update display
        active_path = windows_path if is_windows else linux_path
        if active_path:
            self.db_path_label.setText(active_path)
            current_platform = "Windows" if is_windows else "Linux"
            self.db_type_label.setText(f"Shared ({current_platform})")

        QMessageBox.information(self, "Success",
            f"Platform-specific database paths saved.\n\n"
            f"Linux: {linux_path or '(not set)'}\n"
            f"Windows: {windows_path or '(not set)'}\n\n"
            "Restart the application to use the new database.")

    def _reset_to_local(self):
        """Reset to using local database."""
        try:
            from entryops.entryops import (
                load_shared_config, save_shared_config,
                RESOURCES_DIR, DB_NAME
            )
        except ImportError:
            from entryops import (
                load_shared_config, save_shared_config,
                RESOURCES_DIR, DB_NAME
            )

        config = load_shared_config()
        # Remove all database path options
        for opt in ['path', 'linux_path', 'windows_path']:
            if config.has_option('Database', opt):
                config.remove_option('Database', opt)
        save_shared_config(config)

        self.linux_path_input.clear()
        self.windows_path_input.clear()
        local_path = RESOURCES_DIR / DB_NAME
        self.db_path_label.setText(str(local_path))
        self.db_type_label.setText("Local")

        QMessageBox.information(self, "Reset",
            "Database reset to local.\n\nRestart the application to apply changes.")

    # =========================================================================
    # UPDATES PAGE
    # =========================================================================

    def _create_updates_page(self):
        """Create the Updates settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(15)

        title = QLabel("<h2>Update Settings</h2>")
        layout.addWidget(title)

        # Auto Update Check
        update_group = QGroupBox("Automatic Update Checks")
        update_layout = QVBoxLayout()

        self.check_updates_cb = QCheckBox("Check for updates when application starts")
        saved_check = self.settings_manager.get_user_setting_bool('check_updates_on_startup', True) if self.settings_manager else True
        self.check_updates_cb.setChecked(saved_check)
        self.check_updates_cb.stateChanged.connect(self._save_update_check)
        update_layout.addWidget(self.check_updates_cb)

        update_info = QLabel(
            "<small>When enabled, the application will check for new releases on GitHub at startup. "
            "No personal data is sent.</small>"
        )
        update_info.setWordWrap(True)
        update_info.setStyleSheet(f"color: {self.info_text_color};")
        update_layout.addWidget(update_info)

        update_group.setLayout(update_layout)
        layout.addWidget(update_group)

        # Version Info
        version_group = QGroupBox("Version Information")
        version_layout = QFormLayout()

        version_label = QLabel("<b>Loading...</b>")
        # VERSION is a module-level constant, not an instance attribute
        try:
            from entryops.entryops import VERSION
            version_label.setText(f"<b>{VERSION}</b>")
        except ImportError:
            try:
                from entryops import VERSION
                version_label.setText(f"<b>{VERSION}</b>")
            except ImportError:
                version_label.setText("<b>Unknown</b>")
        version_layout.addRow("Current Version:", version_label)

        try:
            from entryops._branding import GITHUB_RELEASES_URL
        except ImportError:
            from _branding import GITHUB_RELEASES_URL  # type: ignore[no-redef]
        github_link = QLabel(f'<a href="{GITHUB_RELEASES_URL}">View releases on GitHub</a>')
        github_link.setOpenExternalLinks(True)
        version_layout.addRow("Releases:", github_link)

        version_group.setLayout(version_layout)
        layout.addWidget(version_group)

        # Check Now Button
        check_btn = QPushButton("Check for Updates Now")
        check_btn.setStyleSheet(self._get_button_style("success"))
        check_btn.clicked.connect(self._check_updates_now)
        layout.addWidget(check_btn)

        layout.addStretch()
        self.pages["updates"] = page

    def _save_update_check(self, state):
        """Save update check preference."""
        if self.settings_manager:
            self.settings_manager.set_user_setting('check_updates_on_startup', '1' if state else '0')

    def _check_updates_now(self):
        """Trigger update check."""
        self.accept()  # Close dialog
        if self.parent_window and hasattr(self.parent_window, 'check_for_updates_manual'):
            self.parent_window.check_for_updates_manual()

    # =========================================================================
    # AUTHENTICATION PAGE
    # =========================================================================

    def _create_auth_page(self):
        """Create the Authentication settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(15)

        title = QLabel("<h2>Authentication Settings</h2>")
        layout.addWidget(title)

        # Domain Authentication
        domain_group = QGroupBox("Windows Domain Authentication")
        domain_layout = QVBoxLayout()

        domain_info = QLabel(
            "Configure which Windows domains are allowed for automatic login. "
            "Users on these domains can authenticate automatically using their Windows credentials."
        )
        domain_info.setWordWrap(True)
        domain_layout.addWidget(domain_info)

        # Domains input
        domains_form = QFormLayout()
        self.domains_input = QLineEdit()
        self.domains_input.setPlaceholderText("e.g., MYCOMPANY, CORP, DOMAIN1")
        if self.parent_window and hasattr(self.parent_window, 'get_billing_setting'):
            self.domains_input.setText(
                self.parent_window.get_billing_setting('allowed_domains', '')
            )
        domains_form.addRow("Allowed Domains:", self.domains_input)

        domains_help = QLabel("<small>Enter domain names separated by commas. Case-insensitive.</small>")
        domains_help.setStyleSheet(f"color: {self.info_text_color};")
        domains_form.addRow("", domains_help)
        domain_layout.addLayout(domains_form)

        # Save button
        save_btn = QPushButton("Save Domain Settings")
        save_btn.setStyleSheet(self._get_button_style("primary"))
        save_btn.clicked.connect(self._save_domain_settings)
        domain_layout.addWidget(save_btn)

        domain_group.setLayout(domain_layout)
        layout.addWidget(domain_group)

        layout.addStretch()
        self.pages["auth"] = page

    def _save_domain_settings(self):
        """Save domain authentication settings."""
        domains = self.domains_input.text().strip()
        if self.parent_window and hasattr(self.parent_window, 'set_billing_setting'):
            self.parent_window.set_billing_setting('allowed_domains', domains)

        if domains:
            domain_list = [d.strip() for d in domains.split(',') if d.strip()]
            QMessageBox.information(self, "Saved",
                f"Allowed domains updated:\n{', '.join(domain_list)}")
        else:
            QMessageBox.information(self, "Saved",
                "No domains configured. Windows auto-login is disabled.")
