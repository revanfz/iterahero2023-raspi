import os
import time
import glob
import asyncio

class Sensor:
    def __init__(self, name, persamaan) -> None:
        self.name = name
        self.persamaan = persamaan
        self.timeout = 3
        self.nilai = 0

    def info(self):
        print(f"Nama: {self.name}")
        print(f"Persamaan: {self.persamaan}")

    def update(self, nilai):
        self.nilai = nilai

class SensorADC(Sensor):
    def __init__(self, name, persamaan, channel):
        super().__init__(name, persamaan)
        self.channel = channel

class SensorNonADC(Sensor):
    def __init__(self, name, persamaan, pin):
        super().__init__(name, persamaan)
        self.pin = pin
