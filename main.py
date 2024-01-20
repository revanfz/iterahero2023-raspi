import os
import sys
import ssl
import time
import math
import json
import serial
import asyncio
import aiomqtt
import serial.tools.list_ports

import RPi.GPIO as GPIO
from sensor.Sensor import SensorADC, SensorNonADC

NAME = 'Raspi Mitra'

ESP_ser = None
MQTT = None

actuator = {
    "RELAY_A": 17, # Relay 1
    "RELAY_B": 27, # Relay 2
    "RELAY_ASAM": 22, # Relay 3
    "MOTOR_NUTRISI": 26, # Relay 4
    "MOTOR_MIXING": 5, # Relay 5
    "POMPA_DISTRIBUSI": 6, # Relay 6
    "SELENOID_AIR": 23, # Relay 7
    "SELENOID_DISTRIBUSI": 24, # Relay 8
    "SELENOID_LOOP": 25 # Relay 9
}

isi = {
    'tandon': 0
}

peracikan_state = {
    'airEnough': False,
    'asamEnough': False,
    'nutrisiAEnough': False,
    'nutrisiBEnough': False
}

try:
    with open(os.path.dirname(__file__) + '/config.json') as config_file:
        config_str = config_file.read()
        config = json.loads(config_str)
except FileNotFoundError:
    print("file nya gaada")

tls_params = aiomqtt.TLSParameters(
    ca_certs=None,
    certfile=None,
    keyfile=None,
    cert_reqs=ssl.CERT_NONE,
    tls_version=ssl.PROTOCOL_TLS,
    ciphers=None,
)

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for actuator_name, actuator_pin in actuator.items():
    GPIO.setup(actuator_pin, GPIO.OUT)
    GPIO.output(actuator_pin, GPIO.HIGH) # Mati

async def readSensor():  
    global ESP_ser
    def find_serial_port():
        ports = serial.tools.list_ports.comports()
        for port, desc, hwid in sorted(ports):
            if "USB" in desc:
                return port

        return None

    ESP_ser = serial.Serial(find_serial_port(), 115200)
    ESP_ser.close()
    await asyncio.sleep(2)
    ESP_ser.open()
    ESP_ser.flush()

    lastPubTime = time.time()

    while True:
        try:
            if ESP_ser.in_waiting > 0:
                data = ESP_ser.readline().decode('utf-8').rstrip()
                json_data = json.loads(data)
                microcontroller = json_data["microcontroller"]

                if 'info' in json_data:
                    sensorSuhu.update(round(json_data["info"]["temperature"], 2))
                    sensorPH.update(round(json_data["info"]["ph"], 2))
                    sensorEC.update(round(json_data["info"]["ec"], 3))
                
                if 'waterflow' in json_data:
                    if 'a' in json_data["waterflow"]:
                        waterflowA.update(json_data["waterflow"]["a"]["debit"], json_data["waterflow"]["a"]["total"])
                    if 'b' in json_data["waterflow"]:
                        waterflowB.update(json_data["waterflow"]["b"]["debit"], json_data["waterflow"]["b"]["total"])
                    if 'air' in json_data["waterflow"]:
                        waterflowAir.update(json_data["waterflow"]["air"]["debit"], json_data["waterflow"]["air"]["total"])
                    if 'asam' in json_data["waterflow"]:
                        waterflowAsam.update(json_data["waterflow"]["asam"]["debit"], json_data["waterflow"]["asam"]["total"])
                    if 'distribusi' in json_data["waterflow"]:
                        waterflowDistribusi.update(json_data["waterflow"]["distribusi"]["debit"], json_data["waterflow"]["distribusi"]["total"])
                        
                if 'volume' in json_data:
                    if 'distribusi' in json_data:
                        isi["tandon"] -= json_data["volume"]["distribusi"]
                    if 'peracikan' in json_data:
                        isi["tandon"] += json_data["volume"]["peracikan"]

                currentTime = time.time()
                if currentTime - lastPubTime > 2:
                    print(f"Suhu: {sensorSuhu.nilai}\tEC: {sensorEC.nilai}\tpH: {sensorPH.nilai}")
                    print(f"Waterflow A ->\tDebit: {waterflowA.nilai}\tVolume Keluar: {waterflowA.total}")
                    print(f"Waterflow B ->\tDebit: {waterflowB.nilai}\tVolume Keluar: {waterflowB.total}")
                    print(f"Waterflow Asam ->\tDebit: {waterflowAsam.nilai}\tVolume Keluar: {waterflowAsam.total}")
                    print(f"Waterflow Air ->\tDebit: {waterflowAir.nilai}\tVolume Keluar: {waterflowAir.total}")
                    print(f"Waterflow Distribusi ->\tDebit: {waterflowDistribusi.nilai}\tVolume Keluar: {waterflowDistribusi.total}\n")

                    await MQTT.publish("iterahero2023/info/sensor", json.dumps({"sensor_adc": [
                            {str(sensorPH.channel): round(sensorPH.nilai, 2)}, {sensorEC.channel: sensorEC.nilai}], 
                        "sensor_non_adc": [{str(sensorSuhu.pin): round(sensorSuhu.nilai, 2)},
                            {str(waterflowA.pin): round(waterflowA.nilai, 2)},
                            {str(waterflowB.pin): round(waterflowB.nilai, 2)},
                            {str(waterflowAir.pin): round(waterflowAir.nilai, 2)},
                            {str(waterflowAsam.pin): round(waterflowAsam.nilai, 2)}
                        ], "microcontollerName": microcontroller
                        }), qos=1)
                    
                    await MQTT.publish("iterahero2023/mikrokontroller/status", json.dumps({
                        "mikrokontroler": microcontroller
                    }), qos=1)

                    lastPubTime = time.time()
                
        except json.JSONDecodeError as e:
            # print(f"Gagal memparsing json : {e}")
            continue

        except UnicodeDecodeError as e:
            # print(f"Error decoding data: {e}")
            continue

        except KeyError:
            print(f"Key yang diperlukan tidak ditemukan")
            continue

        except KeyboardInterrupt as e:
            print(f"Pembacaan sensor dihentikan")
            break
                

def kontrol_peracikan(state=False, mix=False):
    control = GPIO.LOW if state else GPIO.HIGH
    GPIO.output(actuator["SELENOID_AIR"], control)
    GPIO.output(actuator["RELAY_A"], control)
    GPIO.output(actuator["RELAY_B"], control)
    if mix:
        GPIO.output(actuator["MOTOR_MIXING"], control)


def check_peracikan():
    air = not(GPIO.input(actuator["SELENOID_AIR"]))
    a = not(GPIO.input(actuator["RELAY_A"]))
    b = not(GPIO.input(actuator["RELAY_B"]))
    motor = not(GPIO.input(actuator["MOTOR_MIXING"]))
    return air and a and b and motor


def checkVAR(item):
    for var_names, var_value in item.items():
        print(f"{var_names} = {var_value}")


def turn_off_actuator():
    for actuator_name, actuator_pin in actuator.items():
        GPIO.output(actuator_pin, GPIO.HIGH) # Mati


def stop_peracikan():
    print("Peracikan Selesai" if peracikan_state["airEnough"] else "Peracikan Dihentikan")
    ESP_ser.write(json.dumps({ "peracikan": False }).encode())


async def kontrolAktuatorPeracikan(sensor, cairan, targetVolume, aktuatorPin):
    # await asyncio.sleep(0.2)
    if (sensor.total / 1000 >= targetVolume):
        ESP_ser.write(json.dumps({ "detach": { "pin": sensor.pin, "cairan": cairan }}).encode())
        GPIO.output(aktuatorPin, GPIO.HIGH)
        peracikan_state[cairan + "Enough"] = True
        return True
    else:
        return False

async def monitorPeracikan(volumeAir, volumeA, volumeB):
    while True:
        results = await asyncio.gather(
            kontrolAktuatorPeracikan(waterflowAir, "air", volumeAir, actuator["SELENOID_AIR"]),
            kontrolAktuatorPeracikan(waterflowA, "nutrisiA", volumeA, actuator["RELAY_A"]),
            kontrolAktuatorPeracikan(waterflowB, "nutrisiB", volumeB, actuator["RELAY_B"])
        )
        
        if all(results):
            stop_peracikan()
            break


async def test_waterflow(volume, cairan, sensor, relay_pin):
    volume *= 1000
    try:
        ESP_ser.write(json.dumps({"waterflow": {"volume": volume, "cairan": cairan, "pin": sensor.pin}}).encode())
        GPIO.output(relay_pin, GPIO.LOW) # Nyala
        print(f"Pompa {cairan} Nyala")
        
        while sensor.total < volume:
            print(f"Volume {cairan} yang keluar: {sensor.total / 1000} L")
            await asyncio.sleep(0.1)
        
    except Exception as e:
        print(f"Error during waterflow test: {e}")

    except (asyncio.CancelledError, KeyboardInterrupt) as e:
        print(f"Waterflow dibatalkan {e}")

    finally:
        ESP_ser.write(json.dumps({ "waterflow": { "cairan": cairan, "pin": sensor.pin }}).encode())
        GPIO.output(relay_pin, GPIO.HIGH) # Mati
        print(f"Pompa {cairan} mati")
        await asyncio.sleep(3)
        sensor.reset()


async def validasi_ph(ph_min, ph_max):
    print("Validasi pH")
    if ph_min <= sensorPH.nilai <= ph_max:
        print("PH aman")
    else:
        if sensorPH.nilai > 7:
            print("Tambahin asam")
            asam_tambahan = math.log10(1 /  (10 ** -(14 - sensorPH.nilai))) / 0.1 # belum final
            print(f"Perlu tambahan {asam_tambahan} L asam")


async def validasi_ppm(ppm_min, ppm_max, konstanta, volume):
    print("Validasi PPM")
    if ppm_min <= sensorEC.nilai <= ppm_max:
        print("PPM Aman")
    else:
        GPIO.output(actuator["MOTOR_MIXING"], GPIO.LOW) # Nyala
        if sensorEC.nilai < ppm_min :
            print(f"Target ppm: {ppm_min} - {ppm_max}")
            print(f"Actual ppm: {sensorEC.nilai}")

            nutrisi_tambahan_a = ((((ppm_min + ppm_max) / 2) * konstanta['rasioA'] / konstanta['ppm']) - (
                sensorEC.nilai * konstanta['rasioA'] / konstanta['ppm'])) / 1000
            nutrisi_tambahan_b = ((((ppm_min + ppm_max) / 2) * konstanta['rasioB'] / konstanta['ppm']) - (
                sensorEC.nilai * konstanta['rasioB'] / konstanta['ppm'])) / 1000

            print(f"Nutrisi A tambahan: {nutrisi_tambahan_a}")
            print(f"Nutrisi B tambahan: {nutrisi_tambahan_b}")


            ESP_ser.write(json.dumps({ "adjustment": "ppm" }).encode())
            
            GPIO.output(actuator["RELAY_A"], GPIO.LOW) # Nyala
            GPIO.output(actuator["RELAY_B"], GPIO.LOW) # Nyala
            while True:
                results = await asyncio.gather(
                    kontrolAktuatorPeracikan(waterflowA, "a", nutrisi_tambahan_a, actuator["RELAY_A"]),
                    kontrolAktuatorPeracikan(waterflowB, "b", nutrisi_tambahan_b, actuator["RELAY_B"]),
                )

                if all(results):
                    stop_peracikan()
                    break
            GPIO.output(actuator["RELAY_A"], GPIO.HIGH) # Mati
            GPIO.output(actuator["RELAY_B"], GPIO.HIGH) # Mati
        else:
            # Ngitung air yang mau ditambahin
            air_tambahan = ((((ppm_min + ppm_max) / 2) * konstanta['rasioAir'] / konstanta['ppm']) - (
                ppm_max * konstanta['rasioAir'] / konstanta['ppm'])) / 1000 * volume
            print(f"Air tambahan : {air_tambahan}")
            GPIO.output(actuator["SELENOID_AIR"], GPIO.LOW) # Nyala
            while not kontrolAktuatorPeracikan(waterflowAir, "air", air_tambahan, actuator["SELENOID_AIR"]):
                await asyncio.sleep(0.1)
            GPIO.output(actuator["SELENOID_AIR"], GPIO.HIGH) # Mati

async def infoSensorPeracikan(stop=False):
    print(f"Suhu: {sensorSuhu.nilai}\tEC: {sensorEC.nilai}\tpH: {sensorPH.nilai}")
    print(f"Waterflow A ->\tDebit: {waterflowA.nilai}\tVolume Keluar: {waterflowA.total}")
    print(f"Waterflow B ->\tDebit: {waterflowB.nilai}\tVolume Keluar: {waterflowB.total}")
    print(f"Waterflow Asam ->\tDebit: {waterflowAsam.nilai}\tVolume Keluar: {waterflowAsam.total}")
    print(f"Waterflow Air ->\tDebit: {waterflowAir.nilai}\tVolume Keluar: {waterflowAir.total}")
    print(f"Waterflow Distribusi ->\tDebit: {waterflowDistribusi.nilai}\tVolume Keluar: {waterflowDistribusi.total}\n")
    await asyncio.sleep(2)


async def startPeracikan(ph_min, ph_max, ppm_min, ppm_max, volume_air, volume_a, volume_b, konstanta, volume):
    try:
        ESP_ser.write(json.dumps({ "peracikan": True }).encode())
        info = asyncio.create_task(infoSensorPeracikan())
        asyncio.create_task(monitorPeracikan(volume_air, volume_a, volume_b))
        
        if volume_air > 0:
            GPIO.output(actuator["SELENOID_AIR"], GPIO.LOW) # Nyala
        else:
            peracikan_state["airEnough"] = True

        if volume_a > 0:
            GPIO.output(actuator["RELAY_A"], GPIO.LOW) # Nyala
        else:
            peracikan_state["nutrisiAEnough"] = True

        if volume_b > 0:
            GPIO.output(actuator["RELAY_B"], GPIO.LOW) # Nyala
        else:
            peracikan_state["nutrisiBEnough"] = True

        GPIO.output(actuator["MOTOR_MIXING"], GPIO.LOW) # Nyala

        relay_state = [{str(actuator["MOTOR_MIXING"]): bool(GPIO.input(actuator["MOTOR_MIXING"]))},
                    {str(actuator["SELENOID_AIR"]): bool(
                        GPIO.input(actuator["SELENOID_AIR"]))},
                    {str(actuator["RELAY_A"]): bool(
                        GPIO.input(actuator["RELAY_A"]))},
                    {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))}]
        
        await MQTT.publish("iterahero2023/actuator", json.dumps({"actuator": relay_state, "microcontrollerName": NAME}), qos=1)

        while not (peracikan_state['airEnough']) or not (peracikan_state['nutrisiBEnough']) or not (peracikan_state['nutrisiAEnough']):
            print("Lagi ngeracik")
            await asyncio.sleep(1)

        kontrol_peracikan(False)
        peracikan_state.update((key, False) for key in peracikan_state)

        GPIO.output(actuator["SELENOID_LOOP"], GPIO.LOW) # Nyala
        GPIO.output(actuator["POMPA_DISTRIBUSI"], GPIO.LOW) # Nyala
        await asyncio.sleep(30)
        GPIO.output(actuator["SELENOID_LOOP"], GPIO.HIGH) # Mati
        GPIO.output(actuator["POMPA_DISTRIBUSI"], GPIO.HIGH) # Mati

        await asyncio.create_task(validasi_ppm(ppm_min, ppm_max, konstanta, volume))
        await asyncio.create_task(validasi_ph(ph_min, ph_max))
        
        kontrol_peracikan(False, True)

        peracikan_state.update((key, False) for key in peracikan_state)
        info.cancel()


    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        loop.run_until_complete(stop_peracikan())
        print(f"{e}")

    finally:
        await MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya", "volume": isi['tandon'], "microcontrollerName": NAME}), qos=1)
        

async def timerActuator(pin, duration):
    state = GPIO.input(pin)
    if pin == actuator["RELAY_DISTRIBUSI"]:
        ESP_ser.write(json.dumps({ "distribusi": True }))
    if not(state):
        print("Udah nyala")
    else:
        if pin == actuator["RELAY_DISTRIBUSI"]:
            GPIO.output(actuator["POMPA_DISTRIBUSI"], GPIO.LOW) # Nyala

        GPIO.output(pin, GPIO.LOW) # Nyala
        print('Nyala')
        await asyncio.sleep(duration * 60)

        if pin == actuator["RELAY_DISTRIBUSI"]:
            ESP_ser.write(json.dumps({ "distribusi": False }))
            GPIO.output(actuator["POMPA_DISTRIBUSI"], GPIO.HIGH) # Mati

        GPIO.output(pin, GPIO.HIGH) # Mati


async def publish_actuator():
    while True:
        try:
            data = []
            for key, value in actuator.items():
                data.append({value: GPIO.input(value)})
            await MQTT.publish("iterahero2023/info/aktuator", json.dumps({ "aktuator": data, "microcontrollerName": NAME }), qos=1)
        
            await asyncio.sleep(2)
        
        except KeyboardInterrupt as e:
            print(f"Publish Aktuator dihentikan{e}")     
            break

async def publishStatus():
    while True:          
        try:
            await MQTT.publish("iterahero2023/mikrokontroller/status", json.dumps({ "mikrokontroler": NAME }), qos=1)
            await asyncio.sleep(2)

        except KeyboardInterrupt as e:
            print(f"Publish Status mikrokontroller dihentikan {e}")     
            break


def on_off_actuator(pin):
    state = GPIO.input(pin)
    print(state)
    GPIO.output(pin, not (state))
    print('Mati' if not (state) else 'Nyala')


async def main():
    global MQTT
    MQTT = aiomqtt.Client(config["mqtt_broker_public"], 1883)
    while True:
        try:
            async with MQTT:
                print("MQTT Ready")
                try:
                    await MQTT.subscribe("iterahero2023/#")
                    asyncio.gather(publish_actuator(), readSensor(), publishStatus())
                    async with MQTT.messages() as messages:
                        async for message in messages:
                            data = json.loads(message.payload)
                            if message.topic.matches("iterahero2023/automation"):
                                print(data)
                                if data['microcontroller'] == NAME:
                                    if data['pin'] and 'durasi' in data:
                                        timerActuator(data['pin'], data['durasi'])
                                    elif data['pin']:
                                        on_off_actuator(data['pin'])
                            if message.topic.matches("iterahero2023/kontrol"):
                                print(data)
                                if data['pin'] and data['microcontroller'] == NAME:
                                    if data['pin'] == actuator["POMPA_DISTRIBUSI"]:
                                        on_off_actuator(actuator['SELENOID_DISTRIBUSI'])
                                        on_off_actuator(actuator['SELENOID_LOOP'])
                                    # await MQTT.publish("iterahero2023/respon/kontrol", json.dumps({ "response": True }), qos=1)
                                    on_off_actuator(data['pin'])
                            if message.topic.matches("iterahero2023/waterflow"):
                                if data['cairan'] == 'air':
                                    asyncio.create_task(test_waterflow(data['volume'], data['cairan'], waterflowAir, actuator["SELENOID_AIR"]))
                                elif data['cairan'] == 'asam':
                                    asyncio.create_task(test_waterflow(data['volume'], data['cairan'], waterflowAsam, actuator["RELAY_ASAM"]))
                                elif data['cairan'] == 'a':
                                    asyncio.create_task(test_waterflow(data['volume'], data['cairan'], waterflowA, actuator["RELAY_A"]))
                                elif data['cairan'] == 'b':
                                    asyncio.create_task(test_waterflow(data['volume'], data['cairan'], waterflowB, actuator["RELAY_B"]))
                            if message.topic.matches("iterahero2023/peracikan"):
                                x = check_peracikan()
                                if x:
                                    print("Masih ada peracikan yang berjalan")
                                else:
                                    print(data)
                                    ESP_ser.write(json.dumps({ "peracikan": True }).encode())
                                    komposisi = data['komposisi']
                                    await MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Meracik " + komposisi['nama'], "microcontrollerName": NAME}), qos=1)
                                    volume = komposisi['volume']
                                    ph_min = komposisi['ph_min']
                                    ph_max = komposisi['ph_max']
                                    ppm_min = komposisi['ppm_min']
                                    ppm_max = komposisi['ppm_max']
                                    konstanta = data['konstanta']
                                    komposisi = data['komposisi']
                                    print(konstanta)
                                    nutrisiA = round(
                                        ((ppm_min + ppm_max) / 2) / konstanta['ppm'] * konstanta['rasioA'] * volume / 1000, 3)
                                    nutrisiB = round(
                                        ((ppm_min + ppm_max) / 2) / konstanta['ppm'] * konstanta['rasioB'] * volume / 1000, 3)
                                    air = volume - (nutrisiA + nutrisiB)

                                    # Print value variabel
                                    checkVAR(locals())

                                    asyncio.create_task(startPeracikan(
                                        ph_min, ph_max, ppm_min, ppm_max, nutrisiA, nutrisiB, air,konstanta, volume))

                except KeyError as e:
                    print(f"Tidak ada {e}")

                except (ValueError, KeyboardInterrupt, asyncio.CancelledError) as e:
                    print(f"{e}")
        
        except aiomqtt.MqttError:
            print(f"Connection lost; Reconnecting in {3} seconds ...")
            await asyncio.sleep(3)
            

if __name__ == "__main__":
    try:
        sensorEC = SensorADC("Sensor EC", "1000 * voltage / 820 / 200 * 1.45", 0)
        sensorPH = SensorADC("Sensor PH", "x", 1)
        sensorSuhu = SensorNonADC("Sensor Suhu", "x", 13)
        waterflowAir = SensorNonADC("Sensor Waterflow Air", "x", 15)
        waterflowAsam = SensorNonADC("Sensor Waterflow Asam", "x", 2)
        waterflowA = SensorNonADC("Sensor Waterflow A", "X", 4)
        waterflowB = SensorNonADC("Sensor Waterflow B", "x", 5)
        waterflowDistribusi = SensorNonADC("Sensor Waterflow Distribusi", "x", 18)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")
        loop.run_until_complete(MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya", "volume": isi['tandon'], "microcontrollerName": NAME}), qos=1))

        if check_peracikan():
            # loop.run_until_complete(stop_peracikan())
            pass
        else:
            print("Sistem Dihentikan")

        ESP_ser.write(json.dumps({ "peracikan": False }).encode())
        ESP_ser.close()
        turn_off_actuator()
        loop.run_until_complete(asyncio.sleep(1))

        GPIO.cleanup()                        
        sys.exit()
