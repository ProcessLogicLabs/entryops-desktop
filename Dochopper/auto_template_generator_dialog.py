"""
Auto Template Generator Dialog for DocHopper
Provides a GUI interface for analyzing PDFs and generating invoice templates.
Includes template management with grid view of all templates.
"""

import os
import re
from pathlib import Path
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QFileDialog, QGroupBox, QFormLayout,
    QMessageBox, QProgressBar, QSplitter, QWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QFont

# Base directory for templates
BASE_DIR = Path(__file__).parent


class AnalysisWorker(QThread):
    """Worker thread for PDF analysis to keep UI responsive."""
    finished = pyqtSignal(object)  # Emits the analysis result
    error = pyqtSignal(str)  # Emits error message
    progress = pyqtSignal(str)  # Emits progress messages

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path

    def run(self):
        try:
            self.progress.emit("Loading PDF...")
            from template_generator import TemplateGenerator
            generator = TemplateGenerator()

            self.progress.emit("Analyzing invoice patterns...")
            analysis = generator.analyze_pdf(self.pdf_path)

            self.progress.emit("Analysis complete")
            self.finished.emit((generator, analysis))

        except ImportError as e:
            self.error.emit(f"Missing dependency: {e}\n\nInstall pdfplumber: pip install pdfplumber")
        except Exception as e:
            self.error.emit(str(e))


class AutoTemplateGeneratorDialog(QDialog):
    """
    Auto Template Generator Dialog.
    Analyzes PDF invoices and generates template code automatically.
    Includes template management with grid view.
    """

    template_created = pyqtSignal(str, str)  # template_name, file_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Template Generator")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint)
        self.setMinimumSize(1100, 800)

        self.generator = None
        self.analysis = None
        self.current_pdf = None
        self.templates_data = []  # Store template info

        self._setup_ui()
        self._load_templates()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header
        header = QLabel("AI Template Generator")
        header.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(header)

        desc = QLabel(
            "Manage OCR invoice templates. Select an existing template to edit, or analyze a PDF to create new templates."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Main splitter - Templates on top, Editor on bottom
        main_splitter = QSplitter(Qt.Vertical)

        # Top section - Template Management
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # Template List Group
        templates_group = QGroupBox("Existing Templates")
        templates_layout = QVBoxLayout()

        # Template grid/table
        self.templates_table = QTableWidget()
        self.templates_table.setColumnCount(4)
        self.templates_table.setHorizontalHeaderLabels([
            "Template Name", "Supplier Name", "Client", "Country of Origin"
        ])
        self.templates_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.templates_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.templates_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.templates_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.templates_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.templates_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.templates_table.setAlternatingRowColors(True)
        self.templates_table.doubleClicked.connect(self._edit_selected_template)
        self.templates_table.setMinimumHeight(150)
        templates_layout.addWidget(self.templates_table)

        # Template action buttons
        template_buttons = QHBoxLayout()

        self.btn_edit_template = QPushButton("Edit Selected")
        self.btn_edit_template.clicked.connect(self._edit_selected_template)
        template_buttons.addWidget(self.btn_edit_template)

        self.btn_refresh_templates = QPushButton("Refresh")
        self.btn_refresh_templates.clicked.connect(self._load_templates)
        template_buttons.addWidget(self.btn_refresh_templates)

        self.btn_delete_template = QPushButton("Delete")
        self.btn_delete_template.clicked.connect(self._delete_selected_template)
        template_buttons.addWidget(self.btn_delete_template)

        template_buttons.addStretch()
        templates_layout.addLayout(template_buttons)

        templates_group.setLayout(templates_layout)
        top_layout.addWidget(templates_group)

        main_splitter.addWidget(top_widget)

        # Bottom section - Editor
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        # Step 1: PDF Selection (for new templates)
        pdf_group = QGroupBox("Step 1: Select Sample PDF (for new templates)")
        pdf_layout = QHBoxLayout()

        self.pdf_path_edit = QLineEdit()
        self.pdf_path_edit.setPlaceholderText("Select a sample invoice PDF to analyze...")
        self.pdf_path_edit.setReadOnly(True)
        pdf_layout.addWidget(self.pdf_path_edit, 1)

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_pdf)
        pdf_layout.addWidget(self.btn_browse)

        self.btn_analyze = QPushButton("Analyze PDF")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.clicked.connect(self._analyze_pdf)
        pdf_layout.addWidget(self.btn_analyze)

        pdf_group.setLayout(pdf_layout)
        bottom_layout.addWidget(pdf_group)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        bottom_layout.addWidget(self.progress_bar)

        # Step 2: Template Configuration
        config_group = QGroupBox("Template Settings")
        config_layout = QFormLayout()

        self.template_name_edit = QLineEdit()
        self.template_name_edit.setPlaceholderText("e.g., acme_corp (lowercase with underscores)")
        self.template_name_edit.textChanged.connect(self._update_generate_button)
        config_layout.addRow("Template Name:", self.template_name_edit)

        self.supplier_name_edit = QLineEdit()
        self.supplier_name_edit.setPlaceholderText("e.g., Acme Corporation")
        config_layout.addRow("Supplier Name:", self.supplier_name_edit)

        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("e.g., Acme Corporation")
        config_layout.addRow("Client:", self.client_edit)

        self.country_edit = QLineEdit()
        self.country_edit.setPlaceholderText("e.g., CHINA, INDIA, USA")
        config_layout.addRow("Country of Origin:", self.country_edit)

        config_group.setLayout(config_layout)
        bottom_layout.addWidget(config_group)

        # Main content area with tabs
        self.tabs = QTabWidget()

        # Tab 1: Analysis Results
        analysis_widget = QWidget()
        analysis_layout = QVBoxLayout(analysis_widget)

        self.analysis_text = QTextEdit()
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setFont(QFont("Consolas", 10))
        self.analysis_text.setPlaceholderText("Analysis results will appear here after analyzing a PDF...")
        analysis_layout.addWidget(self.analysis_text)

        self.tabs.addTab(analysis_widget, "Analysis Results")

        # Tab 2: Generated Code
        code_widget = QWidget()
        code_layout = QVBoxLayout(code_widget)

        self.code_text = QTextEdit()
        self.code_text.setFont(QFont("Consolas", 10))
        self.code_text.setPlaceholderText("Generated template code will appear here...")
        code_layout.addWidget(self.code_text)

        self.tabs.addTab(code_widget, "Template Code")

        # Tab 3: Sample Text
        sample_widget = QWidget()
        sample_layout = QVBoxLayout(sample_widget)

        self.sample_text = QTextEdit()
        self.sample_text.setReadOnly(True)
        self.sample_text.setFont(QFont("Consolas", 9))
        self.sample_text.setPlaceholderText("Extracted text from the PDF will appear here...")
        sample_layout.addWidget(self.sample_text)

        self.tabs.addTab(sample_widget, "PDF Text")

        bottom_layout.addWidget(self.tabs, 1)

        # Action buttons
        buttons_layout = QHBoxLayout()

        self.btn_generate = QPushButton("Generate Template Code")
        self.btn_generate.setEnabled(False)
        self.btn_generate.clicked.connect(self._generate_template)
        buttons_layout.addWidget(self.btn_generate)

        self.btn_save = QPushButton("Save Template")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_template)
        buttons_layout.addWidget(self.btn_save)

        buttons_layout.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        buttons_layout.addWidget(btn_close)

        bottom_layout.addLayout(buttons_layout)

        main_splitter.addWidget(bottom_widget)

        # Set splitter sizes (30% top, 70% bottom)
        main_splitter.setSizes([250, 550])

        layout.addWidget(main_splitter, 1)

        # Apply styles
        self._apply_styles()

    def _apply_styles(self):
        """Apply consistent styling to the dialog."""
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                min-width: 80px;
                padding: 6px 12px;
            }
            QPushButton:disabled {
                background-color: #e0e0e0;
                color: #888;
            }
            QTextEdit {
                border: 1px solid #ccc;
                border-radius: 3px;
            }
            QTableWidget {
                border: 1px solid #ccc;
                border-radius: 3px;
                gridline-color: #ddd;
            }
            QTableWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 5px;
                border: 1px solid #ccc;
                font-weight: bold;
            }
        """)

    def _load_templates(self):
        """Load all templates from the templates directory and populate the grid."""
        self.templates_table.setRowCount(0)
        self.templates_data = []

        templates_dir = BASE_DIR / "templates"
        if not templates_dir.exists():
            return

        # Excluded files
        excluded = {'__init__.py', 'base_template.py', 'sample_template.py', '__pycache__'}

        for file_path in sorted(templates_dir.glob("*.py")):
            if file_path.name in excluded:
                continue

            template_info = self._extract_template_info(file_path)
            if template_info:
                self.templates_data.append(template_info)
                row = self.templates_table.rowCount()
                self.templates_table.insertRow(row)

                self.templates_table.setItem(row, 0, QTableWidgetItem(template_info['name']))
                self.templates_table.setItem(row, 1, QTableWidgetItem(template_info['supplier']))
                self.templates_table.setItem(row, 2, QTableWidgetItem(template_info['client']))
                self.templates_table.setItem(row, 3, QTableWidgetItem(template_info['country']))

    def _extract_template_info(self, file_path: Path) -> dict:
        """Extract template metadata from a template file."""
        try:
            content = file_path.read_text(encoding='utf-8')

            info = {
                'file_path': str(file_path),
                'file_name': file_path.stem,
                'name': file_path.stem.replace('_', ' ').title(),
                'supplier': '',
                'client': '',
                'country': ''
            }

            # Extract name
            name_match = re.search(r'^\s*name\s*=\s*["\'](.+?)["\']', content, re.MULTILINE)
            if name_match:
                info['name'] = name_match.group(1)

            # Extract description (often contains supplier info)
            desc_match = re.search(r'^\s*description\s*=\s*["\'](.+?)["\']', content, re.MULTILINE)
            if desc_match:
                info['supplier'] = desc_match.group(1)

            # Extract client
            client_match = re.search(r'^\s*client\s*=\s*["\'](.+?)["\']', content, re.MULTILINE)
            if client_match:
                info['client'] = client_match.group(1)

            # Try to extract country from SUPPLIER_KEYWORDS or extra_columns
            if 'country_origin' in content.lower() or 'country_of_origin' in content.lower():
                # Look for common country patterns
                country_patterns = [
                    r'china', r'india', r'usa', r'mexico', r'brazil', r'czech',
                    r'el salvador', r'taiwan', r'japan', r'korea', r'vietnam'
                ]
                content_lower = content.lower()
                for pattern in country_patterns:
                    if pattern in content_lower:
                        info['country'] = pattern.upper()
                        break

            # Check docstring for country
            docstring_match = re.search(r'"""[\s\S]*?"""', content)
            if docstring_match:
                docstring = docstring_match.group(0).lower()
                for pattern in ['china', 'india', 'usa', 'mexico', 'brazil', 'czech republic',
                               'el salvador', 'taiwan', 'japan', 'korea', 'vietnam']:
                    if pattern in docstring:
                        info['country'] = pattern.upper()
                        break

            return info

        except Exception as e:
            return None

    def _edit_selected_template(self):
        """Load the selected template for editing."""
        selected_rows = self.templates_table.selectedItems()
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select a template to edit.")
            return

        row = self.templates_table.currentRow()
        if row < 0 or row >= len(self.templates_data):
            return

        template_info = self.templates_data[row]
        file_path = Path(template_info['file_path'])

        if not file_path.exists():
            QMessageBox.warning(self, "File Not Found", f"Template file not found:\n{file_path}")
            return

        try:
            # Load the template code
            code = file_path.read_text(encoding='utf-8')

            # Populate the form fields
            self.template_name_edit.setText(template_info['file_name'])
            self.supplier_name_edit.setText(template_info['supplier'])
            self.client_edit.setText(template_info['client'])
            self.country_edit.setText(template_info['country'])

            # Load the code into the editor
            self.code_text.setPlainText(code)
            self.btn_save.setEnabled(True)

            # Switch to the code tab
            self.tabs.setCurrentIndex(1)

            # Clear analysis since we're editing existing
            self.analysis_text.clear()
            self.sample_text.clear()
            self.analysis = None
            self.generator = None

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load template:\n{e}")

    def _delete_selected_template(self):
        """Delete the selected template."""
        selected_rows = self.templates_table.selectedItems()
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select a template to delete.")
            return

        row = self.templates_table.currentRow()
        if row < 0 or row >= len(self.templates_data):
            return

        template_info = self.templates_data[row]
        file_path = Path(template_info['file_path'])

        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete the template:\n\n{template_info['name']}\n\n"
            f"File: {file_path.name}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                file_path.unlink()
                self._load_templates()
                QMessageBox.information(self, "Deleted", "Template deleted successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete template:\n{e}")

    def _browse_pdf(self):
        """Open file dialog to select a PDF."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Sample PDF Invoice",
            str(Path.home()),
            "PDF Files (*.pdf);;All Files (*)"
        )

        if file_path:
            self.pdf_path_edit.setText(file_path)
            self.current_pdf = file_path
            self.btn_analyze.setEnabled(True)

            # Auto-suggest template name from filename
            filename = Path(file_path).stem
            # Clean up filename for use as template name
            clean_name = filename.lower().replace(' ', '_').replace('-', '_')
            clean_name = ''.join(c for c in clean_name if c.isalnum() or c == '_')
            self.template_name_edit.setText(clean_name)

    def _analyze_pdf(self):
        """Analyze the selected PDF."""
        if not self.current_pdf:
            return

        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setFormat("Analyzing...")
        self.btn_analyze.setEnabled(False)
        self.btn_browse.setEnabled(False)

        # Clear previous results
        self.analysis_text.clear()
        self.code_text.clear()
        self.sample_text.clear()

        # Run analysis in background thread
        self.worker = AnalysisWorker(self.current_pdf)
        self.worker.finished.connect(self._on_analysis_complete)
        self.worker.error.connect(self._on_analysis_error)
        self.worker.progress.connect(self._on_analysis_progress)
        self.worker.start()

    def _on_analysis_progress(self, message: str):
        """Handle progress updates from worker."""
        self.progress_bar.setFormat(message)

    def _on_analysis_complete(self, result):
        """Handle completed analysis."""
        self.generator, self.analysis = result

        # Hide progress
        self.progress_bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        self.btn_browse.setEnabled(True)

        # Display analysis results
        self._display_analysis()

        # Show sample text
        if self.analysis and self.analysis.raw_text:
            self.sample_text.setPlainText(self.analysis.raw_text[:10000])

        # Auto-fill supplier name if detected
        if self.analysis and self.analysis.supplier_name:
            self.supplier_name_edit.setText(self.analysis.supplier_name)

        # Enable generate button
        self._update_generate_button()

        # Switch to analysis tab
        self.tabs.setCurrentIndex(0)

    def _on_analysis_error(self, error_msg: str):
        """Handle analysis error."""
        self.progress_bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        self.btn_browse.setEnabled(True)

        QMessageBox.critical(self, "Analysis Error", f"Failed to analyze PDF:\n\n{error_msg}")

    def _display_analysis(self):
        """Display the analysis results in a formatted way."""
        if not self.analysis:
            return

        a = self.analysis
        lines = []

        lines.append("=" * 60)
        lines.append("INVOICE ANALYSIS SUMMARY")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"Supplier/Company: {a.supplier_name or 'Unknown'}")
        if a.supplier_indicators:
            lines.append(f"Indicators: {', '.join(a.supplier_indicators)}")
        lines.append("")

        if a.invoice_number_pattern:
            lines.append("INVOICE NUMBER PATTERN:")
            lines.append(f"  Pattern: {a.invoice_number_pattern.pattern}")
            lines.append(f"  Samples: {a.invoice_number_pattern.sample_matches}")
            lines.append(f"  Confidence: {a.invoice_number_pattern.confidence:.0%}")
            lines.append("")

        if a.project_number_pattern:
            lines.append("PROJECT/PO NUMBER PATTERN:")
            lines.append(f"  Pattern: {a.project_number_pattern.pattern}")
            lines.append(f"  Samples: {a.project_number_pattern.sample_matches}")
            lines.append(f"  Confidence: {a.project_number_pattern.confidence:.0%}")
            lines.append("")

        if a.line_item_pattern:
            lines.append("LINE ITEM PATTERN:")
            lines.append(f"  Pattern: {a.line_item_pattern.pattern}")
            lines.append(f"  Fields: {', '.join(a.line_item_pattern.field_names)}")
            lines.append(f"  Confidence: {a.line_item_pattern.confidence:.0%}")
            if a.line_item_pattern.sample_matches:
                lines.append("  Sample matches:")
                for match in a.line_item_pattern.sample_matches[:3]:
                    lines.append(f"    {match}")
            lines.append("")

        if a.extra_fields:
            lines.append("ADDITIONAL FIELDS DETECTED:")
            for name, pattern in a.extra_fields.items():
                lines.append(f"  {name}: {pattern.sample_matches[:3]}")
            lines.append("")

        lines.append("=" * 60)
        lines.append("SAMPLE LINES FROM INVOICE:")
        lines.append("=" * 60)
        for line in a.sample_lines[:15]:
            lines.append(f"  {line[:100]}")

        self.analysis_text.setPlainText('\n'.join(lines))

    def _update_generate_button(self):
        """Update the generate button state."""
        has_analysis = self.analysis is not None
        has_name = bool(self.template_name_edit.text().strip())
        self.btn_generate.setEnabled(has_analysis and has_name)

    def _generate_template(self):
        """Generate template code from the analysis."""
        if not self.generator or not self.analysis:
            return

        template_name = self.template_name_edit.text().strip()
        supplier_name = self.supplier_name_edit.text().strip()
        client_name = self.client_edit.text().strip()
        country = self.country_edit.text().strip()

        try:
            # Generate base code
            code = self.generator.generate_template(
                template_name=template_name,
                class_name=None
            )

            # Update the generated code with our metadata
            if supplier_name:
                code = re.sub(
                    r'(description\s*=\s*["\']).*?(["\'])',
                    f'\\1Invoices from {supplier_name}\\2',
                    code
                )
            if client_name:
                code = re.sub(
                    r'(client\s*=\s*["\']).*?(["\'])',
                    f'\\1{client_name}\\2',
                    code
                )

            # Add country_origin to extra_columns if specified
            if country and 'country_origin' not in code:
                code = re.sub(
                    r"(extra_columns\s*=\s*\[)",
                    "\\1'country_origin', ",
                    code
                )

            self.code_text.setPlainText(code)
            self.btn_save.setEnabled(True)

            # Switch to code tab
            self.tabs.setCurrentIndex(1)

        except Exception as e:
            QMessageBox.critical(self, "Generation Error", f"Failed to generate template:\n\n{e}")

    def _save_template(self):
        """Save the generated template to the templates directory."""
        template_name = self.template_name_edit.text().strip()
        if not template_name:
            QMessageBox.warning(self, "Missing Name", "Please enter a template name.")
            return

        code = self.code_text.toPlainText()
        if not code:
            QMessageBox.warning(self, "No Code", "Please generate or enter template code first.")
            return

        # Validate name
        clean_name = template_name.lower().replace(' ', '_').replace('-', '_')
        if not clean_name.replace('_', '').isalnum():
            QMessageBox.warning(
                self, "Invalid Name",
                "Template name must contain only letters, numbers, and underscores."
            )
            return

        # Check for existing template
        templates_dir = BASE_DIR / "templates"
        file_path = templates_dir / f"{clean_name}.py"

        if file_path.exists():
            reply = QMessageBox.question(
                self, "Template Exists",
                f"A template named '{clean_name}' already exists.\n\nDo you want to overwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # Save the template
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)

            QMessageBox.information(
                self, "Template Saved",
                f"Template saved successfully!\n\n"
                f"File: {file_path}\n\n"
                "The template will be available after refreshing the templates list."
            )

            # Refresh the templates list
            self._load_templates()

            # Emit signal to notify parent
            self.template_created.emit(clean_name, str(file_path))

        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save template:\n\n{e}")
