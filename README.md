# QiuAi Datamaker

Windows desktop tool for collecting, processing, checking, labeling, and exporting OpenClaw/Hermes trajectory data.

## MVP Scope

- Configure OpenClaw and Hermes log directories
- Scan new raw sessions from source directories
- Support manual file import as fallback
- Assign one of 13 required scene categories
- Run convert -> quality check -> difficulty label -> submission packaging
- Track simple operation logs and processing results
- Export strict customer delivery packages with a separate raw-source backup

## Export Safety

Every successful export creates two sibling directories:

- `submission_export_<timestamp>`: customer delivery only
- `raw_source_backup_<timestamp>`: internal raw inputs plus `manifest.json`

The backup manifest maps each raw file to its record and session, and records its SHA256 checksum. Do not include the raw backup directory in the customer delivery.

## Structure

- `app.py`: desktop entry point
- `qiuai_datamaker/`: application package
- `DATA/`: local runtime data, config, logs, database, work files, exports

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

## Build Notes

The first version targets Windows only. Packaging can be done with `PyInstaller`, then wrapped as a standard installer with Inno Setup.

Installed builds do not require students to install Python separately.
