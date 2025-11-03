VERSION = "1.0"

protocols = {
    "1": {
        "name": "Conrad RSL v1",
        "clientmodule": "SD_RSL",
        "bitlength": 20,
        "comment": "remotes and switches"
    },
    "2": {
        "name": "Arduino",
        "clientmodule": "SD_AS",
        "bitlength": 32,
        "comment": "self build arduino sensor"
    },
    "3": {
        "name": "Intertechno",
        "clientmodule": "IT",
        "bitlength": 24,
        "comment": "remote for ELRO, Intertek, etc."
    }
    # … hier kannst du alle weiteren Protokolle aus SD_ProtocolData.pm ergänzen
}
