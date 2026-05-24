"""
Smart Extractor Dialog for EntryOps

PyQt5 UI for the SmartExtractor that provides an intuitive interface
for extracting line items from commercial invoices and creating templates.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFileDialog, QGroupBox,
    QFormLayout, QLineEdit, QTextEdit, QSplitter, QHeaderView,
    QMessageBox, QProgressBar, QComboBox, QSpinBox, QCheckBox,
    QTabWidget, QWidget, QApplication, QInputDialog, QPlainTextEdit
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QColor

from pathlib import Path
import os
import re
from datetime import datetime

try:
    from smart_extractor import SmartExtractor, ExtractionResult, LineItem
except ImportError:
    from entryops.smart_extractor import SmartExtractor, ExtractionResult, LineItem


class ExtractorThread(QThread):
    """Background thread for PDF extraction."""
    finished = pyqtSignal(object)  # ExtractionResult
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, pdf_path: str, pages: int = 5):
        super().__init__()
        self.pdf_path = pdf_path
        self.pages = pages

    def run(self):
        try:
            self.progress.emit("Extracting text from PDF...")
            extractor = SmartExtractor()
            result = extractor.extract_from_pdf(self.pdf_path, self.pages)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class SmartExtractorDialog(QDialog):
    """
    Dialog for extracting line items from commercial invoices
    and creating templates from successful extractions.

    Uses data shape recognition to find part numbers, quantities,
    and prices regardless of their position in the document.
    """

    # Signal emitted when extraction is complete with results
    extraction_complete = pyqtSignal(object)  # ExtractionResult

    # Signal emitted when a template is created
    template_created = pyqtSignal(str, str)  # template_name, file_path

    def __init__(self, parent=None, pdf_path: str = None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.result = None
        self.extractor_thread = None

        self.setWindowTitle("Smart Invoice Extractor")
        self.setMinimumSize(1100, 750)
        self.setup_ui()

        # Auto-load if PDF path provided
        if pdf_path and Path(pdf_path).exists():
            self.pdf_path_edit.setText(pdf_path)
            self.extract_invoice()

    def setup_ui(self):
        """Build the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header
        header = QLabel("Smart Invoice Extractor")
        header.setFont(QFont("Arial", 16, QFont.Bold))
        header.setStyleSheet("color: #2c3e50; margin-bottom: 10px;")
        layout.addWidget(header)

        desc = QLabel(
            "Extracts line items by recognizing data shapes (part codes, quantities, prices). "
            "After successful extraction, you can create a template for this supplier."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #7f8c8d; margin-bottom: 15px;")
        layout.addWidget(desc)

        # File selection
        file_group = QGroupBox("Invoice File")
        file_layout = QHBoxLayout()

        self.pdf_path_edit = QLineEdit()
        self.pdf_path_edit.setPlaceholderText("Select a PDF invoice to extract...")
        self.pdf_path_edit.setReadOnly(True)
        file_layout.addWidget(self.pdf_path_edit, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_pdf)
        file_layout.addWidget(browse_btn)

        self.pages_spin = QSpinBox()
        self.pages_spin.setRange(1, 50)
        self.pages_spin.setValue(5)
        self.pages_spin.setPrefix("Pages: ")
        self.pages_spin.setToolTip("Number of pages to process")
        file_layout.addWidget(self.pages_spin)

        extract_btn = QPushButton("Extract")
        extract_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        extract_btn.clicked.connect(self.extract_invoice)
        file_layout.addWidget(extract_btn)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # Results area with tabs
        self.tabs = QTabWidget()

        # Tab 1: Line Items Table
        items_widget = QWidget()
        items_layout = QVBoxLayout(items_widget)

        # Header info
        header_group = QGroupBox("Invoice Details")
        header_form = QFormLayout()

        self.supplier_label = QLabel("-")
        header_form.addRow("Supplier:", self.supplier_label)

        self.invoice_label = QLabel("-")
        header_form.addRow("Invoice #:", self.invoice_label)

        self.po_label = QLabel("-")
        header_form.addRow("PO Numbers:", self.po_label)

        self.items_count_label = QLabel("-")
        header_form.addRow("Items Found:", self.items_count_label)

        self.total_value_label = QLabel("-")
        self.total_value_label.setStyleSheet("font-weight: bold; color: #27ae60;")
        header_form.addRow("Invoice Total:", self.total_value_label)

        header_group.setLayout(header_form)
        items_layout.addWidget(header_group)

        # Line items table
        self.items_table = QTableWidget()
        self.items_table.setColumnCount(6)
        self.items_table.setHorizontalHeaderLabels([
            "Part Number", "Quantity", "Unit Price", "Total Price", "Description", "Confidence"
        ])
        self.items_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #ddd;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #34495e;
                color: white;
                padding: 8px;
                font-weight: bold;
            }
        """)
        items_layout.addWidget(self.items_table)

        self.tabs.addTab(items_widget, "Line Items")

        # Tab 2: Raw Text
        raw_widget = QWidget()
        raw_layout = QVBoxLayout(raw_widget)

        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setFont(QFont("Courier New", 10))
        self.raw_text.setStyleSheet("background-color: #f8f9fa;")
        raw_layout.addWidget(self.raw_text)

        self.tabs.addTab(raw_widget, "Raw Text")

        # Tab 3: Create Template
        template_widget = QWidget()
        template_layout = QVBoxLayout(template_widget)

        template_info = QLabel(
            "Create a template to automatically process future invoices from this supplier.\n"
            "The template will use the Smart Extractor with supplier-specific identification."
        )
        template_info.setWordWrap(True)
        template_info.setStyleSheet("color: #7f8c8d; margin-bottom: 15px;")
        template_layout.addWidget(template_info)

        # Template settings
        settings_group = QGroupBox("Template Settings")
        settings_form = QFormLayout()

        self.template_name_edit = QLineEdit()
        self.template_name_edit.setPlaceholderText("e.g., acme_corp (lowercase with underscores)")
        settings_form.addRow("Template Name:", self.template_name_edit)

        self.template_display_name = QLineEdit()
        self.template_display_name.setPlaceholderText("e.g., Acme Corporation")
        settings_form.addRow("Display Name:", self.template_display_name)

        self.template_client = QLineEdit()
        self.template_client.setPlaceholderText("e.g., Acme Corporation")
        settings_form.addRow("Client:", self.template_client)

        self.template_country = QLineEdit()
        self.template_country.setPlaceholderText("e.g., CHINA, INDIA, USA")
        settings_form.addRow("Country of Origin:", self.template_country)

        settings_group.setLayout(settings_form)
        template_layout.addWidget(settings_group)

        # Supplier identification
        identify_group = QGroupBox("Supplier Identification")
        identify_layout = QVBoxLayout()

        identify_label = QLabel(
            "Enter keywords that identify this supplier's invoices (one per line).\n"
            "These will be used to match incoming invoices to this template."
        )
        identify_label.setWordWrap(True)
        identify_layout.addWidget(identify_label)

        self.supplier_keywords = QPlainTextEdit()
        self.supplier_keywords.setPlaceholderText(
            "Example:\nacme corporation\nacme corp\nacme trading"
        )
        self.supplier_keywords.setMaximumHeight(100)
        identify_layout.addWidget(self.supplier_keywords)

        identify_group.setLayout(identify_layout)
        template_layout.addWidget(identify_group)

        # Preview
        preview_group = QGroupBox("Template Preview")
        preview_layout = QVBoxLayout()

        self.template_preview = QPlainTextEdit()
        self.template_preview.setReadOnly(True)
        self.template_preview.setFont(QFont("Courier New", 9))
        self.template_preview.setStyleSheet("background-color: #f8f9fa;")
        preview_layout.addWidget(self.template_preview)

        preview_btn = QPushButton("Generate Preview")
        preview_btn.clicked.connect(self.generate_template_preview)
        preview_layout.addWidget(preview_btn)

        preview_group.setLayout(preview_layout)
        template_layout.addWidget(preview_group, stretch=1)

        # Create button
        create_btn = QPushButton("Create Template")
        create_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                padding: 12px 30px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        create_btn.clicked.connect(self.create_template)
        template_layout.addWidget(create_btn)

        self.tabs.addTab(template_widget, "Create Template")

        layout.addWidget(self.tabs, stretch=1)

        # Action buttons
        btn_layout = QHBoxLayout()

        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        self.copy_btn.setEnabled(False)
        btn_layout.addWidget(self.copy_btn)

        self.export_btn = QPushButton("Export to CSV")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        btn_layout.addWidget(self.export_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def browse_pdf(self):
        """Open file dialog to select PDF."""
        start_dir = str(Path.home())
        if self.pdf_path_edit.text():
            start_dir = str(Path(self.pdf_path_edit.text()).parent)

        path, _ = QFileDialog.getOpenFileName(
            self, "Select Invoice PDF",
            start_dir,
            "PDF Files (*.pdf);;All Files (*.*)"
        )

        if path:
            self.pdf_path_edit.setText(path)
            self.extract_invoice()

    def extract_invoice(self):
        """Start extraction in background thread."""
        pdf_path = self.pdf_path_edit.text()
        if not pdf_path or not Path(pdf_path).exists():
            QMessageBox.warning(self, "No File", "Please select a PDF file first.")
            return

        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setFormat("Extracting...")

        # Clear previous results
        self.items_table.setRowCount(0)
        self.raw_text.clear()
        self.copy_btn.setEnabled(False)
        self.export_btn.setEnabled(False)

        # Start extraction thread
        self.extractor_thread = ExtractorThread(pdf_path, self.pages_spin.value())
        self.extractor_thread.finished.connect(self.on_extraction_complete)
        self.extractor_thread.error.connect(self.on_extraction_error)
        self.extractor_thread.progress.connect(self.on_progress)
        self.extractor_thread.start()

    def on_progress(self, message: str):
        """Update progress message."""
        self.progress_bar.setFormat(message)

    def on_extraction_complete(self, result: ExtractionResult):
        """Handle successful extraction."""
        self.progress_bar.setVisible(False)
        self.result = result

        # Update header info
        self.supplier_label.setText(result.supplier_name or "Unknown")
        self.invoice_label.setText(result.invoice_number or "Not found")
        self.po_label.setText(", ".join(result.po_numbers) if result.po_numbers else "None found")
        self.items_count_label.setText(str(len(result.line_items)))

        # Calculate and display invoice total
        total_value = 0.0
        for item in result.line_items:
            try:
                # Parse total_price, handling various formats
                price_str = item.total_price.replace('$', '').replace(',', '').strip()
                if price_str:
                    total_value += float(price_str)
            except (ValueError, AttributeError):
                pass
        self.total_value_label.setText(f"${total_value:,.2f}")

        # Populate table
        self.items_table.setRowCount(len(result.line_items))
        for row, item in enumerate(result.line_items):
            self.items_table.setItem(row, 0, QTableWidgetItem(item.part_number))
            self.items_table.setItem(row, 1, QTableWidgetItem(item.quantity))
            self.items_table.setItem(row, 2, QTableWidgetItem(item.unit_price))
            self.items_table.setItem(row, 3, QTableWidgetItem(item.total_price))
            self.items_table.setItem(row, 4, QTableWidgetItem(item.description))

            # Confidence with color coding
            conf_item = QTableWidgetItem(f"{item.confidence:.0%}")
            if item.confidence >= 0.9:
                conf_item.setBackground(QColor("#d5f5e3"))  # Green
            elif item.confidence >= 0.7:
                conf_item.setBackground(QColor("#fef9e7"))  # Yellow
            else:
                conf_item.setBackground(QColor("#fadbd8"))  # Red
            self.items_table.setItem(row, 5, conf_item)

        # Resize columns
        self.items_table.resizeColumnsToContents()

        # Show raw text
        self.raw_text.setPlainText(result.raw_text)

        # Enable actions
        self.copy_btn.setEnabled(len(result.line_items) > 0)
        self.export_btn.setEnabled(len(result.line_items) > 0)

        # Pre-fill template fields from extraction results
        if result.supplier_name:
            # Convert supplier name to template name
            template_name = re.sub(r'[^a-z0-9]+', '_', result.supplier_name.lower()).strip('_')
            self.template_name_edit.setText(template_name)
            self.template_display_name.setText(result.supplier_name)
            self.supplier_keywords.setPlainText(result.supplier_name.lower())

        # Emit signal
        self.extraction_complete.emit(result)

        # Show summary
        if len(result.line_items) == 0:
            QMessageBox.information(
                self, "No Items Found",
                "No line items were detected in this invoice.\n\n"
                "This may happen if:\n"
                "- The invoice format is not recognized\n"
                "- The PDF text extraction failed\n"
                "- The invoice uses an unusual layout"
            )

    def on_extraction_error(self, error: str):
        """Handle extraction error."""
        self.progress_bar.setVisible(False)
        QMessageBox.critical(
            self, "Extraction Error",
            f"Failed to extract invoice data:\n\n{error}"
        )

    def copy_to_clipboard(self):
        """Copy line items to clipboard as tab-separated values."""
        if not self.result or not self.result.line_items:
            return

        lines = ["Part Number\tQuantity\tUnit Price\tTotal Price\tDescription"]
        for item in self.result.line_items:
            lines.append(f"{item.part_number}\t{item.quantity}\t{item.unit_price}\t{item.total_price}\t{item.description}")

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)

        QMessageBox.information(
            self, "Copied",
            f"Copied {len(self.result.line_items)} line items to clipboard.\n\n"
            "You can paste this into Excel or other spreadsheet applications."
        )

    def export_csv(self):
        """Export line items to CSV file."""
        if not self.result or not self.result.line_items:
            return

        # Suggest filename based on invoice
        suggested = "extracted_items.csv"
        if self.result.invoice_number:
            suggested = f"invoice_{self.result.invoice_number}_items.csv"

        path, _ = QFileDialog.getSaveFileName(
            self, "Export to CSV",
            str(Path.home() / suggested),
            "CSV Files (*.csv)"
        )

        if not path:
            return

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("Part Number,Quantity,Unit Price,Total Price,Description\n")
                for item in self.result.line_items:
                    # Escape quotes in description
                    desc = item.description.replace('"', '""')
                    f.write(f'"{item.part_number}","{item.quantity}","{item.unit_price}","{item.total_price}","{desc}"\n')

            QMessageBox.information(
                self, "Exported",
                f"Exported {len(self.result.line_items)} line items to:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")

    def generate_template_preview(self):
        """Generate preview of the template code."""
        template_name = self.template_name_edit.text().strip()
        display_name = self.template_display_name.text().strip()
        client = self.template_client.text().strip() or "Universal"
        country = self.template_country.text().strip() or "UNKNOWN"
        keywords = [k.strip() for k in self.supplier_keywords.toPlainText().strip().split('\n') if k.strip()]

        if not template_name:
            QMessageBox.warning(self, "Missing Info", "Please enter a template name.")
            return

        if not keywords:
            QMessageBox.warning(self, "Missing Info", "Please enter at least one supplier keyword.")
            return

        # Generate class name from template name
        class_name = ''.join(word.title() for word in template_name.split('_')) + 'Template'

        # Generate the template code
        code = self._generate_template_code(
            class_name=class_name,
            display_name=display_name or template_name.replace('_', ' ').title(),
            client=client,
            country=country,
            keywords=keywords
        )

        self.template_preview.setPlainText(code)

    def _generate_template_code(self, class_name: str, display_name: str, client: str,
                                 country: str, keywords: list) -> str:
        """Generate the Python template code."""
        keywords_str = ',\n        '.join(f"'{k}'" for k in keywords)

        code = f'''"""
{display_name} Template

Auto-generated template for invoices from {display_name}.
Uses SmartExtractor for reliable extraction with supplier-specific identification.

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

import re
from typing import List, Dict
from .base_template import BaseTemplate

import sys
from pathlib import Path

parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

try:
    from smart_extractor import SmartExtractor
except ImportError:
    try:
        from entryops.smart_extractor import SmartExtractor
    except ImportError:
        SmartExtractor = None


class {class_name}(BaseTemplate):
    """
    Template for {display_name} invoices.
    Uses SmartExtractor for line item extraction.
    """

    name = "{display_name}"
    description = "Invoices from {display_name}"
    client = "{client}"
    version = "1.0.0"
    enabled = True

    extra_columns = ['po_number', 'unit_price', 'description', 'country_origin']

    # Keywords to identify this supplier
    SUPPLIER_KEYWORDS = [
        {keywords_str}
    ]

    def __init__(self):
        super().__init__()
        self._extractor = None
        self._last_result = None

    @property
    def extractor(self):
        """Lazy-load SmartExtractor."""
        if self._extractor is None and SmartExtractor is not None:
            self._extractor = SmartExtractor()
        return self._extractor

    def can_process(self, text: str) -> bool:
        """Check if this is a {display_name} invoice."""
        text_lower = text.lower()

        # Check for supplier keywords
        for keyword in self.SUPPLIER_KEYWORDS:
            if keyword in text_lower:
                return True

        return False

    def get_confidence_score(self, text: str) -> float:
        """Return confidence score for template matching."""
        if not self.can_process(text):
            return 0.0

        score = 0.7  # High base score for specific supplier match
        text_lower = text.lower()

        # Add confidence for each keyword found
        for keyword in self.SUPPLIER_KEYWORDS:
            if keyword in text_lower:
                score += 0.1
                break

        # Add confidence for client name
        if '{client.lower()}' in text_lower:
            score += 0.1

        return min(score, 1.0)

    def extract_invoice_number(self, text: str) -> str:
        """Extract invoice number."""
        patterns = [
            r'INVOICE\\s*(?:NO\\.?)?\\s*[:\\s]*([A-Z0-9][\\w\\-/]+)',
            r'Invoice\\s*(?:No\\.?|#)\\s*[:\\s]*([A-Z0-9][\\w\\-/]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "UNKNOWN"

    def extract_project_number(self, text: str) -> str:
        """Extract PO number."""
        patterns = [
            r'P\\.?O\\.?\\s*#?\\s*:?\\s*(\\d{{6,}})',
            r'Purchase\\s*Order[:\\s]*(\\d+)',
            r'\\b(400\\d{{5}})\\b',  # 8-digit PO format
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return "UNKNOWN"

    def extract_manufacturer_name(self, text: str) -> str:
        """Return the manufacturer name."""
        return "{display_name.upper()}"

    def extract_line_items(self, text: str) -> List[Dict]:
        """
        Extract line items using SmartExtractor.
        """
        if not self.extractor:
            return []

        try:
            self._last_result = self.extractor.extract_from_text(text)

            items = []
            for item in self._last_result.line_items:
                items.append({{
                    'part_number': item.part_number,
                    'quantity': item.quantity,
                    'total_price': item.total_price,
                    'unit_price': item.unit_price,
                    'description': item.description,
                    'po_number': self._last_result.po_numbers[0] if self._last_result.po_numbers else '',
                    'country_origin': '{country}',
                }})

            return items

        except Exception as e:
            print(f"SmartExtractor error: {{e}}")
            return []

    def post_process_items(self, items: List[Dict]) -> List[Dict]:
        """Post-process - deduplicate."""
        if not items:
            return items

        seen = set()
        unique_items = []

        for item in items:
            key = f"{{item['part_number']}}_{{item['quantity']}}_{{item['total_price']}}"
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        return unique_items

    def is_packing_list(self, text: str) -> bool:
        """Check if document is only a packing list."""
        text_lower = text.lower()
        if 'packing list' in text_lower and 'invoice' not in text_lower:
            return True
        return False
'''
        return code

    def create_template(self):
        """Create and save the template file."""
        template_name = self.template_name_edit.text().strip()
        display_name = self.template_display_name.text().strip()
        client = self.template_client.text().strip() or "Universal"
        country = self.template_country.text().strip() or "UNKNOWN"
        keywords = [k.strip() for k in self.supplier_keywords.toPlainText().strip().split('\n') if k.strip()]

        # Validate
        if not template_name:
            QMessageBox.warning(self, "Missing Info", "Please enter a template name.")
            return

        if not re.match(r'^[a-z][a-z0-9_]*$', template_name):
            QMessageBox.warning(
                self, "Invalid Name",
                "Template name must be lowercase, start with a letter, "
                "and contain only letters, numbers, and underscores."
            )
            return

        if not keywords:
            QMessageBox.warning(self, "Missing Info", "Please enter at least one supplier keyword.")
            return

        # Generate class name and code
        class_name = ''.join(word.title() for word in template_name.split('_')) + 'Template'
        code = self._generate_template_code(
            class_name=class_name,
            display_name=display_name or template_name.replace('_', ' ').title(),
            client=client,
            country=country,
            keywords=keywords
        )

        # Determine templates directory
        templates_dir = Path(__file__).parent / 'templates'
        if not templates_dir.exists():
            templates_dir = Path(__file__).parent.parent / 'entryops' / 'templates'

        file_path = templates_dir / f"{template_name}.py"

        # Check if file already exists
        if file_path.exists():
            reply = QMessageBox.question(
                self, "File Exists",
                f"Template '{template_name}' already exists.\n\nOverwrite?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # Save the file
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)

            QMessageBox.information(
                self, "Template Created",
                f"Template created successfully!\n\n"
                f"File: {file_path}\n\n"
                f"The template will be available after refreshing templates or restarting the application."
            )

            # Emit signal for parent to refresh templates
            self.template_created.emit(template_name, str(file_path))

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save template:\n{e}")


def main():
    """Test the dialog standalone."""
    import sys
    app = QApplication(sys.argv)
    dialog = SmartExtractorDialog()
    dialog.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
