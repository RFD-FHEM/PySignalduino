from sd_protocols import SDProtocols

sd = SDProtocols()

def my_logger(message, level):
    print(f"[LOG LEVEL {level}] {message}")

sd.register_log_callback(my_logger)