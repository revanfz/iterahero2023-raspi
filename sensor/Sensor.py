class Sensor:
    def __init__(self, name, persamaan) -> None:
        self.name = name
        self.persamaan = persamaan
        self.nilai = 0

    def info(self):
        print(f"Nama: {self.name}")
        print(f"Persamaan: {self.persamaan}")

    def update(self, nilai):
        self.nilai = nilai

    def reset(self):
        self.nilai = 0

class SensorADC(Sensor):
    def __init__(self, name, persamaan, channel):
        super().__init__(name, persamaan)
        self.channel = channel

class SensorNonADC(Sensor):
    def __init__(self, name, persamaan, pin):
        super().__init__(name, persamaan)
        self.pin = pin
        self.total = 0
        
    def update(self, nilai, total = 0):
        super().update(nilai)
        self.total = total

    def reset(self):
        super().reset()
        self.total = 0