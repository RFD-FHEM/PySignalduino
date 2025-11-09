# sd_protocols/methods/grothe.py

def bin_str_to_hex_str(bitdata: str) -> str:
    """
    Hilfsfunktion: wandelt eine Binär-Stringfolge in einen Hex-String.
    """
    pad_len = (4 - len(bitdata) % 4) % 4
    bitdata = bitdata + ("0" * pad_len)
    hex_str = hex(int(bitdata, 2))[2:].upper()
    return hex_str


def mc_bit2grothe(obj=None, name="anonymous", bitdata=None, protocol_id=None, mcbitnum=None):
    """
    Portierung von mcBit2Grothe aus Perl.
    Input:
        obj, name, bitdata, protocol_id, optional mcbitnum
    Output:
        (rcode, hexData) bei Erfolg
        (rcode, errorMessage) bei Fehler
    """

    if obj is None:
        return (0, "no object provided")
    if bitdata is None:
        return (0, "no bitData provided")
    if protocol_id is None:
        return (0, "no protocolId provided")

    mcbitnum = mcbitnum if mcbitnum is not None else len(bitdata)

    # Logging nur als print, falls gewünscht
    print(f"lib/mcBit2Grothe, bitdata: {bitdata} ({mcbitnum})")

    # Grothe erwartet 32 Bit
    if mcbitnum != 32:
        return (-1, None)

    enc_data = bin_str_to_hex_str(bitdata)
    return (1, enc_data)
