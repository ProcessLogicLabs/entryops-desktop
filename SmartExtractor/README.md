# Smart Extractor

This module was extracted from EntryOps for future development as a standalone feature.

## Files

- `smart_extractor.py` - Core extraction logic
- `smart_extractor_dialog.py` - PyQt5 dialog interface

## Purpose

The Smart Extractor was designed to help with:
- Extracting data from invoices using pattern matching
- Building templates interactively
- Testing extraction patterns

## Status

**Parked for future development**

This feature was removed from the main EntryOps application on 2025-12-27 to focus on the AI Template Generator integration.

## To Reintegrate

If you want to reintegrate this into EntryOps:

1. Move the .py files back to the Entryops directory
2. Add a button to open the Smart Extractor dialog
3. Connect the `template_created` signal to refresh templates

Example:
```python
from smart_extractor_dialog import SmartExtractorDialog
dialog = SmartExtractorDialog(self)
dialog.template_created.connect(self.ocrmill_on_template_created)
dialog.exec_()
```
