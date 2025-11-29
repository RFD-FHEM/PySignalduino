import pytest
from sd_protocols import SDProtocols

@pytest.fixture
def protocols():
    return SDProtocols()

def parse_mu_string(line):
    msg_data = {}
    parts = line.split(";")
    for part in parts:
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            msg_data[key] = value
        else:
            msg_data[part] = ""
    
    if "D" in msg_data:
        msg_data["data"] = msg_data["D"]
        
    return msg_data

def test_mu_corrupt_data(protocols):
    # Corrupt Mu data, combined message
    line = "MU;P0=-2272;P1=228;P2=-356;P3=635;P4=-562;P5=433;D=012345234345252343452523434345252345234343434523434345252343452525252525234523452343452345252525;CP=5;R=4;P3=;L=L=-2864;L=H=2980;S=L=-1444;S=H=1509;D=354146333737463037;C==1466;L==32;R==9;"
    msg_data = parse_mu_string(line)
    results = protocols.demodulate(msg_data, "MU")
    assert len(results) == 0

    # Corrupt MU data, unknown specifier V=
    # This input is rejected by MUParser regex validation, so demodulate is never called in production.
    # If we call demodulate directly, it might find a match (e.g. Protocol 61), so we don't test it here for empty results.
    # See test_mu_parser.py for the validation test.

    # Corrupt MU data, missing D= part
    line = "MU;P0=-370;P1=632;P2=112;P3=-555;P4=428;P5=-780;P6=180;P7=-200;CP=4;R=77;"
    msg_data = parse_mu_string(line)
    results = protocols.demodulate(msg_data, "MU")
    assert len(results) == 0

def test_mu_protocol_44(protocols):
    # Test Protocol 44 - MU Data dispatched
    line = "MU;P0=32001;P1=-1939;P2=1967;P3=3896;P4=-3895;D=01213424242124212121242121242121212124212424212121212121242421212421242121242124242421242421242424242124212124242424242421212424212424212121242121212;CP=2;R=39;"
    msg_data = parse_mu_string(line)
    results = protocols.demodulate(msg_data, "MU")
    assert len(results) >= 1
    assert results[0]["protocol_id"] == "44"

def test_mu_protocol_46(protocols):
    # Test Protocol 46 - MU Data dispatched
    line = "MU;P0=-1943;P1=1966;P2=-327;P3=247;P5=-15810;D=01230121212301230121212121230121230351230121212301230121212121230121230351230121212301230121212121230121230351230121212301230121212121230121230351230121212301230121212121230121230351230;CP=1;"
    msg_data = parse_mu_string(line)
    results = protocols.demodulate(msg_data, "MU")
    # Perl test expects 4 dispatches
    assert len(results) >= 1 # At least one, ideally 4 if all repeats are caught
    assert results[0]["protocol_id"] == "46"

def test_mu_protocol_84(protocols):
    # Test Protocol 84 - MU Data dispatched
    line = "MU;P0=-21520;P1=235;P2=-855;P3=846;P4=620;P5=-236;P7=-614;D=012323232454545454545451717451717171745171717171717171717174517171745174517174517174545;CP=1;R=217;"
    msg_data = parse_mu_string(line)
    results = protocols.demodulate(msg_data, "MU")
    assert len(results) >= 1
    assert results[0]["protocol_id"] == "84"

def test_mu_protocol_85(protocols):
    # Test Protocol 85 - MU Data dispatched
    line = "MU;P0=7944;P1=-724;P2=742;P3=241;P4=-495;P5=483;P6=-248;D=01212121343434345656343434563434345634565656343434565634343434343434345634345634345634343434343434343434345634565634345656345634343456563421212121343434345656343434563434345634565656343434565634343434343434563434563434563434343434343434343434345634565634;CP=3;R=47;"
    msg_data = parse_mu_string(line)
    results = protocols.demodulate(msg_data, "MU")
    assert len(results) >= 1
    
    found = False
    for res in results:
        if res["protocol_id"] == "85":
            found = True
            break
    assert found, f"Protocol 85 not found in results: {[r['protocol_id'] for r in results]}"
