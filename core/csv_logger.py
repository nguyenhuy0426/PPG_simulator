import csv
import time
import os
import threading
import logging

log = logging.getLogger("ppg_simulator")

class CSVLogger:
    """Logs PPG numerical data to a CSV file."""
    
    def __init__(self, folder="dataset"):
        self.folder = folder
        self.temp_filename = os.path.join(self.folder, "temp_recording.csv")
        self.file = None
        self.writer = None
        self.is_logging = False
        self.lock = threading.Lock()
        
        if not os.path.exists(self.folder):
            os.makedirs(self.folder, exist_ok=True)

    def start(self):
        with self.lock:
            if not self.is_logging:
                try:
                    # Always start fresh for a new recording
                    self.file = open(self.temp_filename, 'w', newline='')
                    self.writer = csv.writer(self.file)
                    self.writer.writerow(["IR_Raw", "RED_Raw", "HR_BPM", "SpO2_%", "RR_BPM", "PI_%", "Condition"])
                    self.is_logging = True
                    log.info(f"[CSVLogger] Started recording to {self.temp_filename}")
                except Exception as e:
                    log.error(f"[CSVLogger] Failed to open {self.temp_filename}: {e}")

    def stop(self, save=True):
        with self.lock:
            if self.is_logging:
                try:
                    self.file.close()
                    self.is_logging = False
                    log.info(f"[CSVLogger] Stopped recording.")
                except Exception as e:
                    log.error(f"[CSVLogger] Failed to close temp file: {e}")
                    
        # Outside lock to prevent blocking
        if save:
            self._save_temp_to_dataset()
        else:
            if os.path.exists(self.temp_filename):
                os.remove(self.temp_filename)
                log.info("[CSVLogger] Discarded temp recording.")

    def _save_temp_to_dataset(self):
        if not os.path.exists(self.temp_filename):
            return
            
        # Find next available data_N.csv
        idx = 1
        while True:
            new_name = os.path.join(self.folder, f"data_{idx}.csv")
            if not os.path.exists(new_name):
                break
            idx += 1
            
        os.rename(self.temp_filename, new_name)
        log.info(f"[CSVLogger] Saved recording as {new_name}")

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
