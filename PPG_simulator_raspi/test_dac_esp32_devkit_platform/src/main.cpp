// ESP32-S3 - Raw High-Speed ADC Reader (No Filters)
// GPIO4=IR, GPIO5=Red. Sampling rate 20,000 Hz. Output raw 12-bit values.

#include <Arduino.h>

#define SAMPLING_RATE_HZ 20000UL // 20 kHz
#define ADC_BIT_WIDTH 12
#define ADC_ATTEN ADC_11db

const uint8_t adc_pins[] = {4, 5};
const size_t num_pins = 2;
#define CONVERSIONS_PER_PIN 1 // DO NOT average
#define ADC_ISR_IRAM_SAFE true

void setup() { 
  Serial.begin(921600); // High baud rate 
  delay(1000); 

  analogReadResolution(ADC_BIT_WIDTH); 

  analogSetAttenuation(ADC_ATTEN); 

  if (!analogContinuous(adc_pins, num_pins, CONVERSIONS_PER_PIN, SAMPLING_RATE_HZ, NULL)) { 
    Serial.println("Error initializing analogContinuous"); 
    while(1) delay(10); 
  } 
  analogContinuousStart(); 

  Serial.println("==== Raw ADC 20kHz, no filter ===");
}

void loop() { 
  adc_continuous_data_t *result = NULL; 
  if (analogContinuousRead(&result, 0)) { 
    for (size_t i = 0; i < num_pins; i++) { 
      Serial.print(result[i].avg_read_raw); // Print raw numbers 0-4095

      if (i < num_pins - 1) Serial.print(' ');

    }
    Serial.println();

  }
}