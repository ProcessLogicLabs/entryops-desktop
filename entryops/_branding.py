"""Branding and licensing constants for EntryOps (desktop OSS edition).

OSS variant of entryops/_branding.py. The extraction script copies this
file in place of the private one when bootstrapping the EntryOps desktop
repo.

EntryOps ships as two products under one wordmark:
  - EntryOps (cloud)   — multi-tenant SaaS at https://entryops.us
  - EntryOps (desktop) — this MIT-licensed open-source desktop app

This file configures the *desktop* edition. Do not import other internal
modules from here — this is a leaf module so it can be loaded before
anything else and read at module-level scope.
"""

APP_NAME           = "EntryOps"
APP_TAGLINE        = "Operations platform for customs entry filing"

COPYRIGHT_YEAR     = "2026"
COPYRIGHT_HOLDER   = "EntryOps contributors"
COPYRIGHT_EMAIL    = ""   # OSS: no central support address. Issues go to GitHub.
COPYRIGHT_NOTICE   = f"Copyright (c) {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER}. Licensed under the MIT License."
LICENSE_TYPE       = "MIT"
WEBSITE            = "github.com/ProcessLogicLabs/entryops-desktop"
WEBSITE_URL        = f"https://{WEBSITE}"

# GitHub repo backing the auto-updater, auth fetch, and billing-config fetch.
# Format: "owner/repo". Change to point at your own fork if you maintain
# private builds with auto-update.
UPDATE_REPO        = "ProcessLogicLabs/entryops-desktop"
GITHUB_API_URL     = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{UPDATE_REPO}/releases"
AUTH_CONFIG_URL    = f"https://api.github.com/repos/{UPDATE_REPO}/contents/auth_users.json"
BILLING_CONFIG_URL = f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/billing_config.json"
SUPPORT_MAILTO     = f"https://github.com/{UPDATE_REPO}/issues/new"
