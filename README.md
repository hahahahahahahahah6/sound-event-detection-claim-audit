# Documentation claim auditor

An offline audit tool that compares documentation promises with static Python call evidence. It parses source without executing it. Results are heuristic: matching calls establish a fingerprint, not runtime correctness. Syntax errors contribute no evidence.

## Install and run

Requires Python 3.9 or newer.

```sh
python3 -m pip install .
sound-event-detection-claim-audit /path/to/project
python3 -m sound_event_detection_claim_audit /path/to/project --json
```

The scanner reads the root README and Markdown files beneath a docs path component. Fenced examples are skipped; inline code counts. It excludes symlinks and fixture, example, and documentation source files. Test source is tracked separately. Pairs must occur within one source module; imports alone do not qualify.

## Options and results

Use `--ignore PATH` repeatedly to exclude relative path prefixes, `--verbose` to list evidence files, and `--json` for a report containing verdict, findings, production_evidence, and test_evidence. Each finding includes id, severity, and message. `--version` prints the package version.

Exit status is 0 when no finding reaches the threshold, 2 when a finding reaches it, and 1 for usage or I/O errors. `--fail-on` accepts LOW, MEDIUM, or HIGH and defaults to HIGH. A promise without production evidence is HIGH, or MEDIUM when evidence exists only in tests. A denial conflicting with production evidence is HIGH. A denial without source passes.

Finding identifiers:

```text
documented-sound-event-detection-claim-false
documented-no-sound-event-detection-claim-false
```

## Development

```sh
python3 -m unittest discover
python3 -m sound_event_detection_claim_audit . --json
python3 -m build
```

Distributed under the MIT license.
