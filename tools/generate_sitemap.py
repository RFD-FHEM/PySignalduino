#!/usr/bin/env python3
"""
Sitemap-Generator für PySignalduino-Dokumentation.

Dieses Skript generiert eine dynamische sitemap.xml basierend auf den HTML-Dateien
im Build-Output-Ordner. Es unterstützt branch-spezifische Base-URLs und weist
Prioritäten sowie Update-Frequenzen basierend auf Dateipfaden zu.

Verwendung:
    python generate_sitemap.py --output build/site/html/sitemap.xml --base-url https://pysignalduino.github.io

Oder in CI/CD:
    python generate_sitemap.py --branch main
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Konfiguration der Logging-Einstellungen
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Mapping von Dateipfad-Mustern zu Prioritäten und Update-Frequenzen
# Basierend auf der tatsächlichen Dokumentationsstruktur und erwarteten HTML-Dateien
PRIORITY_MAP = {
    'index.html': 1.0,
    'user-guide/installation.html': 0.9,
    'user-guide/usage.html': 0.9,
    'user-guide/index.html': 0.8,
    'developer-guide/architecture.html': 0.8,
    'developer-guide/contribution.html': 0.7,
    'developer-guide/index.html': 0.8,
    'protocol-reference/protocol-details.html': 0.7,
    'protocol-reference/index.html': 0.8,
    'examples/basic-usage.html': 0.6,
    'examples/mqtt-integration.html': 0.6,
    'examples/command-api-example.html': 0.5,
    'examples/logging-callback.html': 0.5,
    'examples/logging-debug.html': 0.5,
    'examples/mocking-async.html': 0.5,
    'examples/mqtt-publisher-example.html': 0.5,
    'examples/nested-context-manager.html': 0.5,
    'examples/test-example.html': 0.5,
    'examples/bash/coverage-report.html': 0.4,
    'examples/bash/format-code.html': 0.4,
    'examples/bash/install-dev-deps.html': 0.4,
    'examples/bash/install-dev-requirements.html': 0.4,
    'examples/bash/install-requirements.html': 0.4,
    'examples/bash/install-via-pip.html': 0.4,
    'examples/bash/mosquitto-pub-example.html': 0.4,
    'examples/bash/run-pytest.html': 0.4,
    'examples/bash/run-specific-tests.html': 0.4,
    'examples/bash/update-dependencies.html': 0.4,
    'examples/bash/verify-installation.html': 0.4,
    'examples/': 0.3,  # Allgemeine Beispiele
    'examples/bash/': 0.3,
    'migration/': 0.2,  # Migrationsdokumente (falls generiert)
    'migration/asyncio-migration.html': 0.2,
    'migration/manchester-migration.html': 0.2,
    'migration/methods-migration-complete.html': 0.2,
    'migration/signalduino-migration-plan.html': 0.2,
    'migration/manchester-integration-complete.html': 0.2,
    'devcontainer-environment.html': 0.3,
    'agents.html': 0.3,
    'changelog.html': 0.3,
    'readme.html': 0.3,
}

CHANGEFREQ_MAP = {
    'index.html': 'monthly',
    'user-guide/installation.html': 'yearly',
    'user-guide/usage.html': 'yearly',
    'user-guide/index.html': 'yearly',
    'developer-guide/architecture.html': 'yearly',
    'developer-guide/contribution.html': 'yearly',
    'developer-guide/index.html': 'yearly',
    'protocol-reference/protocol-details.html': 'monthly',
    'protocol-reference/index.html': 'monthly',
    'examples/': 'yearly',
    'examples/bash/': 'yearly',
    'migration/': 'never',
    'devcontainer-environment.html': 'yearly',
    'agents.html': 'monthly',
    'changelog.html': 'weekly',
    'readme.html': 'monthly',
}

# Branch-spezifische Base-URLs
BRANCH_URLS = {
    'main': 'https://pysignalduino.rfd-fhem.github.io',
    'gh-pages': 'https://pysignalduino.rfd-fhem.github.io',
    'gh-pages-preview': 'https://preview.rfd-fhem.github.io/PySignalduino',
    'preview': 'https://preview.rfd-fhem.github.io/PySignalduino',
    'develop': 'https://develop.rfd-fhem.github.io/PySignalduino',
    'staging': 'https://staging.rfd-fhem.github.io/PySignalduino',
}

def get_priority_for_path(file_path: str) -> float:
    """Bestimme die Priorität für einen gegebenen Dateipfad."""
    # Normalisiere den Pfad für den Vergleich
    normalized = file_path.replace('\\', '/')
    
    # Suche nach exakten Übereinstimmungen
    for pattern, priority in PRIORITY_MAP.items():
        if pattern.endswith('/'):
            if normalized.startswith(pattern):
                return priority
        elif normalized == pattern:
            return priority
    
    # Fallback-Priorität basierend auf Verzeichnis
    if normalized.startswith('examples/'):
        return 0.2
    elif normalized.startswith('migration/'):
        return 0.1
    elif normalized.startswith('developer-guide/'):
        return 0.5
    elif normalized.startswith('user-guide/'):
        return 0.7
    elif normalized.startswith('protocol-reference/'):
        return 0.6
    else:
        return 0.5

def get_changefreq_for_path(file_path: str) -> str:
    """Bestimme die Update-Frequenz für einen gegebenen Dateipfad."""
    normalized = file_path.replace('\\', '/')
    
    for pattern, changefreq in CHANGEFREQ_MAP.items():
        if pattern.endswith('/'):
            if normalized.startswith(pattern):
                return changefreq
        elif normalized == pattern:
            return changefreq
    
    # Fallback
    if normalized.startswith('examples/'):
        return 'yearly'
    elif normalized.startswith('migration/'):
        return 'never'
    elif normalized.startswith('developer-guide/'):
        return 'yearly'
    elif normalized.startswith('user-guide/'):
        return 'yearly'
    elif normalized.startswith('protocol-reference/'):
        return 'monthly'
    else:
        return 'yearly'

def get_git_root(start_path: Path) -> Path | None:
    """Finde das Git-Repository-Root-Verzeichnis."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            cwd=start_path,
            check=False
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return None

def get_lastmod_for_file(file_path: Path) -> str:
    """Ermittle das letzte Änderungsdatum einer Datei."""
    # Versuche, den Git-Änderungszeitpunkt zu ermitteln (falls verfügbar)
    # Zuerst das Git-Repository-Root finden
    git_root = get_git_root(file_path.parent)
    if git_root:
        try:
            # Pfad relativ zum Git-Root
            rel_path = file_path.relative_to(git_root)
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%cd', '--date=short', '--', str(rel_path)],
                capture_output=True,
                text=True,
                cwd=git_root
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (ValueError, subprocess.CalledProcessError, FileNotFoundError):
            # Datei nicht innerhalb des Git-Repos oder anderer Fehler
            pass
    
    # Fallback: Dateisystem-Modifikationszeit
    mtime = file_path.stat().st_mtime
    return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')

def scan_html_files(build_dir: Path) -> list[dict]:
    """
    Scanne rekursiv nach HTML-Dateien im Build-Verzeichnis.
    
    Args:
        build_dir: Pfad zum Build-Verzeichnis (z.B. 'build/site/html')
    
    Returns:
        Liste von Dictionaries mit URL-Informationen
    """
    html_files = []
    
    if not build_dir.exists():
        logger.warning(f"Build-Verzeichnis existiert nicht: {build_dir}")
        return html_files
    
    # Durchsuche alle HTML-Dateien
    for html_file in build_dir.rglob('*.html'):
        # Relative Pfad vom Build-Verzeichnis
        rel_path = html_file.relative_to(build_dir)
        rel_str = str(rel_path).replace('\\', '/')
        
        # Ignoriere spezielle Dateien
        if rel_str.startswith('_') or rel_str.startswith('.'):
            continue
        
        html_files.append({
            'path': rel_str,
            'full_path': html_file,
        })
    
    logger.info(f"{len(html_files)} HTML-Dateien gefunden.")
    return html_files

def generate_sitemap_urls(html_files: list[dict], base_url: str) -> list[dict]:
    """
    Generiere URL-Einträge für die Sitemap.
    
    Args:
        html_files: Liste von HTML-Datei-Informationen
        base_url: Basis-URL für die Dokumentation
    
    Returns:
        Liste von URL-Einträgen für die Sitemap
    """
    urls = []
    
    for file_info in html_files:
        rel_path = file_info['path']
        
        # URL zusammenbauen (ohne index.html für Verzeichnis-Index)
        if rel_path == 'index.html':
            url_path = ''
        elif rel_path.endswith('/index.html'):
            url_path = rel_path[:-11]  # Entferne '/index.html' (11 Zeichen)
        else:
            url_path = rel_path[:-5] if rel_path.endswith('.html') else rel_path
        
        # Vollständige URL
        if url_path:
            full_url = f"{base_url}/{url_path}"
        else:
            full_url = base_url
        
        # Priorität und Changefreq bestimmen
        priority = get_priority_for_path(rel_path)
        changefreq = get_changefreq_for_path(rel_path)
        
        # Lastmod bestimmen
        lastmod = get_lastmod_for_file(file_info['full_path'])
        
        urls.append({
            'loc': full_url,
            'lastmod': lastmod,
            'changefreq': changefreq,
            'priority': f"{priority:.1f}",
        })
    
    return urls

def create_xml_sitemap(urls: list[dict]) -> ET.Element:
    """
    Erstelle ein XML-Sitemap-Dokument.
    
    Args:
        urls: Liste von URL-Einträgen
    
    Returns:
        XML-Element (urlset)
    """
    # Namespace für Sitemap
    xmlns = "http://www.sitemaps.org/schemas/sitemap/0.9"
    
    # Root-Element erstellen
    urlset = ET.Element('urlset', xmlns=xmlns)
    
    # URL-Einträge hinzufügen
    for url_info in urls:
        url_elem = ET.SubElement(urlset, 'url')
        
        loc = ET.SubElement(url_elem, 'loc')
        loc.text = url_info['loc']
        
        lastmod = ET.SubElement(url_elem, 'lastmod')
        lastmod.text = url_info['lastmod']
        
        changefreq = ET.SubElement(url_elem, 'changefreq')
        changefreq.text = url_info['changefreq']
        
        priority = ET.SubElement(url_elem, 'priority')
        priority.text = url_info['priority']
    
    return urlset

def prettify_xml(element: ET.Element) -> str:
    """
    Gibt ein XML-Element als formatierten String aus.
    
    Args:
        element: XML-Element
    
    Returns:
        Formatierter XML-String
    """
    rough_string = ET.tostring(element, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent='  ')

def write_sitemap(xml_element: ET.Element, output_path: Path) -> None:
    """
    Schreibe die Sitemap in eine Datei.
    
    Args:
        xml_element: XML-Element (urlset)
        output_path: Pfad zur Ausgabedatei
    """
    # Stelle sicher, dass das Verzeichnis existiert
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # XML formatieren und schreiben
    xml_str = prettify_xml(xml_element)
    
    # XML-Deklaration hinzufügen (wird von prettify bereits eingefügt)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(xml_str)
    
    logger.info(f"Sitemap geschrieben nach: {output_path}")

def main():
    """Hauptfunktion des Skripts."""
    parser = argparse.ArgumentParser(
        description='Generiere eine Sitemap für die PySignalduino-Dokumentation.'
    )
    parser.add_argument(
        '--build-dir',
        default='build/site/html',
        help='Pfad zum Build-Verzeichnis mit HTML-Dateien (Standard: build/site/html)'
    )
    parser.add_argument(
        '--output',
        default='sitemap.xml',
        help='Ausgabedatei für die Sitemap (Standard: sitemap.xml)'
    )
    parser.add_argument(
        '--base-url',
        help='Basis-URL für die Dokumentation (z.B. https://pysignalduino.github.io)'
    )
    parser.add_argument(
        '--branch',
        help='Git-Branch zur Bestimmung der Base-URL'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Ausführliche Logging-Ausgabe'
    )
    
    args = parser.parse_args()
    
    # Logging-Level anpassen
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Base-URL bestimmen
    if args.base_url:
        base_url = args.base_url.rstrip('/')
    elif args.branch:
        if args.branch in BRANCH_URLS:
            base_url = BRANCH_URLS[args.branch]
        else:
            # Fallback für unbekannte Branches (Feature-Branches)
            base_url = BRANCH_URLS['preview']
            logger.warning(
                f"Unbekannter Branch '{args.branch}'. "
                f"Verwende Preview-URL als Fallback: {base_url}"
            )
    else:
        # Standard-URL für main-Branch
        base_url = BRANCH_URLS['main']
    
    logger.info(f"Verwende Base-URL: {base_url}")
    logger.info(f"Scanning Build-Verzeichnis: {args.build_dir}")
    
    # Build-Verzeichnis prüfen
    build_dir = Path(args.build_dir)
    if not build_dir.exists():
        logger.error(f"Build-Verzeichnis existiert nicht: {build_dir}")
        logger.error("Bitte führen Sie zuerst den Dokumentations-Build aus (z.B. 'make html' oder 'antora site.yml').")
        sys.exit(1)
    
    # HTML-Dateien scannen
    html_files = scan_html_files(build_dir)
    
    if not html_files:
        logger.warning("Keine HTML-Dateien gefunden. Sitemap wird leer sein.")
    
    # URL-Einträge generieren
    urls = generate_sitemap_urls(html_files, base_url)
    
    # Sitemap erstellen
    sitemap_xml = create_xml_sitemap(urls)
    
    # Sitemap schreiben
    output_path = Path(args.output)
    write_sitemap(sitemap_xml, output_path)
    
    # Zusammenfassung ausgeben
    logger.info(f"Sitemap erfolgreich generiert mit {len(urls)} URLs.")
    for url in urls[:5]:  # Erste 5 URLs anzeigen
        logger.debug(f"  - {url['loc']} (Priority: {url['priority']})")
    if len(urls) > 5:
        logger.debug(f"  ... und {len(urls) - 5} weitere URLs.")
    
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Skript durch Benutzer abgebrochen.")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Fehler bei der Sitemap-Generierung: {e}")
        sys.exit(1)