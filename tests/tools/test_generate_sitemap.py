#!/usr/bin/env python3
"""
Tests für das Sitemap-Generierungsskript (tools/generate_sitemap.py).

Diese Tests überprüfen die Kernfunktionalitäten der Sitemap-Generierung,
einschließlich Prioritätszuweisung, Update-Frequenzen und XML-Validierung.
"""

import pytest
import tempfile
import shutil
import sys
import os
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET

# Das zu testende Modul importieren
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.generate_sitemap import (
    get_priority_for_path,
    get_changefreq_for_path,
    scan_html_files,
    generate_sitemap_urls,
    create_xml_sitemap,
    BRANCH_URLS,
)

class TestPriorityMapping:
    """Tests für die Prioritätszuweisung basierend auf Dateipfaden."""
    
    def test_index_html(self):
        assert get_priority_for_path('index.html') == 1.0
    
    def test_user_guide_installation(self):
        assert get_priority_for_path('user-guide/installation.html') == 0.9
    
    def test_user_guide_usage(self):
        assert get_priority_for_path('user-guide/usage.html') == 0.9
    
    def test_protocol_reference_index(self):
        assert get_priority_for_path('protocol-reference/index.html') == 0.8
    
    def test_developer_guide_architecture(self):
        assert get_priority_for_path('developer-guide/architecture.html') == 0.7
    
    def test_examples_general(self):
        assert get_priority_for_path('examples/some-example.html') == 0.2
    
    def test_migration_general(self):
        assert get_priority_for_path('migration/some-doc.html') == 0.1
    
    def test_unknown_path(self):
        assert get_priority_for_path('unknown/path.html') == 0.5

class TestChangefreqMapping:
    """Tests für die Update-Frequenz-Zuweisung."""
    
    def test_index_html(self):
        assert get_changefreq_for_path('index.html') == 'monthly'
    
    def test_user_guide_installation(self):
        assert get_changefreq_for_path('user-guide/installation.html') == 'yearly'
    
    def test_changelog(self):
        assert get_changefreq_for_path('changelog.html') == 'weekly'
    
    def test_migration_asyncio(self):
        assert get_changefreq_for_path('migration/asyncio-migration.html') == 'never'
    
    def test_examples_general(self):
        assert get_changefreq_for_path('examples/some-example.html') == 'yearly'
    
    def test_unknown_path(self):
        assert get_changefreq_for_path('unknown/path.html') == 'yearly'

class TestScanHtmlFiles:
    """Tests für das Scannen von HTML-Dateien."""
    
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = Path(self.temp_dir) / 'build' / 'site' / 'html'
        self.build_dir.mkdir(parents=True)
    
    def teardown_method(self):
        shutil.rmtree(self.temp_dir)
    
    def test_empty_directory(self):
        files = scan_html_files(self.build_dir)
        assert len(files) == 0
    
    def test_single_html_file(self):
        (self.build_dir / 'index.html').write_text('<html></html>')
        files = scan_html_files(self.build_dir)
        assert len(files) == 1
        assert files[0]['path'] == 'index.html'
    
    def test_nested_html_files(self):
        (self.build_dir / 'user-guide').mkdir()
        (self.build_dir / 'user-guide' / 'installation.html').write_text('<html></html>')
        (self.build_dir / 'examples' / 'bash').mkdir(parents=True)
        (self.build_dir / 'examples' / 'bash' / 'coverage-report.html').write_text('<html></html>')
        
        files = scan_html_files(self.build_dir)
        paths = [f['path'] for f in files]
        assert 'user-guide/installation.html' in paths
        assert 'examples/bash/coverage-report.html' in paths
    
    def test_ignore_hidden_files(self):
        (self.build_dir / '_hidden.html').write_text('<html></html>')
        (self.build_dir / '.hidden.html').write_text('<html></html>')
        files = scan_html_files(self.build_dir)
        assert len(files) == 0

class TestGenerateSitemapUrls:
    """Tests für die Generierung von Sitemap-URLs."""
    
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = Path(self.temp_dir) / 'build' / 'site' / 'html'
        self.build_dir.mkdir(parents=True)
    
    def teardown_method(self):
        shutil.rmtree(self.temp_dir)
    
    def create_test_html(self, rel_path):
        full_path = self.build_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text('<html></html>')
        return full_path
    
    def test_url_generation_index(self):
        self.create_test_html('index.html')
        html_files = scan_html_files(self.build_dir)
        urls = generate_sitemap_urls(html_files, 'https://example.com')
        
        assert len(urls) == 1
        url = urls[0]
        assert url['loc'] == 'https://example.com'
        assert url['priority'] == '1.0'
        assert url['changefreq'] == 'monthly'
    
    def test_url_generation_nested(self):
        self.create_test_html('user-guide/installation.html')
        html_files = scan_html_files(self.build_dir)
        urls = generate_sitemap_urls(html_files, 'https://example.com')
        
        assert len(urls) == 1
        url = urls[0]
        assert url['loc'] == 'https://example.com/user-guide/installation'
        assert url['priority'] == '0.9'
        assert url['changefreq'] == 'yearly'
    
    def test_url_generation_directory_index(self):
        self.create_test_html('user-guide/index.html')
        html_files = scan_html_files(self.build_dir)
        urls = generate_sitemap_urls(html_files, 'https://example.com')
        
        assert len(urls) == 1
        assert urls[0]['loc'] == 'https://example.com/user-guide'
    
    def test_multiple_urls(self):
        self.create_test_html('index.html')
        self.create_test_html('user-guide/installation.html')
        self.create_test_html('examples/basic-usage.html')
        
        html_files = scan_html_files(self.build_dir)
        urls = generate_sitemap_urls(html_files, 'https://example.com')
        
        assert len(urls) == 3
        locs = [u['loc'] for u in urls]
        assert 'https://example.com' in locs
        assert 'https://example.com/user-guide/installation' in locs
        assert 'https://example.com/examples/basic-usage' in locs

class TestXmlSitemapGeneration:
    """Tests für die XML-Sitemap-Generierung."""
    
    def test_create_xml_sitemap(self):
        urls = [
            {
                'loc': 'https://example.com/',
                'lastmod': '2025-12-14',
                'changefreq': 'monthly',
                'priority': '1.0',
            },
            {
                'loc': 'https://example.com/page',
                'lastmod': '2025-12-13',
                'changefreq': 'yearly',
                'priority': '0.5',
            },
        ]
        
        urlset = create_xml_sitemap(urls)
        
        # Überprüfe Root-Element
        assert urlset.tag == 'urlset'
        assert urlset.attrib['xmlns'] == 'http://www.sitemaps.org/schemas/sitemap/0.9'
        
        # Überprüfe Anzahl der URL-Einträge
        url_elements = list(urlset)
        assert len(url_elements) == 2
        
        # Überprüfe ersten URL-Eintrag
        first_url = url_elements[0]
        children = {child.tag: child.text for child in first_url}
        assert children['loc'] == 'https://example.com/'
        assert children['lastmod'] == '2025-12-14'
        assert children['changefreq'] == 'monthly'
        assert children['priority'] == '1.0'
    
    def test_xml_validity(self):
        urls = [{
            'loc': 'https://example.com/',
            'lastmod': '2025-12-14',
            'changefreq': 'monthly',
            'priority': '1.0',
        }]
        
        urlset = create_xml_sitemap(urls)
        
        # Versuche, das XML zu serialisieren (sollte keine Exception werfen)
        xml_str = ET.tostring(urlset, encoding='utf-8')
        assert b'<urlset' in xml_str
        assert b'<loc>https://example.com/</loc>' in xml_str

class TestBranchUrls:
    """Tests für branch-spezifische URLs."""
    
    def test_branch_urls_defined(self):
        assert 'main' in BRANCH_URLS
        assert 'preview' in BRANCH_URLS
        assert 'develop' in BRANCH_URLS
    
    def test_main_branch_url(self):
        assert BRANCH_URLS['main'] == 'https://pysignalduino.rfd-fhem.github.io'
    
    def test_preview_branch_url(self):
        assert BRANCH_URLS['preview'] == 'https://preview.rfd-fhem.github.io/PySignalduino'

def test_integration_with_cli(tmp_path):
    """Integrationstest: Führe das Skript mit einem temporären Build-Verzeichnis aus."""
    import subprocess
    import sys
    
    # Temporäres Build-Verzeichnis erstellen
    build_dir = tmp_path / 'build' / 'site' / 'html'
    build_dir.mkdir(parents=True)
    (build_dir / 'index.html').write_text('<html></html>')
    (build_dir / 'user-guide').mkdir()
    (build_dir / 'user-guide' / 'installation.html').write_text('<html></html>')
    
    # Skript ausführen
    script_path = Path(__file__).parent.parent.parent / 'tools' / 'generate_sitemap.py'
    output_path = tmp_path / 'sitemap.xml'
    
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            '--build-dir', str(build_dir),
            '--output', str(output_path),
            '--base-url', 'https://test.example.com',
            '--verbose',
        ],
        capture_output=True,
        text=True,
    )
    
    # Überprüfe, dass das Skript erfolgreich ausgeführt wurde
    assert result.returncode == 0, f"Skript fehlgeschlagen: {result.stderr}"
    
    # Überprüfe, dass die Sitemap-Datei erstellt wurde
    assert output_path.exists()
    
    # Überprüfe, dass die Sitemap gültiges XML ist
    tree = ET.parse(output_path)
    root = tree.getroot()
    # Der Tag enthält den XML-Namespace, also prüfen wir, ob er mit 'urlset' endet
    assert root.tag.endswith('urlset'), f"Unerwarteter Tag: {root.tag}"
    assert len(root) > 0
    
    # Überprüfe, dass die erwarteten URLs enthalten sind
    # Verwende den XML-Namespace für die Suche
    xmlns = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    locs = []
    for elem in root:
        loc_elem = elem.find(f'{xmlns}loc')
        if loc_elem is not None:
            locs.append(loc_elem.text)
    assert 'https://test.example.com' in locs
    assert 'https://test.example.com/user-guide/installation' in locs

if __name__ == '__main__':
    pytest.main([__file__, '-v'])