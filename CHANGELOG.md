# Changelog

All notable changes to DocHopper will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.19] - 2026-04-11

### Security
- Removed auth_users.json from public repository and git history
- Added auth_users.json to .gitignore to prevent future exposure

### Changed
- Updated AI template generator with ~75% token reduction, fast mode, and PDF pre-processing

## [1.2.8] - 2026-03-25

### Fixed
- OCRMill Export Profile combo now refreshes immediately when profiles are saved or deleted
- Dead links in README Data Flow section replaced with flowchart documentation references

### Changed
- Merged ocr_experimental into main for latest README updates

## [1.2.7] - 2026-03-23

### Added
- New supplier template for cast iron invoices
- Per-item GrossWeight output field from packing list extraction
- GrossWeight added to default output column order and Add Output Field dialog
- Incomplete parts detection in pre-flight dialog (missing hts_code, qty_unit, or client_code)
- Reason column in Missing Parts dialog ("Not in database" / "Missing: qty_unit")
- Auto-create parts_master entries when saving part number mappings (with hts_code and qty_unit from hts_units)
- GR (gross = 144 pieces) UOM conversion in enrichment pipeline
- RelatedParties output field from mid_table

### Changed
- PDF Processing tab moved to first position (default tab on startup)
- Removed duplicate User Management tab from Administration Panel
- Ratio columns renamed to Percentage (SteelRatio → SteelPercentage, etc.)
- Enrichment prefers template-provided net_weight over calculated CalcWtNet for Qty1/Qty2

### Fixed
- Template fix: per-item net/gross weights from packing list instead of proportional calculation
- Added additional part number prefixes to supplier template patterns
- Packing list pages no longer skipped by BOL detection when they contain weight data
- MID typeahead: prefix matching instead of contains, popup no longer steals keystrokes
- GROSS UOM corrected to GR (CBP code) in hts_units and parts_master
- HTS verification batch UOM normalization no longer hangs on large datasets

## [1.2.6] - 2026-03-21

### Added
- Incomplete parts detection in pre-flight missing parts dialog
- Parts flagged when in DB but missing hts_code, qty_unit, or client_code
- Pre-populated from existing DB data with extraction values filling gaps

### Changed
- Version bump for production build

## [1.2.5] - 2026-03-19

### Added
- Per-item net weight extraction from supplier packing list
- PDF Processing as default first tab
- Enrichment: template net_weight preferred over CalcWtNet

### Fixed
- PDF Processing tab blank on startup (auth_manager init order)
- Holly McGinnis role updated to division_admin

## [1.2.4] - 2026-03-14

### Added
- **Section 232 Form Extraction**: Parse embedded aluminum and steel declaration forms from supplier PDFs
- CBP CSMS #65236645 value-based formula: `metal_pct = (acquisition_cost / po_value) × 100`
- Confirmation dialog before writing percentages to parts_master
- New parts_master fields: `country_of_smelt_secondary`, `country_of_cast`
- Steel country mapping: `country_of_melt` for "where melted and poured"
- Scanned PDF detection with user warning (no crash)
- MID typeahead with backspace-safe auto-fill and event filter
- Post-export reset: Net Weight and MID fields clear after successful export
- Clear All button on OCRMill panel

### Changed
- Template update: dual invoice support (OEM + PIP format in same PDF)
- New supplier template for trade company invoices

## [1.2.3] - 2026-03-10

### Added
- Clear All button resets OCRMill fields, output list, preview table, and extraction cache
- Crash report dialog with mailto link and disk log for unhandled exceptions

## [1.2.2] - 2026-03-05

### Added
- Parallel PDF extraction via ThreadPoolExecutor for multi-file batches
- Batch missing-parts dialog (one prompt for all files in a drop)
- Template cache: last-used template tried first, full scoring only on cache miss
- Extraction cache: extracted items stored per PDF, reprocess skips re-extraction
- Validation summary signal: file count, HTS hit rate, not-found/incomplete parts, Section 232 pending
- Network write retry: 3 attempts with 1s delay for UNC output paths

## [1.2.1] - 2026-02-28

### Added
- OCRMill direct XLSX export: PDF invoices export directly to XLSX without CSV step
- Country normalization: all country fields normalized to ISO 2-letter codes via `country_codes` DB table
- Per-row CustomerRef: template-extracted `po_number` mapped to CustomerRef in output

## [1.2.0] - 2026-02-20

### Added
- Semantic versioning (MAJOR.MINOR.PATCH)
- Auto-update: version check on startup, in-app update download
- Folder profiles: save and reuse input/output folder path pairs per client/project

## [0.97.65] - 2026-01-22

### Added
- New supplier invoice templates
- Portable ZIP version for no-install deployment

## [0.97.64] - 2026-01-22

### Fixed
- Improved template loading for PyInstaller frozen app
- Handle _MEIPASS path for templates directory

## [0.97.63] - 2026-01-22

### Changed
- Version bump release

## [0.97.62] - 2026-01-22

### Fixed
- Include templates folder in PyInstaller build

## [0.97.61] - 2026-01-22

### Fixed
- Silent update not restarting app after installation
- Added /RESTARTAPPLICATIONS flag to properly restart after silent updates

## [0.97.60] - 2026-01-22

### Fixed
- Template loading relative imports for packaged application
- Ensures templates package is properly initialized for PyInstaller builds

## [0.97.59] - 2026-01-22

### Fixed
- Template loading when running from parent directory
- Global Castings template regex patterns for line item extraction

## [0.97.58] - 2026-01-21

### Added
- Restored database location configuration to Settings dialog
  - Configure shared database paths for Windows and Linux platforms
  - Browse buttons for easy database file selection
  - "Use Local Database" option to reset to local mode
- Silent update installation support
  - Updates can now install automatically in the background without installer prompts
  - User preference for silent vs interactive updates (Settings → Updates)
  - Inno Setup silent installation flags for seamless updates

### Fixed
- Database location settings were missing from UnifiedSettingsDialog
- Users can now switch between local and shared databases from Settings

## [0.97.57] - 2026-01-21

### Added
- New premium animated splash screen with modern design
- Sort toggle button for input files list for better file organization

### Changed
- Enhanced user experience with improved visual feedback

## [0.97.24] - 2026-01-04

### Changed
- Updated Muted Cyan theme color palette to be more blue-toned for better appearance on Windows 11
- Shifted primary accent from green-cyan (#4a7880) to blue-cyan (#4a7088)

## [0.97.23] - 2026-01-03

### Added
- pip installation support for Linux/Ubuntu users via direct GitHub install
- pyproject.toml for package distribution
- Entry point for running as `dochopper` command after pip install

### Changed
- Various UI improvements and refinements

## [0.97.22] - 2026-01-02

### Added
- New Muted Cyan theme option - professional blue-cyan color scheme

### Removed
- Format Code button from UI (streamlined interface)

## [0.97.21] - 2026-01-01

### Added
- Debug logging for shared templates discovery
- Restored template functionality

### Fixed
- Template loading issues

## [0.97.0] - 2025-12-28

### Added
- Backup schedule time picker - configure what time daily backups run
- Usage Statistics dialog with metrics by Entry Writer and Client
- Statistics moved to Account menu

### Changed
- Settings renamed to Preferences
- Configuration renamed to Profiles
- View Log moved to Help menu
- Removed Log View menu (consolidated into Help)
- References dialog defaults to larger size (1200x700)
- HTS Database tab now first/default in References dialog
- Statistics dialog follows theme colors

## [0.96] - 2025-12-20

### Changed
- Tab reorganization: renamed to Invoice Processing, PDF Processing, and Parts View
- Streamlined PDF Processing by removing unused Parts History tab

### Updated
- All flowcharts and documentation to reflect current workflow

## [0.94.0] - 2024-12-18

### Added
- PDF Processing Integration with AI-powered invoice OCR
- Template system for different invoice formats
- Copyright protection and proprietary license notices

### Changed
- Enhanced dark theme styling consistency
- Improved Result Preview column layout

### Fixed
- Value rounding errors in material percentage row splitting

## [0.93.3] - 2024-12-16

### Fixed
- Startup ghost window flash
- Column names updated

### Changed
- Removed required field restriction from MID and Steel % in Parts Import
- Removed Export Profile dropdown and MID Management menu item
- Renamed Net Wt/Pcs columns to Qty1/Qty2 in Result Preview

### Added
- Profile linking, MID/Tariff tabs, and preview table enhancements

## [0.90.2] - 2024-12-14

### Added
- Landscape page setup for exported Excel worksheets
- Reprocess button to re-process invoices after database changes
- Animated spinner on splash screen during startup
- License system framework (disabled, for future use)
- Distribution database with pre-populated Section 232 tariff data

### Changed
- Database merge strategy now prefers database values over invoice values
- Repository cleanup and branch consolidation
- Improved packaging of reference data tables

### Fixed
- Version parsing for git describe format
- Merge strategy to properly prefer database values during processing

## [0.90.1] - 2024-12-01

### Added
- Export profiles for saving output column configurations
- Output column mapping customization
- Section 301 exclusion tariff tracking with symbol indicator
- Theme-specific color settings (Light/Dark modes)
- Split export by invoice number feature
- Color pickers for all Section 232 material types
- Color coding by Section 232 material type

### Changed
- Migrated to git-based versioning system
- Improved UI layout and responsiveness

### Fixed
- Export profile load error before Configuration dialog opened
- Non-232% column not displaying in Result Preview and Export
- Invoice total display and label text
- Country codes defaulting to MID when not in database
- DraggableLabel error when Excel has numeric column headers

## [0.90.0] - 2024-11-15

### Added
- Major refactoring and modernization of codebase
- Improved Parts Master management with advanced search
- Query builder for advanced database searches
- Multiple invoice mapping profiles support
- MID (Manufacturer ID) management system
- CBP quantity unit lookup for HTS codes

### Changed
- Modern tabbed interface design
- Real-time preview table with color-coded rows
- Configurable input/output directories

## [0.85.0] - 2024-10-01

### Added
- Initial public release
- Invoice processing (CSV, XLSX formats)
- CBP-compliant upload worksheet generation
- Parts Master database management
- Section 232 tariff tracking (steel, aluminum)
- Basic column mapping profiles
