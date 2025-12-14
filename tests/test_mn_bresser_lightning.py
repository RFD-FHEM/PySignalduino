import logging
from unittest.mock import MagicMock
from signalduino.parser.mn import MNParser
from signalduino.types import RawFrame
from sd_protocols.sd_protocols import SDProtocols

def test_bresser_lightning_decoding(caplog):
    # Setup
    caplog.set_level(logging.DEBUG)
    protocols = SDProtocols()
    logger = logging.getLogger("MNParser")
    parser = MNParser(protocols, logger, rfmode="Bresser_lightning")
    
    # Test Data
    line = "MN;D=DA5A2866AAA290AAAAAA;R=23;A=-2;"
    frame = RawFrame(line)
    
    expected_payload = "W131#70F082CC00083A000000"
    expected_protocol_id = "131"
    
    # Execute
    messages = list(parser.parse(frame))
    
    # Verify
    if len(messages) != 1:
        print("\nCaptured Logs:")
        for record in caplog.records:
            print(f"{record.levelname}: {record.message}")

    assert len(messages) == 1
    msg = messages[0]
    
    assert msg.protocol_id == expected_protocol_id
    assert msg.payload == expected_payload
    assert msg.metadata["rfmode"] == "Bresser_lightning"
    # 26000000 / 16384 * -2 / 1000 = -3.1738... -> rounded to -3.0
    assert msg.metadata["freq_afc"] == -3.0 