from sensor.Sensor import SensorADC, SensorSuhu
if __name__ == "__main__":
    pH_sensor = SensorADC("Sensor pH DF Robot", "y = -54.465x + 858.77", 0, "ph")
    EC_sensor = SensorADC("Sensor EC DF Robot",
                          "y = (0.043x + 13.663) - 60", 1, "ec")
    temp_sensor = SensorSuhu("Sensor Suhu DS18B20", "y = x - 1.63")

    pH_sensor.info()
    EC_sensor.info()
    temp_sensor.info()

    pH_sensor.read_value()
    EC_sensor.read_value()
    temp_sensor.read_value()