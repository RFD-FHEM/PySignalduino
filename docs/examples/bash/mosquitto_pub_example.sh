# Firmware-Version abfragen
mosquitto_pub -t "signalduino/commands/version" -m "GET"

# Empfänger aktivieren
mosquitto_pub -t "signalduino/commands/set/XE" -m "1"