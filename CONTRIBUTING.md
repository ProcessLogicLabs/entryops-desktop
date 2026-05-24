# Contributing to EntryOps

Thanks for considering a contribution. EntryOps is a small project with a narrow scope — PDF/Excel extraction for the long tail of "someone is re-keying data from a document into a downstream system" — so this guide is short.

## Where help is most useful

1. **New templates** for specific supplier invoice formats. Drop a `.py` file into `entryops/templates/`, inherit from `BaseTemplate`, and it auto-discovers on startup. Use [`sample_template.py`](entryops/templates/sample_template.py) as a starting point.
2. **Documentation** — particularly how-to walkthroughs for the parts master / alias / enrichment pipeline. The `docs/` tree is currently a snapshot from the internal pre-OSS line and will gradually be back-aligned to the 0.1.x surface.
3. **Bug reports** with a reproducer (sample PDF that fails, expected vs. observed extraction).
4. **Test coverage.** There is none today; any pytest scaffolding for the template engine, enrichment pipeline, or exporter is welcome.

## Development setup

```bash
git clone https://github.com/ProcessLogicLabs/entryops-desktop.git
cd entryops-desktop
python -m venv .venv
. .venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -e .
python entryops/entryops.py
```

On Windows, Tesseract is downloaded by the installer at install time. For development on a source checkout, install Tesseract separately if you need OCR fallback for image-only PDFs.

## Pull request checklist

- One logical change per PR. If you're adding a template and also fixing an unrelated bug, that's two PRs.
- Templates should include a short docstring at the top of the file describing the supplier / document layout the template targets and any quirks (e.g. multi-page invoices, embedded packing list, scanned vs. text).
- Bump the version in [`pyproject.toml`](pyproject.toml) and [`entryops/version.py`](entryops/version.py) `__fallback_version__` together — they must agree.
- Add a `## [x.y.z]` entry to [`CHANGELOG.md`](CHANGELOG.md) under the 0.1.x series.
- If the change is user-visible, mention it in the PR description so it can roll into the next release notes.

## Code style

- Match the surrounding style. The main app is a 33K-line single-file PyQt5 module; we're not enforcing a formatter on it yet, so consistency with neighbors matters more than any specific style guide.
- No new third-party dependencies without an issue / discussion first.
- Comments should explain *why*, not *what*. The code already says what.

## Reporting bugs

Open an issue at https://github.com/ProcessLogicLabs/entryops-desktop/issues with:

- EntryOps version (Help → About, or `python -c "from entryops.version import get_version; print(get_version())"`)
- OS and Python version
- Steps to reproduce
- A redacted sample PDF if relevant — strip any customer-identifying data first

## Security

If you find a security issue, please **do not** open a public issue. Email the maintainers via the contact on the GitHub org page so the fix can ship before disclosure.

## License

By contributing, you agree your contributions are licensed under the MIT License (see [LICENSE](LICENSE)).
