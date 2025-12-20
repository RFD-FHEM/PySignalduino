# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Core Architecture & Patterns (Manchester Parsing)
- **MC Parsing Chain:** `MCParser.parse()` calls `protocols.demodulate_mc()`, which uses `ManchesterMixin._demodulate_mc_data()` for length/clock checks before calling the specific `mcBit2*` method.
- **TFA Protocol Gotcha:** `mcBit2TFA` implements duplicate message detection by chunking the *entire* received bitstream, not just the expected message length.
- **Grothe Constraint:** `mcBit2Grothe` enforces an *exact* 32-bit length, overriding general length checks.
- **Test Mocking:** MC Parser tests mock `mock_protocols.demodulate` to simulate the output of the protocol layer, not `demodulate_mc` directly.
- **Bit Conversion:** `_convert_mc_hex_to_bits` handles `polarity_invert` and firmware version toggling for polarity.

## Verification Execution
- Das Hauptprogramm für Verifizierungen sollte wie folgt gestartet werden:
  `python3 main.py --timeout 1`
  oder um eine längere Laufzeit zu analysieren:
  `python3 main.py --timeout 30`

## Mandatory Documentation and Test Maintenance

Diese Richtlinie gilt für alle AI-Agenten, die Code oder Systemkonfigurationen in diesem Repository ändern. Jede Änderung **muss** eine vollständige Analyse der Auswirkungen auf die zugehörige Dokumentation und die Testsuite umfassen.

### 1. Dokumentationspflicht
- **Synchronisierung:** Die Dokumentation muss synchron zu allen vorgenommenen Änderungen aktualisiert werden, um deren Genauigkeit und Vollständigkeit sicherzustellen.
- **Bereiche:** Betroffene Dokumentationsbereiche umfassen:
  - `docs/`‑Verzeichnis (AsciiDoc‑Dateien)
  - Inline‑Kommentare und Docstrings
  - README.md und andere Markdown‑Dateien
  - API‑Referenzen und Benutzerhandbücher
- **Prüfung:** Vor dem Abschluss einer Änderung ist zu verifizieren, dass alle dokumentationsrelevanten Aspekte berücksichtigt wurden.

### 2. Test‑Pflicht
- **Bestehende Tests:** Die bestehenden Tests sind zu überprüfen und anzupassen, um die geänderten Funktionalitäten korrekt abzudecken.
- **Neue Tests:** Bei Bedarf sind neue Tests zu erstellen, um eine vollständige Testabdeckung der neuen oder modifizierten Logik zu gewährleisten.
- **Test‑Verzeichnis:** Alle Tests befinden sich im `tests/`‑Verzeichnis und müssen nach der Änderung weiterhin erfolgreich ausführbar sein.
- **Test‑Ausführung:** Vor dem Commit ist die Testsuite mit `pytest` (oder dem projektspezifischen Testrunner) auszuführen, um Regressionen auszuschließen.

### 3. Verbindlichkeit
- Diese Praxis ist für **jede** Änderung verbindlich und nicht verhandelbar.
- Ein Commit, der die Dokumentation oder Tests nicht entsprechend anpasst, ist unzulässig.
- Agenten müssen sicherstellen, dass ihre Änderungen den etablierten Qualitätsstandards des Projekts entsprechen.

### 4. Checkliste vor dem Commit
- [ ] Dokumentation im `docs/`‑Verzeichnis aktualisiert
- [ ] Inline‑Kommentare und Docstrings angepasst
- [ ] README.md und andere Markdown‑Dateien geprüft
- [ ] Bestehende Tests angepasst und erfolgreich ausgeführt
- [ ] Neue Tests für geänderte/neue Logik erstellt
- [ ] Gesamte Testsuite (`pytest`) ohne Fehler durchgelaufen
- [ ] Änderungen mit den Projekt‑Konventionen konsistent

Diese Richtlinie gewährleistet, dass Code‑Änderungen nicht isoliert, sondern im Kontext des gesamten Projekts betrachtet werden und die langfristige Wartbarkeit sowie die Zuverlässigkeit der Software erhalten bleibt.