"""Branding and licensing constants for DocHopper.

OSS variant of Dochopper/_branding.py. The extraction script copies this
file in place of the private one when bootstrapping the DocHopper repo.

Do not import other internal modules from here — this is a leaf module so it
can be loaded before anything else and read at module-level scope.
"""

APP_NAME           = "DocHopper"
APP_TAGLINE        = "Document-driven workflow automation"

COPYRIGHT_YEAR     = "2026"
COPYRIGHT_HOLDER   = "DocHopper contributors"
COPYRIGHT_EMAIL    = ""   # OSS: no central support address. Issues go to GitHub.
COPYRIGHT_NOTICE   = f"Copyright (c) {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER}. Licensed under the MIT License."
LICENSE_TYPE       = "MIT"
WEBSITE            = "github.com/ProcessLogicLabs/dochopper"
WEBSITE_URL        = f"https://{WEBSITE}"

# GitHub repo backing the auto-updater, auth fetch, and billing-config fetch.
# Format: "owner/repo". Change to point at your own fork if you maintain
# private builds with auto-update.
UPDATE_REPO        = "ProcessLogicLabs/dochopper"
GITHUB_API_URL     = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{UPDATE_REPO}/releases"
AUTH_CONFIG_URL    = f"https://api.github.com/repos/{UPDATE_REPO}/contents/auth_users.json"
BILLING_CONFIG_URL = f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/billing_config.json"
SUPPORT_MAILTO     = "https://github.com/ProcessLogicLabs/dochopper/issues/new"
