// Bench probe for the MAX30102 module RD / IRD pins (see rd_probe.c for wiring).
#pragma once
#include "esp_err.h"

// Capture both pins for a few tens of ms and print a summary plus every sample on stdout.
esp_err_t rd_probe_capture(void);
