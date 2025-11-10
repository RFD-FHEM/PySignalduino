"""Pytest configuration and shared fixtures."""
import pytest
from sd_protocols.sd_protocols import SDProtocols


@pytest.fixture
def proto():
    """Fixture to provide a real SDProtocols instance for testing."""
    protocols = SDProtocols()
    
    # Add test protocols from RFFHEM test_protocolData.json
    # These are the protocols used by the Perl tests
    test_protocols = {
        '9986': {
            'id': '9986',
            'name': 'Unittest MC Grothe Protocol',
            'comment': 'only for running automated tests',
            'length_min': 40,
            'length_max': 49,
        },
        '9989': {
            'id': '9989',
            'name': 'Unittest MC Protocol',
            'comment': 'only for running automated tests',
            'format': 'manchester',
            'length_min': 1,
            'length_max': 24,
            'polarity': 'invert',
            'clockrange': [300, 360],
        },
        '9990': {
            'id': '9990',
            'name': 'Unittest MC Protocol',
            'comment': 'only for running automated tests',
            'format': 'manchester',
            'length_min': 2,
            'length_max': 8,
            'clockrange': [300, 360],
        },
    }
    
    # Add test protocols to the protocols dict
    for pid, pdata in test_protocols.items():
        protocols._protocols[pid] = pdata
    
    return protocols
