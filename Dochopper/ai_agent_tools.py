"""
AI Agent Tools - Tool implementations for the Claude Code-like experience
Provides tools for reading templates, testing code, editing, and more.
"""

import os
import sys
import ast
import json
import traceback
import difflib
import tempfile
import importlib.util
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path


def get_templates_dir() -> Path:
    """Get the templates directory path."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        base = Path(sys._MEIPASS)
    else:
        # Running from source
        base = Path(__file__).parent

    return base / "templates"


def get_base_template_path() -> Path:
    """Get the base_template.py path."""
    return get_templates_dir() / "base_template.py"


class ToolRegistry:
    """Registry of all available tools."""

    def __init__(self):
        self._context = {}  # Shared context for tools

    def set_context(self, key: str, value: Any):
        """Set a context value that tools can access."""
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """Get a context value."""
        return self._context.get(key, default)

    def create_all_tools(self) -> Dict[str, Dict]:
        """Create all tool definitions and handlers."""
        tools = {}

        # Read Template Tool
        tools["read_template"] = {
            "definition": {
                "name": "read_template",
                "description": "Read the source code of an existing template file to learn patterns and structure",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template to read (e.g., 'sample_template', 'bill_of_lading')"
                        }
                    },
                    "required": ["template_name"]
                }
            },
            "handler": self._read_template
        }

        # Read Base Template Tool
        tools["read_base_template"] = {
            "definition": {
                "name": "read_base_template",
                "description": "Read the BaseTemplate class to understand the interface all templates must implement",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            "handler": self._read_base_template
        }

        # List Templates Tool
        tools["list_templates"] = {
            "definition": {
                "name": "list_templates",
                "description": "List all available templates with their metadata",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            "handler": self._list_templates
        }

        # Edit Template Tool
        tools["edit_template"] = {
            "definition": {
                "name": "edit_template",
                "description": "Edit the current template code. Use surgical edit for find/replace changes (set replace_all=true to replace ALL occurrences), full_rewrite for complete replacement.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "edit_type": {
                            "type": "string",
                            "enum": ["surgical", "full_rewrite"],
                            "description": "Type of edit: 'surgical' for find/replace, 'full_rewrite' for complete replacement"
                        },
                        "old_string": {
                            "type": "string",
                            "description": "For surgical edit: the exact text to find and replace"
                        },
                        "new_string": {
                            "type": "string",
                            "description": "For surgical edit: the text to replace with"
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "For surgical edit: if true, replace ALL occurrences; if false (default), replace only the first occurrence"
                        },
                        "full_content": {
                            "type": "string",
                            "description": "For full_rewrite: the complete new template code"
                        }
                    },
                    "required": ["edit_type"]
                }
            },
            "handler": self._edit_template
        }

        # Test Template Tool
        tools["test_template"] = {
            "definition": {
                "name": "test_template",
                "description": "Test the current template against the loaded invoice to verify extraction works correctly",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "template_code": {
                            "type": "string",
                            "description": "Optional: template code to test. If not provided, uses current editor code."
                        }
                    },
                    "required": []
                }
            },
            "handler": self._test_template
        }

        # Validate Syntax Tool
        tools["validate_syntax"] = {
            "definition": {
                "name": "validate_syntax",
                "description": "Check if Python code has valid syntax before applying changes",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "The Python code to validate"
                        }
                    },
                    "required": ["code"]
                }
            },
            "handler": self._validate_syntax
        }

        # Extract Invoice Text Tool
        tools["extract_invoice_text"] = {
            "definition": {
                "name": "extract_invoice_text",
                "description": "Get the full text content from the loaded invoice PDF",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pages": {
                            "type": "string",
                            "description": "Which pages to extract: 'all', '1-3', or '1,2,5'. Default is 'all'."
                        }
                    },
                    "required": []
                }
            },
            "handler": self._extract_invoice_text
        }

        # Query Database Tool
        tools["query_database"] = {
            "definition": {
                "name": "query_database",
                "description": "Query the parts_master or part_aliases database tables",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "enum": ["parts_master", "part_aliases"],
                            "description": "Which table to query"
                        },
                        "query_type": {
                            "type": "string",
                            "enum": ["search", "schema"],
                            "description": "'search' to find parts, 'schema' to see table structure"
                        },
                        "search_term": {
                            "type": "string",
                            "description": "For search: part number pattern to search for"
                        }
                    },
                    "required": ["table", "query_type"]
                }
            },
            "handler": self._query_database
        }

        # Read File Tool - Read any file from the local filesystem
        tools["read_file"] = {
            "definition": {
                "name": "read_file",
                "description": "Read the contents of a file from the local filesystem. Supports text files (csv, txt, json, xml, py, etc.) and can extract text from PDF files.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "The full path to the file to read (e.g., 'C:\\Users\\username\\Downloads\\OCRMill_Output\\invoice.csv')"
                        },
                        "max_lines": {
                            "type": "integer",
                            "description": "Maximum number of lines to read (default: 500). Use -1 for unlimited."
                        },
                        "encoding": {
                            "type": "string",
                            "description": "File encoding (default: 'utf-8'). Try 'latin-1' if utf-8 fails."
                        }
                    },
                    "required": ["file_path"]
                }
            },
            "handler": self._read_file
        }

        # List Directory Tool - List contents of a directory
        tools["list_directory"] = {
            "definition": {
                "name": "list_directory",
                "description": "List the contents of a directory on the local filesystem. Shows files and subdirectories with their sizes and modification times.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "directory_path": {
                            "type": "string",
                            "description": "The full path to the directory to list (e.g., 'C:\\Users\\username\\Downloads\\OCRMill_Output')"
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Optional glob pattern to filter files (e.g., '*.csv', '*.pdf'). Default shows all files."
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "If true, list files in subdirectories too. Default is false."
                        }
                    },
                    "required": ["directory_path"]
                }
            },
            "handler": self._list_directory
        }

        return tools

    def _read_template(self, template_name: str) -> Dict[str, Any]:
        """Read a template file's source code."""
        templates_dir = get_templates_dir()

        # Try with .py extension
        template_path = templates_dir / f"{template_name}.py"
        if not template_path.exists():
            # Try without modification
            template_path = templates_dir / template_name
            if not template_path.exists():
                return {
                    "success": False,
                    "error": f"Template not found: {template_name}",
                    "available": self._get_template_names()
                }

        try:
            content = template_path.read_text(encoding='utf-8')
            return {
                "success": True,
                "template_name": template_name,
                "file_path": str(template_path),
                "content": content,
                "line_count": len(content.splitlines())
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error reading template: {str(e)}"
            }

    def _read_base_template(self) -> Dict[str, Any]:
        """Read the BaseTemplate class source."""
        base_path = get_base_template_path()

        if not base_path.exists():
            return {
                "success": False,
                "error": "BaseTemplate file not found"
            }

        try:
            content = base_path.read_text(encoding='utf-8')
            return {
                "success": True,
                "file_path": str(base_path),
                "content": content,
                "line_count": len(content.splitlines())
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error reading base template: {str(e)}"
            }

    def _get_template_names(self) -> List[str]:
        """Get list of template file names."""
        templates_dir = get_templates_dir()
        if not templates_dir.exists():
            return []

        names = []
        for f in templates_dir.glob("*.py"):
            if f.name not in ("__init__.py", "base_template.py"):
                names.append(f.stem)
        return sorted(names)

    def _list_templates(self) -> Dict[str, Any]:
        """List all available templates."""
        templates_dir = get_templates_dir()
        templates = []

        for name in self._get_template_names():
            template_path = templates_dir / f"{name}.py"
            try:
                content = template_path.read_text(encoding='utf-8')

                # Extract metadata from source
                metadata = {
                    "name": name,
                    "file_name": f"{name}.py",
                    "description": "",
                    "client": "",
                    "enabled": True
                }

                # Parse for class attributes
                for line in content.splitlines():
                    if 'description' in line and '=' in line and 'str' not in line:
                        try:
                            val = line.split('=', 1)[1].strip().strip('"\'')
                            metadata["description"] = val
                        except:
                            pass
                    elif 'client' in line and '=' in line and 'str' not in line:
                        try:
                            val = line.split('=', 1)[1].strip().strip('"\'')
                            metadata["client"] = val
                        except:
                            pass
                    elif 'enabled' in line and '=' in line:
                        metadata["enabled"] = 'True' in line or 'true' in line

                templates.append(metadata)
            except:
                templates.append({
                    "name": name,
                    "file_name": f"{name}.py",
                    "error": "Could not parse metadata"
                })

        return {
            "success": True,
            "count": len(templates),
            "templates": templates
        }

    def _edit_template(self, edit_type: str, old_string: str = None,
                       new_string: str = None, replace_all: bool = False,
                       full_content: str = None) -> Dict[str, Any]:
        """Edit the current template code."""
        import logging
        logger = logging.getLogger(__name__)

        current_code = self.get_context("current_template_code", "")
        set_code_callback = self.get_context("set_template_code_callback")

        if edit_type == "surgical":
            if not old_string:
                return {"success": False, "error": "old_string is required for surgical edit"}
            if new_string is None:
                return {"success": False, "error": "new_string is required for surgical edit"}

            if old_string not in current_code:
                return {
                    "success": False,
                    "error": "old_string not found in current code",
                    "hint": "Make sure old_string matches exactly, including whitespace"
                }

            # Count occurrences
            count = current_code.count(old_string)

            # Replace based on replace_all flag
            if replace_all:
                new_code = current_code.replace(old_string, new_string)
                replaced_count = count
            else:
                new_code = current_code.replace(old_string, new_string, 1)
                replaced_count = 1

            # Generate diff
            diff = list(difflib.unified_diff(
                current_code.splitlines(keepends=True),
                new_code.splitlines(keepends=True),
                fromfile="before",
                tofile="after",
                lineterm=""
            ))

            if set_code_callback:
                try:
                    set_code_callback(new_code)
                except Exception as e:
                    logger.error(f"  set_code_callback failed: {e}")
            self.set_context("current_template_code", new_code)

            return {
                "success": True,
                "edit_type": "surgical",
                "occurrences_found": count,
                "replaced": replaced_count,
                "replace_all": replace_all,
                "diff": "".join(diff),
                "new_line_count": len(new_code.splitlines())
            }

        elif edit_type == "full_rewrite":
            if not full_content:
                return {"success": False, "error": "full_content is required for full_rewrite"}

            # Validate syntax first
            syntax_result = self._validate_syntax(full_content)
            if not syntax_result["valid"]:
                return {
                    "success": False,
                    "error": "Syntax error in new code",
                    "syntax_error": syntax_result
                }

            # Generate diff
            diff = list(difflib.unified_diff(
                current_code.splitlines(keepends=True),
                full_content.splitlines(keepends=True),
                fromfile="before",
                tofile="after",
                lineterm=""
            ))

            if set_code_callback:
                try:
                    set_code_callback(full_content)
                except Exception as e:
                    logger.error(f"  full_rewrite: set_code_callback failed: {e}")
            self.set_context("current_template_code", full_content)

            return {
                "success": True,
                "edit_type": "full_rewrite",
                "diff": "".join(diff),
                "old_line_count": len(current_code.splitlines()),
                "new_line_count": len(full_content.splitlines())
            }

        else:
            return {"success": False, "error": f"Unknown edit_type: {edit_type}"}

    def _test_template(self, template_code: str = None) -> Dict[str, Any]:
        """Test a template against the loaded invoice."""
        code = template_code or self.get_context("current_template_code", "")
        invoice_text = self.get_context("invoice_text", "")
        invoice_tables = self.get_context("invoice_tables", [])

        if not code:
            return {"success": False, "error": "No template code to test"}
        if not invoice_text:
            return {"success": False, "error": "No invoice loaded. Please load an invoice PDF first."}

        # Validate syntax first
        syntax_result = self._validate_syntax(code)
        if not syntax_result["valid"]:
            return {
                "success": False,
                "error": "Syntax error in template code",
                "syntax_error": syntax_result
            }

        try:
            # Create a temporary module to execute the template
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                f.write(code)
                temp_path = f.name

            try:
                # Import the template module
                spec = importlib.util.spec_from_file_location("test_template", temp_path)
                module = importlib.util.module_from_spec(spec)

                # Need to add parent imports for BaseTemplate
                templates_dir = get_templates_dir()
                if str(templates_dir.parent) not in sys.path:
                    sys.path.insert(0, str(templates_dir.parent))

                spec.loader.exec_module(module)

                # Find the template class (should inherit from BaseTemplate)
                template_class = None
                for name, obj in vars(module).items():
                    if isinstance(obj, type) and name != "BaseTemplate":
                        # Check if it has the required methods
                        if hasattr(obj, 'can_process') and hasattr(obj, 'extract_line_items'):
                            template_class = obj
                            break

                if not template_class:
                    return {
                        "success": False,
                        "error": "No valid template class found in code. Must inherit from BaseTemplate."
                    }

                # Instantiate and test
                template = template_class()

                # Test can_process
                can_process = template.can_process(invoice_text)

                # Extract data
                invoice_number = template.extract_invoice_number(invoice_text)
                project_number = template.extract_project_number(invoice_text)

                # Try table-based extraction if available
                if invoice_tables and hasattr(template, 'extract_from_tables'):
                    items = template.extract_from_tables(invoice_tables, invoice_text)
                    if not items:
                        items = template.extract_line_items(invoice_text)
                else:
                    items = template.extract_line_items(invoice_text)

                # Post-process items if method exists
                if hasattr(template, 'post_process_items'):
                    items = template.post_process_items(items)

                return {
                    "success": True,
                    "can_process": can_process,
                    "invoice_number": invoice_number,
                    "project_number": project_number,
                    "items_count": len(items),
                    "items": items[:20],  # Limit to first 20 items
                    "items_truncated": len(items) > 20,
                    "template_name": getattr(template, 'name', 'Unknown'),
                    "template_client": getattr(template, 'client', 'Unknown')
                }

            finally:
                # Cleanup temp file
                try:
                    os.unlink(temp_path)
                except:
                    pass

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    def _validate_syntax(self, code: str) -> Dict[str, Any]:
        """Validate Python syntax."""
        try:
            ast.parse(code)
            return {"valid": True}
        except SyntaxError as e:
            return {
                "valid": False,
                "error_line": e.lineno,
                "error_offset": e.offset,
                "error_message": str(e.msg),
                "error_text": e.text.strip() if e.text else ""
            }

    def _extract_invoice_text(self, pages: str = "all") -> Dict[str, Any]:
        """Extract text from the loaded invoice."""
        invoice_text = self.get_context("invoice_text", "")
        invoice_path = self.get_context("invoice_path", "")
        page_texts = self.get_context("invoice_page_texts", [])

        if not invoice_text:
            return {
                "success": False,
                "error": "No invoice loaded. Please load an invoice PDF first."
            }

        # If we have page-level text and specific pages requested
        if page_texts and pages != "all":
            try:
                selected_text = []
                total_pages = len(page_texts)

                if "-" in pages:
                    # Range: "1-3"
                    start, end = map(int, pages.split("-"))
                    for i in range(start - 1, min(end, total_pages)):
                        selected_text.append(f"--- Page {i + 1} ---\n{page_texts[i]}")
                elif "," in pages:
                    # List: "1,2,5"
                    for p in pages.split(","):
                        idx = int(p.strip()) - 1
                        if 0 <= idx < total_pages:
                            selected_text.append(f"--- Page {idx + 1} ---\n{page_texts[idx]}")
                else:
                    # Single page
                    idx = int(pages) - 1
                    if 0 <= idx < total_pages:
                        selected_text.append(page_texts[idx])

                return {
                    "success": True,
                    "file_path": invoice_path,
                    "pages_requested": pages,
                    "page_count": total_pages,
                    "text": "\n\n".join(selected_text),
                    "character_count": sum(len(t) for t in selected_text)
                }
            except:
                pass  # Fall through to return all text

        return {
            "success": True,
            "file_path": invoice_path,
            "pages_requested": "all",
            "page_count": len(page_texts) if page_texts else 1,
            "text": invoice_text,
            "character_count": len(invoice_text)
        }

    # Whitelist of tables the AI agent is allowed to query
    _ALLOWED_TABLES = frozenset({
        'parts_master', 'mid_table', 'hts_units', 'tariff_232',
        'tariff_301', 'tariff_122', 'country_codes', 'cbp_uom_codes',
        'part_number_corrections',
    })

    def _query_database(self, table: str, query_type: str,
                        search_term: str = None) -> Dict[str, Any]:
        """Query the parts database."""
        db_connection = self.get_context("db_connection")

        if not db_connection:
            return {
                "success": False,
                "error": "Database connection not available"
            }

        # Validate table name against whitelist to prevent SQL injection
        if table not in self._ALLOWED_TABLES:
            return {
                "success": False,
                "error": f"Table '{table}' not allowed. Allowed tables: {', '.join(sorted(self._ALLOWED_TABLES))}"
            }

        try:
            cursor = db_connection.cursor()

            if query_type == "schema":
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()
                return {
                    "success": True,
                    "table": table,
                    "columns": [
                        {"name": col[1], "type": col[2], "nullable": not col[3], "primary_key": col[5] == 1}
                        for col in columns
                    ]
                }

            elif query_type == "search":
                if not search_term:
                    return {"success": False, "error": "search_term is required for search query_type"}

                # Search by part number pattern
                query = f"SELECT * FROM {table} WHERE part_number LIKE ? LIMIT 20"
                cursor.execute(query, (f"%{search_term}%",))
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]

                return {
                    "success": True,
                    "table": table,
                    "search_term": search_term,
                    "count": len(rows),
                    "results": [dict(zip(columns, row)) for row in rows],
                    "truncated": len(rows) >= 20
                }

            else:
                return {"success": False, "error": f"Unknown query_type: {query_type}"}

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    def _read_file(self, file_path: str, max_lines: int = 500,
                   encoding: str = "utf-8") -> Dict[str, Any]:
        """Read contents of a file from the local filesystem."""
        from datetime import datetime

        file_path = Path(file_path)

        if not file_path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}"
            }

        if not file_path.is_file():
            return {
                "success": False,
                "error": f"Path is not a file: {file_path}"
            }

        # Get file info
        stat = file_path.stat()
        file_info = {
            "name": file_path.name,
            "path": str(file_path),
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "extension": file_path.suffix.lower()
        }

        # Handle PDF files specially
        if file_path.suffix.lower() == '.pdf':
            try:
                import pdfplumber
                text_parts = []
                with pdfplumber.open(file_path) as pdf:
                    for i, page in enumerate(pdf.pages[:20]):  # Limit to 20 pages
                        page_text = page.extract_text()
                        if page_text:
                            text_parts.append(f"[Page {i+1}]\n{page_text}")
                content = "\n\n".join(text_parts)
                return {
                    "success": True,
                    "file_info": file_info,
                    "content_type": "pdf_extracted_text",
                    "page_count": len(text_parts),
                    "content": content,
                    "character_count": len(content)
                }
            except ImportError:
                return {
                    "success": False,
                    "error": "pdfplumber not installed - cannot read PDF files"
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error reading PDF: {str(e)}"
                }

        # Handle text files
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                if max_lines == -1:
                    content = f.read()
                    line_count = content.count('\n') + 1
                else:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= max_lines:
                            break
                        lines.append(line)
                    content = ''.join(lines)
                    line_count = len(lines)

            return {
                "success": True,
                "file_info": file_info,
                "content_type": "text",
                "line_count": line_count,
                "truncated": max_lines != -1 and line_count >= max_lines,
                "content": content,
                "character_count": len(content)
            }

        except UnicodeDecodeError:
            # Try latin-1 as fallback
            try:
                with open(file_path, 'r', encoding='latin-1') as f:
                    if max_lines == -1:
                        content = f.read()
                    else:
                        lines = [next(f) for _ in range(max_lines) if f]
                        content = ''.join(lines)
                return {
                    "success": True,
                    "file_info": file_info,
                    "content_type": "text",
                    "encoding_used": "latin-1",
                    "content": content,
                    "character_count": len(content)
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to decode file: {str(e)}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error reading file: {str(e)}",
                "traceback": traceback.format_exc()
            }

    def _list_directory(self, directory_path: str, pattern: str = None,
                        recursive: bool = False) -> Dict[str, Any]:
        """List contents of a directory."""
        from datetime import datetime

        dir_path = Path(directory_path)

        if not dir_path.exists():
            return {
                "success": False,
                "error": f"Directory not found: {directory_path}"
            }

        if not dir_path.is_dir():
            return {
                "success": False,
                "error": f"Path is not a directory: {directory_path}"
            }

        try:
            files = []
            directories = []

            # Get items based on pattern and recursive flag
            if pattern:
                if recursive:
                    items = list(dir_path.rglob(pattern))
                else:
                    items = list(dir_path.glob(pattern))
            else:
                if recursive:
                    items = list(dir_path.rglob("*"))
                else:
                    items = list(dir_path.iterdir())

            for item in items[:100]:  # Limit to 100 items
                try:
                    stat = item.stat()
                    item_info = {
                        "name": item.name,
                        "path": str(item),
                        "size_bytes": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    }
                    if item.is_dir():
                        item_info["type"] = "directory"
                        directories.append(item_info)
                    else:
                        item_info["type"] = "file"
                        item_info["extension"] = item.suffix.lower()
                        files.append(item_info)
                except (PermissionError, OSError):
                    continue

            # Sort by modification time (newest first)
            files.sort(key=lambda x: x["modified"], reverse=True)
            directories.sort(key=lambda x: x["name"])

            return {
                "success": True,
                "directory": str(dir_path),
                "pattern": pattern,
                "recursive": recursive,
                "total_items": len(files) + len(directories),
                "truncated": len(items) > 100,
                "directories": directories,
                "files": files
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error listing directory: {str(e)}",
                "traceback": traceback.format_exc()
            }


def register_all_tools(tool_executor, tool_registry: ToolRegistry):
    """Register all tools with the tool executor."""
    tools = tool_registry.create_all_tools()

    for name, tool_info in tools.items():
        tool_executor.register_tool(
            name=tool_info["definition"]["name"],
            description=tool_info["definition"]["description"],
            input_schema=tool_info["definition"]["input_schema"],
            handler=tool_info["handler"]
        )
