idf_component_register(SRCS "main.c" "max30102.c" "ppg_hr.c" "lcd.c" "rd_probe.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_driver_i2c esp_driver_spi esp_driver_gpio esp_driver_uart esp_lcd esp_timer esp_adc)
