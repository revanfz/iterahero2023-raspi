import os
import time
import glob
import asyncio
import Adafruit_MCP3008

CLK = 21
MISO = 9
MOSI = 10
CS = 8
SAMPEL = 25
mcp = Adafruit_MCP3008.MCP3008(clk=CLK, cs=CS, miso=MISO, mosi=MOSI)


class Sensor:
    def __init__(self, name, persamaan) -> None:
        self.name = name
        self.persamaan = persamaan
        self.timeout = 5

    def info(self):
        print(f"Nama: {self.name}")
        print(f"Persamaan: {self.persamaan}")


class SensorADC(Sensor):
    def __init__(self, name, persamaan, channel, tipe):
        super().__init__(name, persamaan)
        self.channel = channel
        self.tipe = tipe

    def info(self):
        super().info()
        print(f"CHANNEL: {self.channel}\n")

    async def read_value(self):
        count = 0
        val_min = 0
        val_max = 0
        total = 0
        while count < self.timeout:
            count += 1
            raw = 0
            # Baca nilai channel MCP
            values = mcp.read_adc(self.channel)
            if self.tipe == "ec":
                ec = round((values - 13.663) / 0.043, 3) - 60  # Persamaan 1000
                raw = int(ec / 1000 * 500)

                # print(f"EC larutan: { ec } µs/cm")
                # print(f"EC larutan: { round(ec / 1000, 3) } ms/cm")
                print(f"PPM : { raw } ppm", end='\n')
            elif self.tipe == 'ph':
                raw = round((values - 858.77) / -54.465, 2)

                print(f"pH larutan: { raw }")
            if count == 1:
                val_min = raw
                val_max = raw
            else:
                if raw < val_min:
                    val_min = raw
                elif raw > val_max:
                    val_max = raw
            total += raw
            await asyncio.sleep(1)
        # return round(total / self.timeout, 2)
        return (val_min + val_max) / 2


class SensorSuhu(Sensor):
    def __init__(self, name, persamaan) -> None:
        super().__init__(name, persamaan)
        self.path = ''

 
        os.system('modprobe w1-gpio')
        os.system('modprobe w1-therm')
        base_dir = '/sys/bus/w1/devices/'

        while self.path == '':
            try:
                device_folder = glob.glob(base_dir + '28*')[0]
                self.path = device_folder + '/w1_slave'
            except IndexError:
                print(f"{self.name} tidak terhubung ke raspi")
                # time.sleep(1.5)
                return

    def info(self):
        super().info()
        print()

    def read_temp_raw(self):
        if self.path:
            f = open(self.path, 'r')
            lines = f.readlines()
            f.close()
            return lines
        else:
            raise FileExistsError(
                "Sensor tidak ditemukan. Harap periksa koneksi sensor ke Raspi")

    async def read_temp(self):
        if self.path:
            lines = self.read_temp_raw()
            while lines[0].strip()[-3:] != 'YES':
                await asyncio.sleep(0.2)
                lines = self.read_temp_raw()
            equals_pos = lines[1].find('t=')
            if equals_pos != -1:
                temp_string = lines[1][equals_pos+2:]
                temp_c = float(temp_string) / 1000.0 - 0.3
                # temp_f = temp_c * 9.0 / 5.0 + 32.0
                # return [temp_c, temp_f]
                return round(temp_c, 2)
        else:
            raise FileExistsError(
                "Sensor tidak ditemukan. Harap periksa koneksi sensor ke Raspi")

    async def read_value(self):
        if self.path != '':
            count = 0
            val_min = 0
            val_max = 0
            total = 0
            while count < self.timeout:
                count += 1
                suhu = await self.read_temp()
                print(f"Suhu Larutan: {suhu}")
                total += suhu
                await asyncio.sleep(0.5)
                if count == 1:
                    val_min = suhu
                    val_max = suhu
                else:
                    if suhu < val_min:
                        val_min = suhu
                    elif suhu > val_max:
                        val_max = suhu
                
            print()
            # return round(suhu / self.timeout, 2)
            return (val_min + val_max) / 2
        else:
            raise FileExistsError(
                "Sensor tidak ditemukan. Harap periksa koneksi sensor ke Raspi")
