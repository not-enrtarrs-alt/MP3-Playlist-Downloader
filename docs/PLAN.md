# Plan

- M0: scaffold, paths, settings, logging, SQLite schema, diagnostics, empty GUI, documentation.
- M1: playlist ingestion and refresh, cached track UI.
- M2: download, tagging, scans, extras, deletion, offline demo.
- M3: equalization and settings UI.
- M4: resilient queue, linking, overwrite, retagging.
- M5: packaging, full diagnostics, documentation and tests.
- M6: optional real-world smoke test and handoff.

Current milestone: M5 completed and checkpointed. M6 fixes are implemented and tested offline, but acceptance remains blocked until the user retests a real YouTube download with the updated build. Work and test one sub-step at a time; do not claim M6 complete without the real-download evidence.
