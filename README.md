# helpguideschecker

A small Python CLI that crawls a help site and an app site, compares terminology and paths, and writes markdown reports for potentially missing help-guide coverage.

## Usage

```bash
python helpguideschecker.py \
  --help-url https://help.smartsurvey.co.uk \
  --app-url https://app.smartsurvey.co.uk \
  --output-dir missing-help-guides
```

The command writes:

- `summary.md` with all potential gaps
- One markdown file per uncovered app page

## Tests

```bash
python -m unittest discover -s tests -v
```
