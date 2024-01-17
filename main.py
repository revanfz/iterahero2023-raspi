import os
import serial
import math
import ssl
import sys
import json
import asyncio
import aiomqtt
import serial.tools.list_ports

import RPi.GPIO as GPIO
from sensor.Sensor import Sensor, SensorADC, SensorNonADC

NAME = 'Raspi Mitra'

ESP_ser = None
MQTT = None

actuator = {
    "RELAY_AIR": 5,
    "RELAY_A": 17,
    "RELAY_B": 2,
    "RELAY_ASAM": 20,
    "RELAY_DISTRIBUSI": 6,
    "MOTOR_MIXING": 16,
    "MOTOR_NUTRISI": 25,
}

sensor = {
    "WATERFLOW_A": 13,
    "WATERFLOW_B": 26,
    "WATERFLOW_ASAM": 18,
    "WATERFLOW_AIR": 24,
    "WATERFLOW_DISTRIBUSI": 0
}

debit = {
    'air': 0,
    'asam': 0,
    'distribusi': 0,
    'nutrisiA': 0,
    'nutrisiB': 0
}

volume = {
    'nutrisiA': 0,
    'nutrisiB': 0,
    'air': 0,
    'asam': 0,
    'basa': 0,
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
    GPIO.output(actuator_pin, GPIO.LOW)

for sensor_name, sensor_pin in sensor.items():
    GPIO.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

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
    ESP_ser.open()
    await asyncio.sleep(1)
    ESP_ser.flush()

    while True:
        try:
            if ESP_ser.in_waiting > 0 or ESP_ser.readline():
                data = ESP_ser.readline().decode('utf-8').rstrip()
                json_data = json.loads(data)

                sensorSuhu.update(round(json_data["temperature"], 2))
                sensorPH.update(round(json_data["ph"], 2))
                sensorEC.update(round(json_data["ec"], 3))

                print(f"Suhu: {sensorSuhu.nilai}\tEC: {sensorEC.nilai}\tpH: {sensorPH.nilai}")

                await MQTT.publish("iterahero2023/info/sensor", json.dumps({"sensor_adc": [
                        {str(sensorPH.channel): round(sensorPH.nilai, 2)}, {sensorEC.channel: sensorEC.nilai}], 
                    "sensor_non_adc": [{str(sensorSuhu.pin): round(sensorSuhu.nilai, 2)}], "microcontollerName": NAME
                    }), qos=1)

            await asyncio.sleep(1.5)
                
        except json.JSONDecodeError as e:
            # print(f"Gagal memparsing json : {e}")
            continue

        except UnicodeDecodeError as e:
            # print(f"Error decoding data: {e}")
            continue

        except KeyError:
            # print(f"Key yang diperlukan tidak ditemukan")
            continue

        except KeyboardInterrupt as e:
            print(f"Pembacaan sensor dihentikan")
            ESP_ser.close()
            break
                

def countPulse(channel, volume, relay_aktuator, pin_sensor, cairan):
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        if debit[cairan] / 378 >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            peracikan_state[cairan + 'Enough'] = True
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
        if debit[cairan] % 75 == 0:
            print(f"Volume {cairan} yang keluar: {debit[cairan] / 378}")

def kontrol_peracikan(state=False):
    control = GPIO.HIGH if state else GPIO.LOW
    GPIO.output(actuator["RELAY_AIR"], control)
    GPIO.output(actuator["RELAY_A"], control)
    GPIO.output(actuator["RELAY_B"], control)
    # GPIO.output(actuator["MOTOR_MIXING"], control)


def check_peracikan():
    air = GPIO.input(actuator["RELAY_AIR"])
    a = GPIO.input(actuator["RELAY_A"])
    b = GPIO.input(actuator["RELAY_B"])
    motor = GPIO.input(actuator["MOTOR_MIXING"])
    return air and a and b and motor


async def distribusi(selenoid, durasi):
    for item in selenoid:
        GPIO.output(item['GPIO'], GPIO.HIGH)
    try:
        await asyncio.sleep(durasi * 60)
    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")
    finally:
        print("Distribusi Selesai")
        for item in selenoid:
            GPIO.output(item['GPIO'], GPIO.LOW)


def checkVAR(item):
    for var_names, var_value in item.items():
        print(f"{var_names} = {var_value}")


def turn_off_actuator():
    for actuator_name, actuator_pin in actuator.items():
        GPIO.output(actuator_pin, GPIO.LOW)


def stop_peracikan():
    GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
    GPIO.remove_event_detect(sensor["WATERFLOW_A"])
    GPIO.remove_event_detect(sensor["WATERFLOW_B"])

    print("Peracikan Selesai" if peracikan_state["airEnough"] else "Peracikan Dihentikan")


async def test_waterflow(volume, cairan):
    if cairan == 'air':
        GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], cairan))
        GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    elif cairan == 'nutrisiA':
        GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume, actuator["RELAY_A"], sensor["WATERFLOW_A"], cairan))
        GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    elif cairan == 'nutrisiB':
        GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume, actuator["RELAY_B"], sensor["WATERFLOW_B"], cairan))
        GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
    elif cairan == 'asam':
        GPIO.add_event_detect(sensor["WATERFLOW_ASAM"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume, actuator["RELAY_ASAM"], sensor["WATERFLOW_ASAM"], cairan))
        GPIO.output(actuator["RELAY_ASAM"], GPIO.HIGH)


async def validasi_ph(target_ph, actual_ph):
    if 6.0 <= actual_ph <= 7.0:
        print("PH aman")
    else:
        if actual_ph > 7:
            print("Tambahin asam")
            asam_tambahan = math.log10(1 /  (10 ** -(14 - actual_ph))) / 0.1 # belum final
            print(f"Perlu tambahan {asam_tambahan} L asam")
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            #     channel, vol_asam, actuator["RELAY_ASAM"], sensor["WATERFLOW_ASAM_BASA"], 'asam'))
        # else:
        #     print("Tambahin Basa")
        #     basa_tambahan = math.log10(1 / (10 ** -actual_ph)) / 0.1 # Belum final
        #     print(f"Perlu tambahan {basa_tambahan} L basa") 
        #     GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
        #     channel, vol_basa, actuator["RELAY_BASA"], sensor["WATERFLOW_ASAM_BASA"], 'basa'))


async def validasi_ppm(target_ppm, actual_ppm, konstanta, volume):
    if target_ppm - 200 <= actual_ppm <= target_ppm + 200:
        print("PPM Aman")
    else:
        # ada yang ditambahin air / nutrisi
        GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)
        if actual_ppm < target_ppm - 200:
            print(f"Target ppm: {target_ppm}")
            print(f"Actual ppm: {actual_ppm}")

            nutrisi_tambahan_a = ((target_ppm * konstanta['rasioA'] / konstanta['ppm']) - (
                actual_ppm * konstanta['rasioA'] / konstanta['ppm'])) / 1000
            nutrisi_tambahan_b = ((target_ppm * konstanta['rasioB'] / konstanta['ppm']) - (
                actual_ppm * konstanta['rasioB'] / konstanta['ppm'])) / 1000
            GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
                channel, nutrisi_tambahan_a, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
            GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
                channel, nutrisi_tambahan_b, actuator["RELAY_B"], sensor["WATERFLOW_B"], 'nutrisiB'))

            print(f"Nutrisi A add: {nutrisi_tambahan_a}")
            print(f"Nutrisi B add: {nutrisi_tambahan_b}")

            GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
            GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
            while not (peracikan_state['nutrisiAEnough']) or not (peracikan_state['nutrisiBEnough']):
                await asyncio.sleep(0.1)
        else:
            # Ngitung air yang mau ditambahin
            air_tambahan = ((actual_ppm * konstanta['rasioAir'] / konstanta['ppm']) - (
                target_ppm * konstanta['rasioAir'] / konstanta['ppm'])) / 1000 * volume
            print(f"Air tambahan : {air_tambahan}")
            GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
                channel, air_tambahan, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
            GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
            print("Tambahin air")
            while not (peracikan_state['airEnough']):
                await asyncio.sleep(0.1)


async def peracikan(pH, ppm, volume_air, volume_a, volume_b, konstanta, volume, penyiraman=False, durasi=None, pin_selenoid=None):
    GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_air, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
    GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_a, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
    GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_b, actuator["RELAY_B"], sensor["WATERFLOW_B"], 'nutrisiB'))

    if volume_air > 0:
        GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    else:
        GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
        peracikan_state["airEnough"] = True

    if volume_a > 0:
        GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    else:
        GPIO.remove_event_detect(sensor["WATERFLOW_A"])
        peracikan_state["nutrisiAEnough"] = True

    if volume_b > 0:
        GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
    else:
        GPIO.remove_event_detect(sensor["WATERFLOW_B"])
        peracikan_state["nutrisiBEnough"] = True

    GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)

    relay_state = [{str(actuator["MOTOR_MIXING"]): bool(GPIO.input(actuator["MOTOR_MIXING"]))},
                {str(actuator["RELAY_AIR"]): bool(
                    GPIO.input(actuator["RELAY_AIR"]))},
                {str(actuator["RELAY_A"]): bool(
                    GPIO.input(actuator["RELAY_A"]))},
                {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))}]
    await MQTT.publish("iterahero2023/actuator", json.dumps({"actuator": relay_state, "microcontrollerName": NAME}), qos=1)

    while not (peracikan_state['airEnough']) or not (peracikan_state['nutrisiBEnough']) or not (peracikan_state['nutrisiAEnough']):
        print("Lagi ngeracik")
        await asyncio.sleep(0.2)

    peracikan_state.update((key, False) for key in peracikan_state)

    kontrol_peracikan(False)

    await MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya", "microcontrollerName": NAME}), qos=1)
    stop_peracikan()
    turn_off_actuator()

    peracikan_state.update((key, False) for key in peracikan_state)
    debit.update((key, 0) for key in debit)

    if penyiraman:
        await distribusi(pin_selenoid, durasi)


async def timerActuator(pin, duration):
    state = GPIO.input(pin)
    GPIO.output(pin, not (state))
    print('Nyala' if not (state) else 'Mati')


async def publish_actuator():
    while True:
        try:
            data = []
            for key, value in actuator.items():
                data.append({value: GPIO.input(value)})
            await MQTT.publish("iterahero2023/info/aktuator", json.dumps({ "aktuator": data, "microcontrollerName": NAME }), qos=1)
        
            await asyncio.sleep(1)
        
        except KeyboardInterrupt as e:
            print(f"Publish Aktuator dihentikan{e}")               


def on_off_actuator(pin):
    state = GPIO.input(pin)
    GPIO.output(pin, not (state))
    print('Nyala' if not (state) else 'Mati')


async def main():
    # Inisialisasi TLS parameter buat MQTT
    global MQTT
    MQTT = aiomqtt.Client(config["mqtt_broker_public"], 1883)
    while True:
        try:
            async with MQTT:
                print("MQTT Ready")
                try:
                    await MQTT.subscribe("iterahero2023/#")
                    asyncio.gather(publish_actuator(), readSensor())
                    async with MQTT.messages() as messages:
                        async for message in messages:
                            data = json.loads(message.payload)
                            # if message.topic.matches("iterahero2023/info/sensor"):
                            #     print(message.payload)
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
                                    on_off_actuator(data['pin'])
                            if message.topic.matches("iterahero2023/waterflow"):
                                asyncio.create_task(test_waterflow(data['volume'], data['cairan']))
                            if message.topic.matches("iterahero2023/peracikan"):
                                x = check_peracikan()
                                if x:
                                    print("Masih ada peracikan yang berjalan")
                                else:
                                    komposisi = data['komposisi']
                                    await MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Meracik " + komposisi['nama'], "microcontrollerName": NAME}), qos=1)
                                    volume = komposisi['volume']
                                    ph = komposisi['ph']
                                    ppm = komposisi['ppm']
                                    konstanta = data['konstanta']
                                    komposisi = data['komposisi']
                                    print(konstanta)
                                    nutrisiA = round(
                                        ppm / konstanta['ppm'] * konstanta['rasioA'] * volume / 1000, 3)
                                    nutrisiB = round(
                                        ppm / konstanta['ppm'] * konstanta['rasioB'] * volume / 1000, 3)
                                    air = volume - (nutrisiA + nutrisiB)

                                    # Print value variabel
                                    checkVAR(locals())

                                    asyncio.create_task(peracikan(
                                        ph, ppm, volume_a=nutrisiA, volume_b=nutrisiB,
                                        volume_air=air, konstanta=konstanta, volume=volume))

                except KeyError as e:
                    print(f"Tidak ada {e}")

                except (ValueError, KeyboardInterrupt) as e:
                    print(f"{e}")
        
        except aiomqtt.MqttError:
            print(f"Connection lost; Reconnecting in {3} seconds ...")
            await asyncio.sleep(3)
            

if __name__ == "__main__":
    try:
        sensorEC = SensorADC("Sensor EC", "1000 * voltage / 820 / 200 * 1.45", 0)
        sensorPH = SensorADC("Sensor PH", "x", 1)
        sensorSuhu = SensorNonADC("Sensor Suhu", "x", 13)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

        if check_peracikan():
            loop.run_until_complete(stop_peracikan())
        else:
            print("Sistem Dihentikan")

        turn_off_actuator()
        loop.run_until_complete(asyncio.sleep(1))

        GPIO.cleanup()                        
        sys.exit()
