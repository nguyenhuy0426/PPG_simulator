import csv
import time
import os
import threading
import logging
from pathlib import Path

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
        self.active_filename = ""
        
        if not os.path.exists(self.folder):
            os.makedirs(self.folder, exist_ok=True)

    def start(self, filename=None):
        with self.lock:
            if not self.is_logging:
                try:
                    requested = Path(str(filename)).name if filename else ""
                    if requested and not requested.lower().endswith(".csv"):
                        requested += ".csv"
                    self.active_filename = requested or self._next_filename()
                    # Always start fresh for a new recording
                    self.file = open(self.temp_filename, 'w', newline='')
                    self.writer = csv.writer(self.file)
                    self.writer.writerow(["IR_Raw", "RED_Raw", "HR_BPM", "SpO2_%", "RR_BPM", "PI_%", "Condition", "Time_s", "Source"])
                    self.is_logging = True
                    log.info(f"[CSVLogger] Started recording to {self.temp_filename}")
                except Exception as e:
                    log.error(f"[CSVLogger] Failed to open {self.temp_filename}: {e}")

    def _next_filename(self):
        idx = 1
        while os.path.exists(os.path.join(self.folder, f"data_{idx}.csv")):
            idx += 1
        return f"data_{idx}.csv"

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
            
        new_name = os.path.join(self.folder, self.active_filename or self._next_filename())
        # The active name is shared with the phone so both applications can
        # select the same session. A new recording intentionally replaces an
        # old file with that exact session name.
        os.rename(self.temp_filename, new_name)
        log.info(f"[CSVLogger] Saved recording as {new_name}")

    def log_data(self, ir, red, hr, spo2, rr, pi, condition_name, timestamp_s=None):
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
                        condition_name,
                        "" if timestamp_s is None else f"{timestamp_s:.6f}",
                        "TX model / DAC command"
                    ])
                    self.file.flush()
                except Exception as e:
                    log.error(f"[CSVLogger] Error writing data: {e}")
