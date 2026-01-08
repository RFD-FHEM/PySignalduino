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
from unittest.mock import patch, MagicMock

# Das zu testende Modul importieren
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.generate_sitemap import (
    get_priority_for_path,
    get_changefreq_for_path,
    scan_html_files,
    generate_sitemap_urls,
    create_xml_sitemap,
    BRANCH_URLS,
    get_lastmod_for_file,
    get_git_root,
    main,
)

class TestPriorityMapping:
    """Tests für die Prioritätszuweisung basierend auf Dateipfaden."""
    
    def test_index_html(self):
        assert get_priority_for_path('index.html') == 1.0
    
    def test_user_guide_installation(self):
        assert get_priority_for_path('01_user_guide/installation.html') == 0.9
    
    def test_user_guide_usage(self):
        assert get_priority_for_path('01_user_guide/usage.html') == 0.9
    
    def test_protocol_reference_index(self):
        assert get_priority_for_path('03_protocol_reference/index.html') == 0.8
    
    def test_developer_guide_architecture(self):
        assert get_priority_for_path('02_developer_guide/architecture.html') == 0.8
    
    def test_examples_general(self):
        assert get_priority_for_path('examples/some-example.html') == 0.3
    
    def test_migration_general(self):
        assert get_priority_for_path('migration/some-doc.html') == 0.2
    
    def test_unknown_path(self):
        assert get_priority_for_path('unknown/path.html') == 0.5

class TestChangefreqMapping:
    """Tests für die Update-Frequenz-Zuweisung."""
    
    def test_index_html(self):
        assert get_changefreq_for_path('index.html') == 'monthly'
    
    def test_user_guide_installation(self):
        assert get_changefreq_for_path('01_user_guide/installation.html') == 'yearly'
    
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
        (self.build_dir / '01_user_guide').mkdir()
        (self.build_dir / '01_user_guide' / 'installation.html').write_text('<html></html>')
        (self.build_dir / 'examples' / 'bash').mkdir(parents=True)
        (self.build_dir / 'examples' / 'bash' / 'coverage-report.html').write_text('<html></html>')
        
        files = scan_html_files(self.build_dir)
        paths = [f['path'] for f in files]
        assert '01_user_guide/installation.html' in paths
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
        self.create_test_html('01_user_guide/installation.html')
        html_files = scan_html_files(self.build_dir)
        urls = generate_sitemap_urls(html_files, 'https://example.com')
        
        assert len(urls) == 1
        url = urls[0]
        assert url['loc'] == 'https://example.com/01_user_guide/installation'
        assert url['priority'] == '0.9'
        assert url['changefreq'] == 'yearly'
    
    def test_url_generation_directory_index(self):
        self.create_test_html('01_user_guide/index.html')
        html_files = scan_html_files(self.build_dir)
        urls = generate_sitemap_urls(html_files, 'https://example.com')
        
        assert len(urls) == 1
        assert urls[0]['loc'] == 'https://example.com/01_user_guide'
    
    def test_multiple_urls(self):
        self.create_test_html('index.html')
        self.create_test_html('01_user_guide/installation.html')
        self.create_test_html('examples/basic-usage.html')
        
        html_files = scan_html_files(self.build_dir)
        urls = generate_sitemap_urls(html_files, 'https://example.com')
        
        assert len(urls) == 3
        locs = [u['loc'] for u in urls]
        assert 'https://example.com' in locs
        assert 'https://example.com/01_user_guide/installation' in locs
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


class TestScanHtmlFilesEdgeCases:
    """Tests für Edge Cases beim Scannen von HTML-Dateien."""
    
    def test_nonexistent_directory(self):
        """Teste, dass scan_html_files mit nicht existierendem Verzeichnis umgeht."""
        non_existent = Path('/nonexistent/path')
        files = scan_html_files(non_existent)
        assert len(files) == 0
    
    def test_non_html_files_ignored(self):
        """Teste, dass nur .html-Dateien gescannt werden."""
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp) / 'build' / 'site' / 'html'
            build_dir.mkdir(parents=True)
            (build_dir / 'index.txt').write_text('text')
            (build_dir / 'image.png').write_text('png')
            (build_dir / 'index.html').write_text('<html></html>')
            
            files = scan_html_files(build_dir)
            paths = [f['path'] for f in files]
            assert 'index.html' in paths
            assert len(files) == 1


class TestLastModFunction:
    """Tests für die get_lastmod_for_file Funktion."""
    
    @patch('tools.generate_sitemap.get_git_root')
    @patch('tools.generate_sitemap.subprocess.run')
    def test_get_lastmod_for_file_with_git(self, mock_run, mock_get_git_root):
        """Teste, dass Git-Log verwendet wird, wenn verfügbar."""
        with tempfile.NamedTemporaryFile(suffix='.html') as f:
            file_path = Path(f.name)
            # Mock get_git_root, um das Elternverzeichnis der Datei zurückzugeben
            mock_get_git_root.return_value = file_path.parent
            # Mock subprocess.run für git log
            mock_git_log = MagicMock()
            mock_git_log.returncode = 0
            mock_git_log.stdout = '2025-12-14\n'
            mock_run.return_value = mock_git_log
            
            result = get_lastmod_for_file(file_path)
        
        assert result == '2025-12-14'
        # Überprüfe, dass get_git_root aufgerufen wurde
        mock_get_git_root.assert_called_once()
        # Überprüfe, dass subprocess.run für git log aufgerufen wurde
        mock_run.assert_called_once()
    
    @patch('tools.generate_sitemap.subprocess.run')
    def test_get_lastmod_for_file_without_git(self, mock_run):
        """Teste Fallback auf Dateisystem-Modifikationszeit."""
        mock_run.return_value.returncode = 1  # Git nicht verfügbar
        
        with tempfile.NamedTemporaryFile(suffix='.html') as f:
            file_path = Path(f.name)
            # Setze eine bekannte Modifikationszeit
            import os
            import time
            test_time = time.mktime((2025, 12, 13, 12, 0, 0, 0, 0, 0))
            os.utime(f.name, (test_time, test_time))
            
            result = get_lastmod_for_file(file_path)
        
        assert result == '2025-12-13'
    
    @patch('tools.generate_sitemap.subprocess.run')
    def test_get_lastmod_for_file_git_error(self, mock_run):
        """Teste, dass Git-Fehler abgefangen werden."""
        mock_run.side_effect = FileNotFoundError()  # Git nicht installiert
        
        with tempfile.NamedTemporaryFile(suffix='.html') as f:
            file_path = Path(f.name)
            import os
            import time
            test_time = time.mktime((2025, 12, 10, 12, 0, 0, 0, 0, 0))
            os.utime(f.name, (test_time, test_time))
            
            result = get_lastmod_for_file(file_path)
        
        assert result == '2025-12-10'


class TestMainFunction:
    """Tests für die Hauptfunktion main()."""
    
    @patch('tools.generate_sitemap.sys.exit')
    @patch('tools.generate_sitemap.logger')
    def test_main_missing_build_dir(self, mock_logger, mock_exit):
        """Teste, dass main bei fehlendem Build-Verzeichnis mit Fehler beendet."""
        import sys
        sys.argv = ['generate_sitemap.py', '--build-dir', '/nonexistent']
        
        main()
        
        # Überprüfe, dass sys.exit(1) aufgerufen wurde
        mock_exit.assert_called_with(1)
        # Überprüfe, dass eine Fehlermeldung geloggt wurde
        assert mock_logger.error.called
    
    @patch('tools.generate_sitemap.scan_html_files')
    @patch('tools.generate_sitemap.generate_sitemap_urls')
    @patch('tools.generate_sitemap.create_xml_sitemap')
    @patch('tools.generate_sitemap.write_sitemap')
    @patch('tools.generate_sitemap.Path')
    def test_main_with_branch_arg(self, mock_path, mock_write, mock_create, mock_generate, mock_scan):
        """Teste, dass --branch korrekt verarbeitet wird."""
        import sys
        sys.argv = [
            'generate_sitemap.py',
            '--branch', 'preview',
            '--build-dir', 'build/site/html',
            '--output', 'sitemap.xml'
        ]
        
        # Mock Path.exists() um True zurückzugeben
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance
        
        # Mock die Abhängigkeiten
        mock_scan.return_value = []
        mock_generate.return_value = []
        mock_create.return_value = MagicMock()
        
        main()
        
        # Überprüfe, dass generate_sitemap_urls mit der korrekten Base-URL aufgerufen wurde
        mock_generate.assert_called_once()
        # Die Base-URL sollte die für 'preview' sein
        call_args = mock_generate.call_args
        assert call_args[0][1] == 'https://preview.rfd-fhem.github.io/PySignalduino'
    
    @patch('tools.generate_sitemap.scan_html_files')
    @patch('tools.generate_sitemap.generate_sitemap_urls')
    @patch('tools.generate_sitemap.create_xml_sitemap')
    @patch('tools.generate_sitemap.write_sitemap')
    @patch('tools.generate_sitemap.Path')
    def test_main_with_base_url_arg(self, mock_path, mock_write, mock_create, mock_generate, mock_scan):
        """Teste, dass --base-url Vorrang vor --branch hat."""
        import sys
        sys.argv = [
            'generate_sitemap.py',
            '--branch', 'preview',
            '--base-url', 'https://custom.example.com',
            '--build-dir', 'build/site/html',
            '--output', 'sitemap.xml'
        ]
        
        # Mock Path.exists()
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance
        
        mock_scan.return_value = []
        mock_generate.return_value = []
        mock_create.return_value = MagicMock()
        
        main()
        
        call_args = mock_generate.call_args
        assert call_args[0][1] == 'https://custom.example.com'


class TestPriorityChangefreqMappingUpdates:
    """Tests für aktualisierte Mapping-Tabellen."""
    
    def test_new_priority_mappings(self):
        """Teste neue Einträge in PRIORITY_MAP."""
        # devcontainer-environment.html
        assert get_priority_for_path('devcontainer-environment.html') == 0.3
        # agents.html
        assert get_priority_for_path('agents.html') == 0.3
        # readme.html
        assert get_priority_for_path('readme.html') == 0.3
        # migration/asyncio-migration.html
        assert get_priority_for_path('migration/asyncio-migration.html') == 0.2
    
    def test_new_changefreq_mappings(self):
        """Teste neue Einträge in CHANGEFREQ_MAP."""
        # devcontainer-environment.html
        assert get_changefreq_for_path('devcontainer-environment.html') == 'yearly'
        # agents.html
        assert get_changefreq_for_path('agents.html') == 'monthly'
        # readme.html
        assert get_changefreq_for_path('readme.html') == 'monthly'
        # migration/asyncio-migration.html
        assert get_changefreq_for_path('migration/asyncio-migration.html') == 'never'


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