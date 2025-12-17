# Sitemap-Validierungsbericht

**Datum:** 2025-12-17  
**Sitemap-URL:** https://rfd-fhem.github.io/PySignalduino/sitemap.xml  
**Lokale Datei:** `current_sitemap.xml`

## 1. Herunterladen und XML-Struktur

Die Sitemap wurde erfolgreich heruntergeladen (267 Bytes). Die XML-Struktur ist wohlgeformt und entspricht dem Sitemap-Protokoll.

- **XML-Deklaration:** `<?xml version="1.0" ?>` ✓
- **Root-Element:** `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">` ✓
- **Namespace:** korrekt ✓

## 2. Inhalt der Sitemap

Die Sitemap enthält **nur einen einzigen URL-Eintrag**:

```xml
<url>
  <loc>https://pysignalduino.rfd-fhem.github.io</loc>
  <lastmod>2025-12-15</lastmod>
  <changefreq>monthly</changefreq>
  <priority>1.0</priority>
</url>
```

### Validierung der einzelnen Felder:
- `<loc>`: vorhanden, absolute URL ✓
- `<lastmod>`: vorhanden, Format YYYY-MM-DD ✓
- `<changefreq>`: vorhanden, gültiger Wert (`monthly`) ✓
- `<priority>`: vorhanden, numerischer Wert zwischen 0.0 und 1.0 ✓

**Technisch gesehen ist die Sitemap valide gemäß sitemaps.org.**

## 3. Fehlende Seiten (Vergleich mit erwarteter Dokumentation)

Basierend auf der Projektstruktur (`docs/`) und dem Sitemap-Generierungsskript (`tools/generate_sitemap.py`) werden folgende wichtige Seiten erwartet:

| Kategorie | Erwartete URL (Beispiel) | In Sitemap? |
|-----------|--------------------------|-------------|
| Hauptseite | `https://pysignalduino.rfd-fhem.github.io` | ✓ |
| Benutzerhandbuch | `https://pysignalduino.rfd-fhem.github.io/user-guide/installation` | ✗ |
| | `https://pysignalduino.rfd-fhem.github.io/user-guide/usage` | ✗ |
| Entwicklerhandbuch | `https://pysignalduino.rfd-fhem.github.io/developer-guide/architecture` | ✗ |
| | `https://pysignalduino.rfd-fhem.github.io/developer-guide/contribution` | ✗ |
| Protokollreferenz | `https://pysignalduino.rfd-fhem.github.io/protocol-reference/protocol-details` | ✗ |
| Beispiele | `https://pysignalduino.rfd-fhem.github.io/examples/basic-usage` | ✗ |
| Migrationsdokumente | `https://pysignalduino.rfd-fhem.github.io/migration/asyncio-migration` | ✗ |

**Insgesamt fehlen mindestens 10–15 wichtige Unterseiten.**

## 4. Ursachenanalyse

### 4.1. Basis-URL-Konflikt
Die Sitemap verwendet die Base-URL `https://pysignalduino.rfd-fhem.github.io`.  
Ein HTTP-Test ergibt jedoch **HTTP 404** für diese URL, was darauf hindeutet, dass die GitHub Pages-Dokumentation möglicherweise nicht unter dieser Adresse veröffentlicht ist.

Die korrekte Dokumentations-URL könnte stattdessen `https://rfd-fhem.github.io/PySignalduino` sein (wie in der `preview`- und `develop`-Branch-Konfiguration des Skripts). Die Sitemap-Generierung für den `main`-Branch verwendet jedoch die oben genannte URL.

### 4.2. Unvollständige Generierung
Das Sitemap-Generierungsskript scannt das Build-Verzeichnis (`build/site/html`) nach HTML-Dateien. Wenn dieses Verzeichnis leer ist oder nur `index.html` enthält, wird die Sitemap entsprechend knapp.

Möglicherweise wurde die Dokumentation nicht vollständig gebaut, oder der Build-Prozess hat nicht alle HTML-Dateien erzeugt.

### 4.3. Branch-spezifische Unterschiede
Laut `BRANCH_URLS` im Skript:
- `main`: `https://pysignalduino.rfd-fhem.github.io`
- `preview`: `https://preview.rfd-fhem.github.io/PySignalduino`
- `develop`: `https://develop.rfd-fhem.github.io/PySignalduino`

Die aktuell gehostete Sitemap stammt vom `main`-Branch, aber die Dokumentation könnte unter einer anderen URL liegen.

## 5. Empfehlungen

1. **Überprüfung der GitHub Pages-Konfiguration:**  
   Stellen Sie sicher, dass die Dokumentation unter `https://pysignalduino.rfd-fhem.github.io` tatsächlich erreichbar ist. Falls nicht, passen Sie die Base-URL in `BRANCH_URLS` an.

2. **Vollständige Generierung der Sitemap:**  
   Führen Sie das Sitemap-Generierungsskript mit einem vollständigen Build-Verzeichnis aus, um alle HTML-Dateien zu erfassen:
   ```bash
   python3 tools/generate_sitemap.py --build-dir build/site/html --branch main --verbose
   ```

3. **Validierung der generierten Sitemap:**  
   Nach der Generierung sollten mindestens 15–20 URL-Einträge enthalten sein (entsprechend der Anzahl der `.adoc`-Dateien).

4. **Automatische Integration in CI/CD:**  
   Sicherstellen, dass der GitHub Actions Workflow (`.github/workflows/docs.yml`) die Sitemap-Generierung nach jedem Dokumentations-Build ausführt und die `sitemap.xml` korrekt deployt.

5. **Manuelle Ergänzung fehlender URLs:**  
   Falls bestimmte Seiten absichtlich nicht in der Sitemap erscheinen sollen, prüfen Sie die `PRIORITY_MAP` und `CHANGEFREQ_MAP` im Skript auf Vollständigkeit.

## 6. Zusammenfassung

| Kriterium | Status | Bemerkung |
|-----------|--------|-----------|
| XML wohlgeformt | ✓ | Keine Syntaxfehler |
| Sitemap-Schema konform | ✓ | Korrekte Namespace und Elemente |
| Anzahl URLs | ❌ | Nur 1 URL (erwartet: >10) |
| Alle wichtigen Seiten enthalten | ❌ | Fehlen zahlreiche Unterseiten |
| Absolute URLs | ✓ | `loc` ist absolut |
| Optionale Felder vorhanden | ✓ | `lastmod`, `changefreq`, `priority` |

**Gesamtbewertung:** Die Sitemap ist **technisch valide, aber inhaltlich unvollständig**. Sie erfüllt nicht den Zweck, Suchmaschinen über die gesamte Dokumentation zu informieren.

## Anhang

- `current_sitemap.xml`: Heruntergeladene Sitemap
- `test_sitemap.xml`: Beispiel-Sitemap mit erwarteten URLs (generiert mit Test-Build)
- `validate_sitemap.py`: Validierungsskript
- `tools/generate_sitemap.py`: Generierungsskript

---
*Bericht generiert durch automatische Validierung.*