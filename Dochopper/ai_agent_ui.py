"""
AI Agent UI Components - Enhanced UI for Claude Code-like experience
Provides tool result rendering, test results panel, and enhanced chat display.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QGroupBox, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette
import json
from typing import Dict, Any, List, Optional


class CollapsibleSection(QWidget):
    """A collapsible section widget for tool results."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.is_expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Header with expand/collapse button
        self.header = QPushButton(f"+ {title}")
        self.header.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 5px 10px;
                background-color: #3d3d3d;
                border: none;
                border-radius: 3px;
                color: #e0e0e0;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
        """)
        self.header.clicked.connect(self.toggle)
        layout.addWidget(self.header)

        # Content area
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(10, 5, 10, 5)
        self.content.hide()
        layout.addWidget(self.content)

        self.title = title

    def toggle(self):
        """Toggle expanded/collapsed state."""
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        prefix = "-" if self.is_expanded else "+"
        self.header.setText(f"{prefix} {self.title}")

    def set_content_widget(self, widget: QWidget):
        """Set the content widget."""
        # Clear existing content
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.content_layout.addWidget(widget)

    def expand(self):
        """Expand the section."""
        if not self.is_expanded:
            self.toggle()

    def collapse(self):
        """Collapse the section."""
        if self.is_expanded:
            self.toggle()


class ToolResultWidget(QFrame):
    """Widget to display a single tool invocation and result."""

    def __init__(self, tool_name: str, tool_input: Dict, tool_result: Dict, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("""
            ToolResultWidget {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 5px;
                margin: 3px 0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        # Tool header
        header_layout = QHBoxLayout()

        tool_label = QLabel(f"TOOL: {tool_name}")
        tool_label.setStyleSheet("color: #7eb6ff; font-weight: bold;")
        header_layout.addWidget(tool_label)

        # Status indicator
        is_error = tool_result.get("is_error", False) or not tool_result.get("success", True)
        status = "Error" if is_error else "Success"
        status_color = "#ff6b6b" if is_error else "#69db7c"
        status_label = QLabel(status)
        status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        header_layout.addWidget(status_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Tool input summary
        input_summary = self._format_input_summary(tool_name, tool_input)
        if input_summary:
            input_label = QLabel(input_summary)
            input_label.setStyleSheet("color: #aaa; font-size: 11px;")
            input_label.setWordWrap(True)
            layout.addWidget(input_label)

        # Result display
        result_widget = self._create_result_widget(tool_name, tool_result)
        if result_widget:
            layout.addWidget(result_widget)

    def _format_input_summary(self, tool_name: str, tool_input: Dict) -> str:
        """Format tool input for display."""
        if not tool_input:
            return ""

        if tool_name == "read_template":
            return f"Template: {tool_input.get('template_name', 'unknown')}"
        elif tool_name == "edit_template":
            edit_type = tool_input.get("edit_type", "unknown")
            if edit_type == "surgical":
                old = tool_input.get("old_string", "")[:50]
                return f"Type: surgical | Find: \"{old}...\""
            return f"Type: {edit_type}"
        elif tool_name == "test_template":
            return "Testing template against loaded invoice"
        elif tool_name == "extract_invoice_text":
            return f"Pages: {tool_input.get('pages', 'all')}"
        elif tool_name == "query_database":
            return f"Table: {tool_input.get('table')} | Query: {tool_input.get('query_type')}"
        elif tool_name == "validate_syntax":
            return "Validating Python syntax"

        return json.dumps(tool_input, indent=2)[:100]

    def _create_result_widget(self, tool_name: str, result: Dict) -> Optional[QWidget]:
        """Create appropriate widget to display tool result."""
        if tool_name == "test_template":
            return self._create_test_result_widget(result)
        elif tool_name == "read_template" or tool_name == "read_base_template":
            return self._create_code_result_widget(result)
        elif tool_name == "list_templates":
            return self._create_list_result_widget(result)
        elif tool_name == "edit_template":
            return self._create_edit_result_widget(result)
        elif tool_name == "extract_invoice_text":
            return self._create_text_result_widget(result)
        elif tool_name == "validate_syntax":
            return self._create_syntax_result_widget(result)
        elif tool_name == "query_database":
            return self._create_query_result_widget(result)

        # Default: show JSON
        return self._create_json_result_widget(result)

    def _create_test_result_widget(self, result: Dict) -> QWidget:
        """Create widget for test_template results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 0)
        layout.setSpacing(3)

        if result.get("success"):
            can_process = result.get("can_process", False)
            cp_icon = "check" if can_process else "x"
            cp_color = "#69db7c" if can_process else "#ff6b6b"

            info_text = f"""
            <span style="color: {cp_color};">can_process: {can_process}</span><br>
            Invoice: {result.get('invoice_number', 'N/A')}<br>
            Project: {result.get('project_number', 'N/A')}<br>
            Items: {result.get('items_count', 0)} extracted
            """
            info_label = QLabel(info_text)
            info_label.setStyleSheet("color: #ddd;")
            layout.addWidget(info_label)

            # Items table if available
            items = result.get("items", [])
            if items:
                section = CollapsibleSection(f"View {len(items)} Items")
                table = self._create_items_table(items)
                section.set_content_widget(table)
                layout.addWidget(section)
        else:
            error_label = QLabel(f"Error: {result.get('error', 'Unknown error')}")
            error_label.setStyleSheet("color: #ff6b6b;")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

            if result.get("traceback"):
                section = CollapsibleSection("View Traceback")
                tb_edit = QTextEdit()
                tb_edit.setPlainText(result["traceback"])
                tb_edit.setReadOnly(True)
                tb_edit.setMaximumHeight(150)
                tb_edit.setStyleSheet("background-color: #1a1a1a; color: #ff8888;")
                section.set_content_widget(tb_edit)
                layout.addWidget(section)

        return widget

    def _create_items_table(self, items: List[Dict]) -> QTableWidget:
        """Create a table to display extracted items."""
        if not items:
            return QTableWidget()

        # Get all unique keys
        keys = []
        for item in items:
            for k in item.keys():
                if k not in keys:
                    keys.append(k)

        table = QTableWidget(len(items), len(keys))
        table.setHorizontalHeaderLabels(keys)
        table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                color: #ddd;
                gridline-color: #444;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #fff;
                padding: 4px;
                border: 1px solid #444;
            }
        """)

        for row, item in enumerate(items):
            for col, key in enumerate(keys):
                value = str(item.get(key, ""))
                table.setItem(row, col, QTableWidgetItem(value))

        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setMaximumHeight(200)

        return table

    def _create_code_result_widget(self, result: Dict) -> QWidget:
        """Create widget for code/template results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 0)

        if result.get("success"):
            info = f"Lines: {result.get('line_count', 0)}"
            info_label = QLabel(info)
            info_label.setStyleSheet("color: #aaa;")
            layout.addWidget(info_label)

            section = CollapsibleSection("View Code")
            code_edit = QTextEdit()
            code_edit.setPlainText(result.get("content", ""))
            code_edit.setReadOnly(True)
            code_edit.setMaximumHeight(200)
            code_edit.setStyleSheet("background-color: #1a1a1a; color: #ddd; font-family: Consolas, monospace;")
            section.set_content_widget(code_edit)
            layout.addWidget(section)
        else:
            error_label = QLabel(f"Error: {result.get('error', 'Unknown')}")
            error_label.setStyleSheet("color: #ff6b6b;")
            layout.addWidget(error_label)

        return widget

    def _create_list_result_widget(self, result: Dict) -> QWidget:
        """Create widget for list_templates results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 0)

        templates = result.get("templates", [])
        info_label = QLabel(f"Found {len(templates)} templates")
        info_label.setStyleSheet("color: #aaa;")
        layout.addWidget(info_label)

        if templates:
            text = ""
            for t in templates:
                name = t.get("name", "unknown")
                desc = t.get("description", "")[:50]
                enabled = "enabled" if t.get("enabled", True) else "disabled"
                text += f"  - {name}: {desc} [{enabled}]\n"

            section = CollapsibleSection("View Templates")
            list_edit = QTextEdit()
            list_edit.setPlainText(text)
            list_edit.setReadOnly(True)
            list_edit.setMaximumHeight(150)
            list_edit.setStyleSheet("background-color: #1a1a1a; color: #ddd;")
            section.set_content_widget(list_edit)
            layout.addWidget(section)

        return widget

    def _create_edit_result_widget(self, result: Dict) -> QWidget:
        """Create widget for edit_template results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 0)

        if result.get("success"):
            info = f"Edit type: {result.get('edit_type', 'unknown')} | Lines: {result.get('new_line_count', 0)}"
            info_label = QLabel(info)
            info_label.setStyleSheet("color: #69db7c;")
            layout.addWidget(info_label)

            if result.get("diff"):
                section = CollapsibleSection("View Diff")
                diff_edit = QTextEdit()
                diff_edit.setPlainText(result["diff"])
                diff_edit.setReadOnly(True)
                diff_edit.setMaximumHeight(150)
                diff_edit.setStyleSheet("background-color: #1a1a1a; color: #ddd; font-family: Consolas, monospace;")
                section.set_content_widget(diff_edit)
                layout.addWidget(section)
        else:
            error_label = QLabel(f"Error: {result.get('error', 'Unknown')}")
            error_label.setStyleSheet("color: #ff6b6b;")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

        return widget

    def _create_text_result_widget(self, result: Dict) -> QWidget:
        """Create widget for extract_invoice_text results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 0)

        if result.get("success"):
            info = f"Pages: {result.get('page_count', 0)} | Characters: {result.get('character_count', 0)}"
            info_label = QLabel(info)
            info_label.setStyleSheet("color: #aaa;")
            layout.addWidget(info_label)

            section = CollapsibleSection("View Text")
            text_edit = QTextEdit()
            text_edit.setPlainText(result.get("text", ""))
            text_edit.setReadOnly(True)
            text_edit.setMaximumHeight(200)
            text_edit.setStyleSheet("background-color: #1a1a1a; color: #ddd;")
            section.set_content_widget(text_edit)
            layout.addWidget(section)
        else:
            error_label = QLabel(f"Error: {result.get('error', 'Unknown')}")
            error_label.setStyleSheet("color: #ff6b6b;")
            layout.addWidget(error_label)

        return widget

    def _create_syntax_result_widget(self, result: Dict) -> QWidget:
        """Create widget for validate_syntax results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 0)

        if result.get("valid"):
            label = QLabel("Syntax is valid")
            label.setStyleSheet("color: #69db7c;")
        else:
            label = QLabel(f"Syntax error on line {result.get('error_line', '?')}: {result.get('error_message', 'Unknown')}")
            label.setStyleSheet("color: #ff6b6b;")
            label.setWordWrap(True)

        layout.addWidget(label)
        return widget

    def _create_query_result_widget(self, result: Dict) -> QWidget:
        """Create widget for query_database results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 0)

        if result.get("success"):
            if "columns" in result:
                # Schema result
                cols = result.get("columns", [])
                text = "\n".join([f"  {c['name']}: {c['type']}" for c in cols])
                info_label = QLabel(f"Table schema ({len(cols)} columns)")
                info_label.setStyleSheet("color: #aaa;")
                layout.addWidget(info_label)

                section = CollapsibleSection("View Schema")
                text_edit = QTextEdit()
                text_edit.setPlainText(text)
                text_edit.setReadOnly(True)
                text_edit.setMaximumHeight(150)
                section.set_content_widget(text_edit)
                layout.addWidget(section)
            else:
                # Search result
                results = result.get("results", [])
                info_label = QLabel(f"Found {len(results)} results")
                info_label.setStyleSheet("color: #aaa;")
                layout.addWidget(info_label)

                if results:
                    section = CollapsibleSection("View Results")
                    table = self._create_items_table(results)
                    section.set_content_widget(table)
                    layout.addWidget(section)
        else:
            error_label = QLabel(f"Error: {result.get('error', 'Unknown')}")
            error_label.setStyleSheet("color: #ff6b6b;")
            layout.addWidget(error_label)

        return widget

    def _create_json_result_widget(self, result: Dict) -> QWidget:
        """Create widget for generic JSON results."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 0)

        section = CollapsibleSection("View Result")
        text_edit = QTextEdit()
        text_edit.setPlainText(json.dumps(result, indent=2, default=str))
        text_edit.setReadOnly(True)
        text_edit.setMaximumHeight(150)
        text_edit.setStyleSheet("background-color: #1a1a1a; color: #ddd; font-family: Consolas, monospace;")
        section.set_content_widget(text_edit)
        layout.addWidget(section)

        return widget


class TestResultsPanel(QFrame):
    """Panel showing test results with extracted items."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("""
            TestResultsPanel {
                background-color: #252526;
                border: 1px solid #3c3c3c;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header
        header = QLabel("Test Results")
        header.setStyleSheet("font-size: 14px; font-weight: bold; color: #e0e0e0;")
        layout.addWidget(header)

        # Status section
        self.status_label = QLabel("No test run yet")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        # Info section
        self.info_widget = QWidget()
        info_layout = QVBoxLayout(self.info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        self.can_process_label = QLabel()
        self.invoice_label = QLabel()
        self.project_label = QLabel()
        self.items_label = QLabel()

        for lbl in [self.can_process_label, self.invoice_label, self.project_label, self.items_label]:
            lbl.setStyleSheet("color: #ccc;")
            info_layout.addWidget(lbl)

        self.info_widget.hide()
        layout.addWidget(self.info_widget)

        # Items table
        self.items_table = QTableWidget()
        self.items_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                color: #ddd;
                gridline-color: #444;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #fff;
                padding: 4px;
                border: 1px solid #444;
            }
        """)
        self.items_table.hide()
        layout.addWidget(self.items_table)

        # Error section
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #ff6b6b;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        layout.addStretch()

    def show_result(self, result: Dict):
        """Display test result."""
        if result.get("success"):
            self.status_label.setText("Status: Success")
            self.status_label.setStyleSheet("color: #69db7c; font-weight: bold;")

            can_process = result.get("can_process", False)
            cp_color = "#69db7c" if can_process else "#ff6b6b"
            self.can_process_label.setText(f"can_process: {can_process}")
            self.can_process_label.setStyleSheet(f"color: {cp_color};")

            self.invoice_label.setText(f"Invoice: {result.get('invoice_number', 'N/A')}")
            self.project_label.setText(f"Project: {result.get('project_number', 'N/A')}")
            self.items_label.setText(f"Items: {result.get('items_count', 0)} extracted")

            self.info_widget.show()
            self.error_label.hide()

            # Show items table
            items = result.get("items", [])
            if items:
                self._populate_table(items)
                self.items_table.show()
            else:
                self.items_table.hide()
        else:
            self.status_label.setText("Status: Failed")
            self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")

            self.error_label.setText(result.get("error", "Unknown error"))
            self.error_label.show()

            self.info_widget.hide()
            self.items_table.hide()

    def _populate_table(self, items: List[Dict]):
        """Populate the items table."""
        if not items:
            return

        # Get all unique keys
        keys = []
        for item in items:
            for k in item.keys():
                if k not in keys:
                    keys.append(k)

        self.items_table.setRowCount(len(items))
        self.items_table.setColumnCount(len(keys))
        self.items_table.setHorizontalHeaderLabels(keys)

        for row, item in enumerate(items):
            for col, key in enumerate(keys):
                value = str(item.get(key, ""))
                self.items_table.setItem(row, col, QTableWidgetItem(value))

        self.items_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def clear(self):
        """Clear all results."""
        self.status_label.setText("No test run yet")
        self.status_label.setStyleSheet("color: #888;")
        self.info_widget.hide()
        self.items_table.hide()
        self.error_label.hide()


class AgentChatDisplay(QScrollArea):
    """Enhanced chat display with tool result rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QScrollArea {
                background-color: #1e1e1e;
                border: none;
            }
        """)

        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        self.layout.addStretch()

        self.setWidget(self.container)

    def add_user_message(self, text: str):
        """Add a user message bubble."""
        msg_widget = QFrame()
        msg_widget.setStyleSheet("""
            QFrame {
                background-color: #0d6efd;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        layout = QVBoxLayout(msg_widget)
        layout.setContentsMargins(10, 8, 10, 8)

        label = QLabel(text)
        label.setStyleSheet("color: white;")
        label.setWordWrap(True)
        layout.addWidget(label)

        # Insert before the stretch
        self.layout.insertWidget(self.layout.count() - 1, msg_widget)
        self._scroll_to_bottom()

    def add_assistant_message(self, text: str):
        """Add an assistant message bubble."""
        if not text.strip():
            return

        msg_widget = QFrame()
        msg_widget.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        layout = QVBoxLayout(msg_widget)
        layout.setContentsMargins(10, 8, 10, 8)

        label = QLabel(text)
        label.setStyleSheet("color: #e0e0e0;")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.layout.insertWidget(self.layout.count() - 1, msg_widget)
        self._scroll_to_bottom()

    def add_tool_result(self, tool_name: str, tool_input: Dict, tool_result: Dict):
        """Add a tool result widget."""
        result_widget = ToolResultWidget(tool_name, tool_input, tool_result)
        self.layout.insertWidget(self.layout.count() - 1, result_widget)
        self._scroll_to_bottom()

    def add_system_message(self, text: str):
        """Add a system notification message."""
        msg_widget = QFrame()
        msg_widget.setStyleSheet("""
            QFrame {
                background-color: #3d3d3d;
                border-left: 3px solid #7eb6ff;
                padding: 5px 10px;
            }
        """)
        layout = QVBoxLayout(msg_widget)
        layout.setContentsMargins(10, 5, 10, 5)

        label = QLabel(text)
        label.setStyleSheet("color: #aaa; font-style: italic;")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.layout.insertWidget(self.layout.count() - 1, msg_widget)
        self._scroll_to_bottom()

    def clear(self):
        """Clear all messages."""
        while self.layout.count() > 1:  # Keep the stretch
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _scroll_to_bottom(self):
        """Scroll to the bottom of the chat."""
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
