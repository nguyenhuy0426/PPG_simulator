import csv
import time
import os
import threading
import logging

log = logging.getLogger("ppg_simulator")

class CSVLogger:
    """Logs PPG numerical data to a CSV file."""
    
    def __init__(self, filename="data.csv"):
        self.filename = filename
        self.file = None
        self.writer = None
        self.is_logging = False
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if not self.is_logging:
                try:
                    mode = 'a' if os.path.exists(self.filename) else 'w'
                    self.file = open(self.filename, mode, newline='')
                    self.writer = csv.writer(self.file)
                    if mode == 'w':
                        self.writer.writerow(["IR_Raw", "RED_Raw", "HR_BPM", "SpO2_%", "RR_BPM", "PI_%", "Condition"])
                    self.is_logging = True
                    log.info(f"[CSVLogger] Started logging to {self.filename}")
                except Exception as e:
                    log.error(f"[CSVLogger] Failed to open {self.filename}: {e}")

    def stop(self):
        with self.lock:
            if self.is_logging:
                try:
                    self.file.close()
                    self.is_logging = False
                    log.info(f"[CSVLogger] Stopped logging to {self.filename}")
                except Exception as e:
                    log.error(f"[CSVLogger] Failed to close {self.filename}: {e}")

    def log_data(self, ir, red, hr, spo2, rr, pi, condition_name):
        with self.lock:
            if self.is_logging and self.writer:
                try:
                    self.writer.writerow([
                        f"{int(ir)}", 
                        f"{int(red)}", 
                        f"{hr:.1f}", 
                        f"{spo2:.1f}", 
                        f"{rr:.1f}", 
                        f"{pi:.2f}", 
                        condition_name
                    ])
                    self.file.flush()
                except Exception as e:
                    log.error(f"[CSVLogger] Error writing data: {e}")
