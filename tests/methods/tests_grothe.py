import pytest
from sd_protocols.methods.grothe import mc_bit2grothe

@pytest.fixture
def protocol_id():
    return 7  # Beispiel-ID für Grothe Gong

def test_mcbitnum_eq_32(protocol_id):
    bitdata = "10101010101010101010101010101010"  # 32 Bit
    rcode, hexresult = mc_bit2grothe(obj=True, bitdata=bitdata, protocol_id=protocol_id, mcbitnum=len(bitdata))
    assert rcode == 1
    assert isinstance(hexresult, str)
    assert len(hexresult) > 0

def test_mcbitnum_not_32(protocol_id):
    bitdata = "10101010"  # nur 8 Bit
    rcode, hexresult = mc_bit2grothe(obj=True, bitdata=bitdata, protocol_id=protocol_id, mcbitnum=len(bitdata))
    assert rcode == -1
    assert hexresult is None
