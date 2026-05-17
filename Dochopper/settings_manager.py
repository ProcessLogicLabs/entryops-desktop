"""
Unified Settings Manager for DocHopper

Consolidates all application settings into a single manager:
- AI Provider settings (API keys, models) - stored in database (encrypted)
- PDF Processing settings (folders, intervals) - stored in database
- User Preferences (window sizes, themes) - stored in registry for portability

Author: DocHopper Team
"""

import sqlite3
import json
import base64
import os
from pathlib import Path
from typing import Any, Optional, Dict, List
from dataclasses import dataclass, field, asdict
from enum import Enum

try:
    from PyQt5.QtCore import QSettings
except ImportError:
    QSettings = None

import logging
logger = logging.getLogger(__name__)


class SettingsCategory(Enum):
    """Categories of settings for organization."""
    AI = "ai"
    PDF_PROCESSING = "pdf"
    USER_PREFERENCES = "user"
    APPLICATION = "app"


@dataclass
class AISettings:
    """AI Provider configuration settings."""
    # API Keys (stored encrypted)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # Default models per provider
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"
    gemini_model: str = "gemini-1.5-pro"
    groq_model: str = "llama-3.1-70b-versatile"

    # Default provider
    default_provider: str = "anthropic"


@dataclass
class PDFProcessingSettings:
    """PDF/OCRMill processing configuration."""
    input_folder: str = ""
    output_folder: str = ""
    poll_interval: int = 60
    consolidate_multi_invoice: bool = False
    auto_start_monitoring: bool = False

    # Template settings (template_name -> enabled)
    template_settings: Dict[str, bool] = field(default_factory=dict)


@dataclass
class UserPreferences:
    """User interface preferences (stored in registry for portability)."""
    theme: str = "Muted Cyan"
    font_size: int = 9
    preview_row_height: int = 22
    excel_viewer: str = "System Default"
    show_division_selector: bool = True
    check_updates_on_startup: bool = True

    # Colors
    output_font_color: str = "#000000"

    # Window state
    invoice_splitter_sizes: str = ""
    pdf_splitter_sizes: str = ""
    column_widths: str = ""

    # Last used folders
    input_folder: str = ""
    output_folder: str = ""


class SettingsManager:
    """
    Unified settings manager for DocHopper application.

    Provides consistent access to all application settings with:
    - Type-safe access via dataclasses
    - Automatic persistence to appropriate storage
    - Migration support from legacy settings
    - Encryption for sensitive data (API keys)
    """

    def __init__(self, db_path: Path, base_dir: Path = None):
        """
        Initialize the settings manager.

        Args:
            db_path: Path to the SQLite database
            base_dir: Base directory for default folder paths
        """
        self.db_path = db_path
        self.base_dir = base_dir or db_path.parent

        # Initialize settings objects
        self._ai_settings: Optional[AISettings] = None
        self._pdf_settings: Optional[PDFProcessingSettings] = None
        self._user_prefs: Optional[UserPreferences] = None

        # Ensure database table exists
        self._ensure_settings_table()

        # Load settings
        self._load_all_settings()

    def _ensure_settings_table(self):
        """Ensure the settings table exists in the database."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    value_type TEXT DEFAULT 'string',
                    PRIMARY KEY (category, key)
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to create settings table: {e}")

    # =========================================================================
    # AI Settings
    # =========================================================================

    @property
    def ai(self) -> AISettings:
        """Get AI settings."""
        if self._ai_settings is None:
            self._ai_settings = self._load_ai_settings()
        return self._ai_settings

    def save_ai_settings(self, settings: AISettings = None):
        """Save AI settings to database."""
        if settings:
            self._ai_settings = settings
        self._save_ai_settings(self._ai_settings)

    def _load_ai_settings(self) -> AISettings:
        """Load AI settings from database."""
        settings = AISettings()

        # Set default folders
        settings.anthropic_api_key = self._get_db_setting(SettingsCategory.AI, 'anthropic_api_key', '', encrypted=True)
        settings.openai_api_key = self._get_db_setting(SettingsCategory.AI, 'openai_api_key', '', encrypted=True)
        settings.gemini_api_key = self._get_db_setting(SettingsCategory.AI, 'gemini_api_key', '', encrypted=True)
        settings.groq_api_key = self._get_db_setting(SettingsCategory.AI, 'groq_api_key', '', encrypted=True)

        settings.anthropic_model = self._get_db_setting(SettingsCategory.AI, 'anthropic_model', settings.anthropic_model)
        settings.openai_model = self._get_db_setting(SettingsCategory.AI, 'openai_model', settings.openai_model)
        settings.gemini_model = self._get_db_setting(SettingsCategory.AI, 'gemini_model', settings.gemini_model)
        settings.groq_model = self._get_db_setting(SettingsCategory.AI, 'groq_model', settings.groq_model)

        settings.default_provider = self._get_db_setting(SettingsCategory.AI, 'default_provider', settings.default_provider)

        return settings

    def _save_ai_settings(self, settings: AISettings):
        """Save AI settings to database."""
        self._set_db_setting(SettingsCategory.AI, 'anthropic_api_key', settings.anthropic_api_key, encrypted=True)
        self._set_db_setting(SettingsCategory.AI, 'openai_api_key', settings.openai_api_key, encrypted=True)
        self._set_db_setting(SettingsCategory.AI, 'gemini_api_key', settings.gemini_api_key, encrypted=True)
        self._set_db_setting(SettingsCategory.AI, 'groq_api_key', settings.groq_api_key, encrypted=True)

        self._set_db_setting(SettingsCategory.AI, 'anthropic_model', settings.anthropic_model)
        self._set_db_setting(SettingsCategory.AI, 'openai_model', settings.openai_model)
        self._set_db_setting(SettingsCategory.AI, 'gemini_model', settings.gemini_model)
        self._set_db_setting(SettingsCategory.AI, 'groq_model', settings.groq_model)

        self._set_db_setting(SettingsCategory.AI, 'default_provider', settings.default_provider)

    def get_ai_api_key(self, provider: str) -> str:
        """Get API key for a specific provider."""
        key_map = {
            'anthropic': self.ai.anthropic_api_key,
            'openai': self.ai.openai_api_key,
            'gemini': self.ai.gemini_api_key,
            'groq': self.ai.groq_api_key,
        }
        return key_map.get(provider.lower(), '')

    def set_ai_api_key(self, provider: str, api_key: str):
        """Set API key for a specific provider."""
        provider = provider.lower()
        if provider == 'anthropic':
            self._ai_settings.anthropic_api_key = api_key
        elif provider == 'openai':
            self._ai_settings.openai_api_key = api_key
        elif provider == 'gemini':
            self._ai_settings.gemini_api_key = api_key
        elif provider == 'groq':
            self._ai_settings.groq_api_key = api_key
        self._set_db_setting(SettingsCategory.AI, f'{provider}_api_key', api_key, encrypted=True)

    def get_ai_model(self, provider: str) -> str:
        """Get default model for a specific provider."""
        model_map = {
            'anthropic': self.ai.anthropic_model,
            'openai': self.ai.openai_model,
            'gemini': self.ai.gemini_model,
            'groq': self.ai.groq_model,
        }
        return model_map.get(provider.lower(), '')

    def set_ai_model(self, provider: str, model: str):
        """Set default model for a specific provider."""
        provider = provider.lower()
        if provider == 'anthropic':
            self._ai_settings.anthropic_model = model
        elif provider == 'openai':
            self._ai_settings.openai_model = model
        elif provider == 'gemini':
            self._ai_settings.gemini_model = model
        elif provider == 'groq':
            self._ai_settings.groq_model = model
        self._set_db_setting(SettingsCategory.AI, f'{provider}_model', model)

    # =========================================================================
    # PDF Processing Settings
    # =========================================================================

    @property
    def pdf(self) -> PDFProcessingSettings:
        """Get PDF processing settings."""
        if self._pdf_settings is None:
            self._pdf_settings = self._load_pdf_settings()
        return self._pdf_settings

    def save_pdf_settings(self, settings: PDFProcessingSettings = None):
        """Save PDF processing settings to database."""
        if settings:
            self._pdf_settings = settings
        self._save_pdf_settings(self._pdf_settings)

    def _load_pdf_settings(self) -> PDFProcessingSettings:
        """Load PDF processing settings from database."""
        settings = PDFProcessingSettings()

        # Set default folders based on base_dir
        default_input = str(self.base_dir / "OCR_Input")
        default_output = str(self.base_dir / "OCR_Output")

        settings.input_folder = self._get_db_setting(SettingsCategory.PDF_PROCESSING, 'input_folder', default_input)
        settings.output_folder = self._get_db_setting(SettingsCategory.PDF_PROCESSING, 'output_folder', default_output)
        settings.poll_interval = int(self._get_db_setting(SettingsCategory.PDF_PROCESSING, 'poll_interval', '60'))
        settings.consolidate_multi_invoice = self._get_db_setting(SettingsCategory.PDF_PROCESSING, 'consolidate_multi_invoice', 'false').lower() == 'true'
        settings.auto_start_monitoring = self._get_db_setting(SettingsCategory.PDF_PROCESSING, 'auto_start_monitoring', 'false').lower() == 'true'

        # Load template settings
        template_json = self._get_db_setting(SettingsCategory.PDF_PROCESSING, 'template_settings', '{}')
        try:
            settings.template_settings = json.loads(template_json)
        except json.JSONDecodeError:
            settings.template_settings = {}

        return settings

    def _save_pdf_settings(self, settings: PDFProcessingSettings):
        """Save PDF processing settings to database."""
        self._set_db_setting(SettingsCategory.PDF_PROCESSING, 'input_folder', settings.input_folder)
        self._set_db_setting(SettingsCategory.PDF_PROCESSING, 'output_folder', settings.output_folder)
        self._set_db_setting(SettingsCategory.PDF_PROCESSING, 'poll_interval', str(settings.poll_interval))
        self._set_db_setting(SettingsCategory.PDF_PROCESSING, 'consolidate_multi_invoice', str(settings.consolidate_multi_invoice).lower())
        self._set_db_setting(SettingsCategory.PDF_PROCESSING, 'auto_start_monitoring', str(settings.auto_start_monitoring).lower())
        self._set_db_setting(SettingsCategory.PDF_PROCESSING, 'template_settings', json.dumps(settings.template_settings))

    def get_template_enabled(self, template_name: str) -> bool:
        """Check if a template is enabled."""
        return self.pdf.template_settings.get(template_name, True)

    def set_template_enabled(self, template_name: str, enabled: bool):
        """Set template enabled state."""
        self._pdf_settings.template_settings[template_name] = enabled
        self._set_db_setting(SettingsCategory.PDF_PROCESSING, 'template_settings',
                           json.dumps(self._pdf_settings.template_settings))

    # =========================================================================
    # User Preferences (Registry-based for portability)
    # =========================================================================

    @property
    def user(self) -> UserPreferences:
        """Get user preferences."""
        if self._user_prefs is None:
            self._user_prefs = self._load_user_preferences()
        return self._user_prefs

    def save_user_preferences(self, prefs: UserPreferences = None):
        """Save user preferences to registry."""
        if prefs:
            self._user_prefs = prefs
        self._save_user_preferences(self._user_prefs)

    def _get_qsettings(self) -> 'QSettings':
        """Get QSettings instance."""
        if QSettings is None:
            raise ImportError("PyQt5 QSettings not available")
        return QSettings("DocHopper", "DocHopper")

    def _load_user_preferences(self) -> UserPreferences:
        """Load user preferences from registry."""
        prefs = UserPreferences()

        try:
            settings = self._get_qsettings()

            prefs.theme = settings.value('theme', prefs.theme)
            prefs.font_size = int(settings.value('font_size', prefs.font_size))
            prefs.preview_row_height = int(settings.value('preview_row_height', prefs.preview_row_height))
            prefs.excel_viewer = settings.value('excel_viewer', prefs.excel_viewer)
            prefs.show_division_selector = settings.value('show_division_selector', 'true').lower() == 'true'
            prefs.check_updates_on_startup = settings.value('check_updates_on_startup', 'true').lower() == 'true'
            prefs.output_font_color = settings.value('output_font_color', prefs.output_font_color)
            prefs.invoice_splitter_sizes = settings.value('invoice_splitter_sizes', '')
            prefs.pdf_splitter_sizes = settings.value('pdf_splitter_sizes', '')
            prefs.column_widths = settings.value('column_widths', '')
            prefs.input_folder = settings.value('input_folder', '')
            prefs.output_folder = settings.value('output_folder', '')

        except Exception as e:
            logger.warning(f"Failed to load user preferences from registry: {e}")

        return prefs

    def _save_user_preferences(self, prefs: UserPreferences):
        """Save user preferences to registry."""
        try:
            settings = self._get_qsettings()

            settings.setValue('theme', prefs.theme)
            settings.setValue('font_size', prefs.font_size)
            settings.setValue('preview_row_height', prefs.preview_row_height)
            settings.setValue('excel_viewer', prefs.excel_viewer)
            settings.setValue('show_division_selector', str(prefs.show_division_selector).lower())
            settings.setValue('check_updates_on_startup', str(prefs.check_updates_on_startup).lower())
            settings.setValue('output_font_color', prefs.output_font_color)
            settings.setValue('invoice_splitter_sizes', prefs.invoice_splitter_sizes)
            settings.setValue('pdf_splitter_sizes', prefs.pdf_splitter_sizes)
            settings.setValue('column_widths', prefs.column_widths)
            settings.setValue('input_folder', prefs.input_folder)
            settings.setValue('output_folder', prefs.output_folder)

        except Exception as e:
            logger.error(f"Failed to save user preferences to registry: {e}")

    def get_user_setting(self, key: str, default: Any = None) -> Any:
        """Get a single user preference by key."""
        try:
            settings = self._get_qsettings()
            return settings.value(key, default)
        except Exception:
            return default

    def set_user_setting(self, key: str, value: Any):
        """Set a single user preference by key."""
        try:
            settings = self._get_qsettings()
            settings.setValue(key, value)
        except Exception as e:
            logger.error(f"Failed to set user setting {key}: {e}")

    def get_user_setting_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean user preference."""
        value = self.get_user_setting(key, str(default).lower())
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes')

    def get_user_setting_int(self, key: str, default: int = 0) -> int:
        """Get an integer user preference."""
        try:
            return int(self.get_user_setting(key, default))
        except (ValueError, TypeError):
            return default

    def get_user_setting_float(self, key: str, default: float = 0.0) -> float:
        """Get a float user preference."""
        try:
            return float(self.get_user_setting(key, default))
        except (ValueError, TypeError):
            return default

    # =========================================================================
    # Database Helpers
    # =========================================================================

    def _get_db_setting(self, category: SettingsCategory, key: str, default: str = '', encrypted: bool = False) -> str:
        """Get a setting from the database."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute(
                "SELECT value FROM app_settings WHERE category = ? AND key = ?",
                (category.value, key)
            )
            row = c.fetchone()
            conn.close()

            if row and row[0]:
                value = row[0]
                if encrypted:
                    value = self._decrypt(value)
                return value
            return default
        except Exception as e:
            logger.error(f"Failed to get setting {category.value}.{key}: {e}")
            return default

    def _set_db_setting(self, category: SettingsCategory, key: str, value: str, encrypted: bool = False):
        """Set a setting in the database."""
        try:
            if encrypted and value:
                value = self._encrypt(value)

            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO app_settings (category, key, value, value_type)
                VALUES (?, ?, ?, ?)
            """, (category.value, key, value, 'encrypted' if encrypted else 'string'))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to set setting {category.value}.{key}: {e}")

    def _load_all_settings(self):
        """Load all settings from storage."""
        self._ai_settings = self._load_ai_settings()
        self._pdf_settings = self._load_pdf_settings()
        self._user_prefs = self._load_user_preferences()

    # =========================================================================
    # Encryption (Basic obfuscation - not cryptographically secure)
    # =========================================================================

    def _get_encryption_key(self) -> bytes:
        """Get machine-specific encryption key."""
        # Use a combination of factors for basic obfuscation
        # This is NOT cryptographically secure, just prevents casual viewing
        import hashlib
        machine_id = os.environ.get('COMPUTERNAME', '') + os.environ.get('USERNAME', '')
        return hashlib.sha256(machine_id.encode()).digest()[:16]

    def _encrypt(self, value: str) -> str:
        """Encrypt a value (basic obfuscation)."""
        if not value:
            return value
        try:
            key = self._get_encryption_key()
            # Simple XOR encryption with base64 encoding
            encrypted = bytes(a ^ b for a, b in zip(value.encode(), key * (len(value) // len(key) + 1)))
            return base64.b64encode(encrypted).decode()
        except Exception:
            return value

    def _decrypt(self, value: str) -> str:
        """Decrypt a value (basic obfuscation)."""
        if not value:
            return value
        try:
            key = self._get_encryption_key()
            encrypted = base64.b64decode(value.encode())
            decrypted = bytes(a ^ b for a, b in zip(encrypted, key * (len(encrypted) // len(key) + 1)))
            return decrypted.decode()
        except Exception:
            # If decryption fails, return as-is (might be legacy unencrypted value)
            return value

    # =========================================================================
    # Migration from Legacy Settings
    # =========================================================================

    def migrate_from_legacy(self):
        """
        Migrate settings from legacy storage locations.
        Call this once during application startup to migrate old settings.
        """
        self._migrate_legacy_ai_settings()
        self._migrate_legacy_pdf_settings()
        logger.info("Legacy settings migration completed")

    def _migrate_legacy_ai_settings(self):
        """Migrate AI settings from old app_config table format."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()

            # Check for legacy AI settings in app_config
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='app_config'")
            if not c.fetchone():
                conn.close()
                return

            # Migrate API keys
            legacy_keys = {
                'api_key_anthropic': ('anthropic_api_key', True),
                'api_key_openai': ('openai_api_key', True),
                'api_key_gemini': ('gemini_api_key', True),
                'api_key_groq': ('groq_api_key', True),
                'ai_anthropic_default_model': ('anthropic_model', False),
                'ai_openai_default_model': ('openai_model', False),
                'ai_gemini_default_model': ('gemini_model', False),
                'ai_groq_default_model': ('groq_model', False),
                'ai_default_provider': ('default_provider', False),
            }

            for old_key, (new_key, encrypted) in legacy_keys.items():
                c.execute("SELECT value FROM app_config WHERE key = ?", (old_key,))
                row = c.fetchone()
                if row and row[0]:
                    # Only migrate if not already in new table
                    existing = self._get_db_setting(SettingsCategory.AI, new_key, '')
                    if not existing:
                        self._set_db_setting(SettingsCategory.AI, new_key, row[0], encrypted=encrypted)
                        logger.info(f"Migrated AI setting: {old_key} -> {new_key}")

            conn.close()
        except Exception as e:
            logger.error(f"Failed to migrate legacy AI settings: {e}")

    def _migrate_legacy_pdf_settings(self):
        """Migrate PDF/OCRMill settings from registry to database."""
        try:
            settings = self._get_qsettings()

            # Check for legacy OCRMill settings in registry
            legacy_keys = {
                'ocrmill_input_folder': 'input_folder',
                'ocrmill_output_folder': 'output_folder',
                'ocrmill_poll_interval': 'poll_interval',
                'ocrmill_consolidate': 'consolidate_multi_invoice',
                'ocrmill_autostart': 'auto_start_monitoring',
            }

            for old_key, new_key in legacy_keys.items():
                value = settings.value(old_key, None)
                if value is not None:
                    # Only migrate if not already in new storage
                    existing = self._get_db_setting(SettingsCategory.PDF_PROCESSING, new_key, '')
                    if not existing:
                        self._set_db_setting(SettingsCategory.PDF_PROCESSING, new_key, str(value))
                        logger.info(f"Migrated PDF setting: {old_key} -> {new_key}")

        except Exception as e:
            logger.error(f"Failed to migrate legacy PDF settings: {e}")

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def export_settings(self) -> Dict:
        """Export all settings as a dictionary (for backup/debug)."""
        return {
            'ai': asdict(self.ai),
            'pdf': asdict(self.pdf),
            'user': asdict(self.user),
        }

    def reset_to_defaults(self, category: SettingsCategory = None):
        """Reset settings to defaults."""
        if category is None or category == SettingsCategory.AI:
            self._ai_settings = AISettings()
            self._save_ai_settings(self._ai_settings)

        if category is None or category == SettingsCategory.PDF_PROCESSING:
            self._pdf_settings = PDFProcessingSettings()
            self._pdf_settings.input_folder = str(self.base_dir / "OCR_Input")
            self._pdf_settings.output_folder = str(self.base_dir / "OCR_Output")
            self._save_pdf_settings(self._pdf_settings)

        if category is None or category == SettingsCategory.USER_PREFERENCES:
            self._user_prefs = UserPreferences()
            self._save_user_preferences(self._user_prefs)


# Singleton instance for global access
_settings_manager: Optional[SettingsManager] = None


def get_settings_manager() -> Optional[SettingsManager]:
    """Get the global settings manager instance."""
    return _settings_manager


def init_settings_manager(db_path: Path, base_dir: Path = None) -> SettingsManager:
    """Initialize the global settings manager."""
    global _settings_manager
    _settings_manager = SettingsManager(db_path, base_dir)
    return _settings_manager
