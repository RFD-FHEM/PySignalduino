import pytest
from sd_protocols.methods.somfy import mc_bit2somfy_rts

@pytest.fixture
def protocol_id():
    return 5043

def test_mcbitnum_not_57(protocol_id):
    bitdata = "10011000110110111101000101010011110101100011000110111011"
    rcode, hexresult = mc_bit2somfy_rts(obj=True, bitdata=bitdata, protocol_id=protocol_id, mcbitnum=len(bitdata))
    assert rcode == 1
    assert hexresult == "98DBD153D631BB"

def test_mcbitnum_eq_57(protocol_id):
    bitdata = "110011000110110111101000101010011110101100011000110111011"
    rcode, hexresult = mc_bit2somfy_rts(obj=True, bitdata=bitdata, protocol_id=protocol_id, mcbitnum=len(bitdata))
    assert rcode == 1
    assert hexresult == "98DBD153D631BB"

def test_mcbitnum_undefined(protocol_id):
    bitdata = "10011000110110111101000101010011110101100011000110111011"
    rcode, hexresult = mc_bit2somfy_rts(obj=True, bitdata=bitdata, protocol_id=protocol_id, mcbitnum=None)
    assert rcode == 1
    assert hexresult == "98DBD153D631BB"

@pytest.mark.xfail(reason="needs some code enhancement")
def test_message_too_long(protocol_id):
    bitdata = "100110001101101111010001010100111101011000110001101110111010"
    rcode, hexresult = mc_bit2somfy_rts(obj=True, bitdata=bitdata, protocol_id=protocol_id, mcbitnum=None)
    assert rcode == -1
    assert hexresult is None
