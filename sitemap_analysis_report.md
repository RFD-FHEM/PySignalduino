# Analyse des Sitemap-Generator-Skripts `tools/generate_sitemap.py`

## Zusammenfassung

Das Skript `tools/generate_sitemap.py` generiert eine dynamische `sitemap.xml` basierend auf HTML-Dateien im Build-Output-Ordner. Es weist Prioritäten und Update-Frequenzen basierend auf Dateipfaden zu und unterstützt branch-spezifische Base-URLs.

Die Analyse hat mehrere potenzielle Probleme identifiziert, die zu einer unvollständigen oder fehlerhaften Sitemap führen können.

## 1. Generierungsprozess

### Wie werden HTML-Dateien gefunden?
- Die Funktion `scan_html_files` durchsucht rekursiv das Build-Verzeichnis (`build_dir`) nach Dateien mit der Endung `.html`.
- Versteckte Dateien (beginnend mit `_` oder `.`) werden ignoriert.
- Relative Pfade werden vom Build-Verzeichnis aus berechnet.

### Welche Verzeichnisse werden durchsucht?
- Standardmäßig `build/site/html`. Kann über `--build-dir` angepasst werden.
- Das Skript erstellt ein minimales Build-Verzeichnis mit Beispiel-HTML, falls das Verzeichnis nicht existiert (Zeilen 355–363). Dies ist ein Test-Fallback, der in Produktion nicht auftreten sollte.

### Wie werden URLs konstruiert?
- Basis-URL wird aus `--base-url` oder Branch-Mapping (`BRANCH_URLS`) bestimmt.
- Für jede HTML-Datei:
  - Wenn `rel_path == 'index.html'` → `url_path = ''`
  - Wenn `rel_path.endswith('/index.html')` → `url_path = rel_path[:-11]` (Entfernt `/index.html`)
  - Sonst wird `.html`-Endung entfernt (`rel_path[:-5]`)
- Vollständige URL: `{base_url}/{url_path}` (wenn `url_path` nicht leer)

### Welche Metadaten werden gesetzt?
- **Priority**: Aus `PRIORITY_MAP` (exakte Übereinstimmung oder Präfix) oder Fallback basierend auf Verzeichnis.
- **Changefreq**: Aus `CHANGEFREQ_MAP` oder Fallback.
- **Lastmod**: Git-Änderungsdatum (falls verfügbar), sonst Dateisystem-Modifikationszeit.

## 2. Identifizierte Probleme

### 2.1 Fehlende Build-Verzeichnis-Validierung
- Das Skript erstellt bei fehlendem Build-Verzeichnis Beispiel-HTML-Dateien (`index.html`, `user-guide/installation.html`). Diese könnten in die Sitemap aufgenommen werden und falsche URLs erzeugen.
- **Empfehlung**: Statt Beispielen zu erstellen, sollte das Skript mit einem Fehler abbrechen oder zumindest eine klare Warnung ausgeben.

### 2.2 Git-Änderungszeitpunkt unzuverlässig
- `get_lastmod_for_file` verwendet `cwd=file_path.parent`. Wenn die HTML-Datei außerhalb des Git-Repositories liegt (z.B. im Build-Ordner), schlägt `git log` fehl und es wird die Dateisystem-Modifikationszeit verwendet. Diese kann neuer sein als der tatsächliche Content-Änderungszeitpunkt.
- **Empfehlung**: Das CWD sollte das Root-Repository sein (`Path.cwd()` oder über `git rev-parse --show-toplevel` ermitteln).

### 2.3 Mapping-Tabellen unvollständig/inkonsistent
- Die `PRIORITY_MAP` und `CHANGEFREQ_MAP` enthalten Einträge für Dateien, die im aktuellen Test-Build nicht vorhanden sind (z.B. `migration/asyncio-migration.html`, `readme.html`, `changelog.html`, `agents.html`, `devcontainer-environment.html`).
- Diese Dateien könnten entweder nicht generiert werden oder unter anderen Pfaden liegen. Falls sie fehlen, erhalten sie Fallback-Werte, was nicht unbedingt falsch ist, aber die intendierten Prioritäten/Frequenzen werden nicht angewendet.
- **Empfehlung**: Mapping-Tabellen mit der tatsächlichen Ausgabe des Dokumentations-Builds abgleichen und ggf. anpassen.

### 2.4 Fehlende Index-HTML-Dateien
- Im Test-Build fehlen `user-guide/index.html`, `developer-guide/index.html`, `protocol-reference/index.html`. Diese sind in den Mappings enthalten (`priority: 0.8` bzw. `0.7`). Wenn sie nicht generiert werden, fehlen entsprechende Sitemap-Einträge.
- **Ursache**: Möglicherweise werden diese Index-Dateien nicht von AsciiDoc/Antora erzeugt, weil die entsprechenden `index.adoc`-Dateien existieren. Das Build-System muss überprüft werden.
- **Empfehlung**: Sicherstellen, dass alle erwarteten HTML-Dateien tatsächlich generiert werden. Andernfalls Mapping-Tabellen bereinigen.

### 2.5 Base-URL für Branches möglicherweise falsch
- `BRANCH_URLS['main']` ist `https://pysignalduino.rfd-fhem.github.io`. Ist das die korrekte URL für die Hauptdokumentation? Möglicherweise sollte es `https://pysignalduino.github.io` sein.
- **Empfehlung**: URLs mit den tatsächlichen Deployment-Zielen abgleichen.

### 2.6 Pfadtrenner auf Windows
- Das Skript verwendet `rel_str = str(rel_path).replace('\\', '/')`. Das ist robust, aber es könnte Probleme geben, wenn Pfade gemischte Schrägstriche enthalten (unwahrscheinlich).
- Kein kritisches Problem.

### 2.7 Doppelte Slashes in URLs
- Die Base-URL wird mit `.rstrip('/')` bereinigt. Wenn `url_path` leer ist, wird `full_url = base_url` (ohne trailing slash) korrekt sein. Allerdings erwarten einige Webserver möglicherweise einen trailing slash für die Root-URL. Das ist jedoch kein Sitemap-Problem.
- **Empfehlung**: Keine Änderung notwendig.

### 2.8 Unvollständige Durchsuchung
- Das Skript sucht nur nach `.html`-Dateien. Andere Ressourcen (PDF, Bilder) werden ignoriert, was korrekt ist, da Sitemaps typischerweise nur HTML-Seiten enthalten.
- **Kein Problem**.

### 2.9 Fehlerhafte URL-Konstruktion für "index.html" in Unterverzeichnissen
- Die Logik `rel_path.endswith('/index.html')` erfasst auch `subdir/index.html`. Das Entfernen von `/index.html` (11 Zeichen) ist korrekt.
- **Kein Problem**.

## 3. Vergleich mit Dokumentationsstruktur (`docs/`)

### Vorhandene `.adoc`-Dateien:
- `docs/01_user_guide/index.adoc` → erwartet `user-guide/index.html`
- `docs/02_developer_guide/index.adoc` → erwartet `developer-guide/index.html`
- `docs/03_protocol_reference/index.adoc` → erwartet `protocol-reference/index.html`
- `docs/ASYNCIO_MIGRATION.md` → könnte zu `migration/asyncio-migration.html` werden (wenn konvertiert)
- `docs/MANCHESTER_MIGRATION.md` → ähnlich
- `docs/METHODS_MIGRATION_COMPLETE.md` → ähnlich
- `docs/MIGRATION.md` → ähnlich
- `docs/SIGNALDUINO_MIGRATION_PLAN.md` → ähnlich
- `docs/devcontainer_env.md` → `devcontainer-environment.html`
- `docs/AGENTS.md` (existiert nicht als separate Datei, aber `AGENTS.md` im Root) → `agents.html`

### Diskrepanzen:
- Viele dieser Migrationsdateien sind `.md`, nicht `.adoc`. Ob sie in HTML umgewandelt werden, hängt vom Build-System ab. Im Test-Build sind sie nicht vorhanden.
- Die Mapping-Tabellen enthalten Einträge für diese Dateien, aber sie werden möglicherweise nie generiert, was zu fehlenden Sitemap-Einträgen führt.

## 4. Spezifische Probleme, die zur unvollständigen Sitemap führen

1. **Fehlende HTML-Generierung**: Wenn das Build-System nicht alle erwarteten HTML-Dateien erzeugt, fehlen sie in der Sitemap. Das Skript kann nur vorhandene Dateien erfassen.

2. **Falsche Prioritäten/Frequenzen für nicht gemappte Pfade**: Fallback-Logik weist pauschal `priority=0.5` und `changefreq='yearly'` zu, was für bestimmte Seiten unpassend sein könnte.

3. **Git-Lastmod ungenau**: Wenn `git log` fehlschlägt, wird die Dateisystem-Modifikationszeit verwendet, die nicht dem letzten Content-Update entspricht (z.B. bei Neubuild).

4. **Base-URL-Konfiguration**: Wenn die Base-URL falsch ist, sind alle URLs in der Sitemap ungültig.

## 5. Vorschläge zur Behebung

### Kurzfristig (Skript-Anpassungen):
- **Validierung des Build-Verzeichnisses**: Statt Beispiel-HTML zu erstellen, sollte das Skript einen Fehler ausgeben und den Benutzer auffordern, das Build-Verzeichnis korrekt zu erstellen.
- **Verbesserte Git-Lastmod**: CWD auf Repository-Root setzen; falls nicht möglich, Fallback auf `git log --all` oder den neuesten Commit, der die Quelldatei (`.adoc`) ändert.
- **Bereinigung der Mapping-Tabellen**: Entferne Einträge für nicht existierende HTML-Dateien oder passe das Build-System an, damit diese Dateien generiert werden.
- **Logging verbessern**: Warnung ausgeben, wenn eine Datei in den Mappings nicht gefunden wird.

### Mittelfristig (Build-System-Koordination):
- **Synchronisation mit Antora/AsciiDoc**: Sicherstellen, dass alle `.adoc`- und `.md`-Dateien in HTML umgewandelt werden und die Pfade mit den Mappings übereinstimmen.
- **Automatische Generierung der Mapping-Tabellen**: Ein Skript, das die `docs/`-Struktur analysiert und Prioritäten/Frequenzen basierend auf Metadaten (z.B. Frontmatter) zuweist.

### Langfristig (Robustheit):
- **Integration in CI/CD**: Das Skript sollte nach dem Dokumentations-Build ausgeführt werden, mit korrekter Base-URL je nach Branch.
- **Validierung der Sitemap**: Nach Generierung sollte die Sitemap auf XML-Konformität und gültige URLs geprüft werden (z.B. mit `validate_sitemap.py`).

## 6. Fazit

Das Sitemap-Generator-Skript ist grundsätzlich funktional, hat jedoch mehrere Schwachstellen, die zu unvollständigen oder fehlerhaften Sitemaps führen können. Die Hauptprobleme liegen in der Diskrepanz zwischen erwarteten und tatsächlich generierten HTML-Dateien sowie in der unzuverlässigen Ermittlung des `lastmod`-Datums.

Durch die oben genannten Vorschläge kann die Zuverlässigkeit und Korrektheit der generierten Sitemap deutlich verbessert werden.