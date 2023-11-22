import os
from random import randint, uniform
import ssl
import sys
import json
import asyncio
import aiomqtt

import RPi.GPIO as GPIO
import paho.mqtt.client as paho

from sensor.Sensor import SensorADC, SensorSuhu

with open(os.path.dirname(__file__) + '/config.json') as config_file:
    config_str = config_file.read()
    config = json.loads(config_str)

actuator = {
    "RELAY_AIR": 5,
    "RELAY_A": 2,
    "RELAY_B": 17,
    "RELAY_ASAM": 20,
    "RELAY_BASA": 22,
    "RELAY_DISTRIBUSI": 6,
    "MOTOR_MIXING": 16,
    "MOTOR_NUTRISI": 25,
}

sensor = {
    "WATERFLOW_A": 26,
    "WATERFLOW_B": 13,
    "WATERFLOW_ASAM_BASA": 18,
    "WATERFLOW_AIR": 24
}

debit = {
    'air': 0,
    'asam': 0,
    'basa': 0,
    'distribusi': 0,
    'nutrisiA': 0,
    'nutrisiB': 0
}

volume = {
    'nutrisiA': 0,
    'nutrisiB': 0,
    'air': 0,
    'asam': 0,
    'basa': 0
}

peracikan_state = {
    'airEnough': False,
    'basaEnough': False,
    'asamEnough': False,
    'nutrisiAEnough': False,
    'nutrisiBEnough': False
}


tls_params = aiomqtt.TLSParameters(
    ca_certs=None,
    certfile=None,
    keyfile=None,
    cert_reqs=ssl.CERT_REQUIRED,
    tls_version=ssl.PROTOCOL_TLS,
    ciphers=None,
)

client = None

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for actuator_name, actuator_pin in actuator.items():
    GPIO.setup(actuator_pin, GPIO.OUT)
    GPIO.output(actuator_pin, GPIO.LOW)

for sensor_name, sensor_pin in sensor.items():
    GPIO.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

async def test_baca():
    x, y = await asyncio.gather(
        pH_sensor.read_value(),
        EC_sensor.read_value()
    )
    print(x, y)


async def actuatorState(channel, pin):
    await client.publish("iterahero2023/actuator", json.dumps({str(pin): True if GPIO.input(pin) else False}))


def countPulse(channel, volume, relay_aktuator, pin_sensor, cairan):
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        print(f"Volume {cairan} yang keluar: {debit[cairan] / 216} L")
        if debit[cairan] / 216 >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
            peracikan_state[cairan + 'Enough'] = True


def kontrol_peracikan():
    GPIO.output(actuator["RELAY_AIR"], not (GPIO.input(actuator["RELAY_AIR"])))
    GPIO.output(actuator["RELAY_A"], not (GPIO.input(actuator["RELAY_A"])))
    GPIO.output(actuator["RELAY_B"], not (GPIO.input(actuator["RELAY_B"])))


def check_peracikan():
    air = GPIO.input(actuator["RELAY_AIR"])
    a = GPIO.input(actuator["RELAY_A"])
    b = GPIO.input(actuator["RELAY_B"])
    return air and a and b


async def penyiraman(pin_selenoid, durasi):
    GPIO.output(pin_selenoid, GPIO.HIGH)
    try:
        await asyncio.sleep(2)
        # await asyncio.sleep(durasi)
    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")
    finally:
        GPIO.output(pin_selenoid, GPIO.LOW)


def checkVAR(item):
    for var_names, var_value in item.items():
        print(f"{var_names} = {var_value}")


async def turn_off_peracikan():
    GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
    GPIO.remove_event_detect(sensor["WATERFLOW_A"])
    GPIO.remove_event_detect(sensor["WATERFLOW_B"])

    for actuator_name, actuator_pin in actuator.items():
        GPIO.output(actuator_pin, GPIO.LOW)

    relay_state = [{actuator["MOTOR_MIXING"]: bool(GPIO.input(actuator["MOTOR_MIXING"]))}, {str(actuator["RELAY_AIR"]): bool(GPIO.input(actuator["RELAY_AIR"]))}, {str(actuator["RELAY_A"]): bool(GPIO.input(
        actuator["RELAY_A"]))}, {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))}]
    await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya"}), qos=1)
    await client.publish("iterahero2023/actuator", json.dumps({"actuator": relay_state}), qos=1)
    print("Peracikan Selesai" if peracikan_state["airEnough"] else "Peracikan Dihentikan")


async def test_waterflow():
    GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, 0.7, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
    GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)

async def waterflow_manual():
    GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, 200, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))

async def peracikan(pH, ppm, volume_air, volume_a, volume_b, durasi=None, pin_selenoid=None):
    GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_air, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
    GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_a, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
    GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_b, actuator["RELAY_B"], sensor["WATERFLOW_B"], 'nutrisiB'))

    GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)
    GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
    GPIO.output(actuator["MOTOR_NUTRISI"], GPIO.HIGH)

    relay_state = [{str(actuator["RELAY_AIR"]): bool(GPIO.input(actuator["RELAY_AIR"]))}, {str(actuator["RELAY_A"]): bool(GPIO.input(
        actuator["RELAY_A"]))}, {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))}]
    await client.publish("iterahero2023/actuator", json.dumps({"actuator": relay_state}))

    while not (peracikan_state['airEnough']) and not (peracikan_state['asamEnough']) and not (peracikan_state['basaEnough']):
        print("Lagi ngeracik")
        await asyncio.sleep(0.7)

    GPIO.output(actuator["MOTOR_MIXING"], GPIO.LOW)
    GPIO.output(actuator["RELAY_AIR"], GPIO.LOW)
    GPIO.output(actuator["RELAY_A"], GPIO.LOW)
    GPIO.output(actuator["RELAY_B"], GPIO.LOW)
    GPIO.output(actuator["MOTOR_NUTRISI"], GPIO.LOW)

    #  temp_value
    ppm_value, ph_value, temp_value = await asyncio.gather(
        EC_sensor.read_value(),
        pH_sensor.read_value(),
        temp_sensor.read_value()
    )
    print(f"\npH Larutan: {ph_value}\nPPM Larutan: {ppm_value}\nSuhu Larutan: {temp_value}\n")

    # # VALIDASI PH
    # if 6.0 <= ph_value <= 7.0:
    #     print("PH aman")
    # else:
    #     # ada yang ditambahin asam / basa
    #     if ph_value < 6.2:
    #         print("Tambahin Basa")
    #         # Basa yang dibutuhin berapa
    #         # Basa = ....
    #         vol_basa = 0  # dummy
    #         GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
    #             channel, vol_basa, actuator["RELAY_BASA"], sensor["WATERFLOW_ASAM_BASA"], 'basa'))
    #     else:
    #         print("Tambahin asam")
    #         # Asam yang dibutuhin berapa
    #         # Asam = ....
    #         vol_asam = 0  # dummy
    #         GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
    #             channel, vol_asam, actuator["RELAY_ASAM"], sensor["WATERFLOW_ASAM_BASA"], 'asam'))

    # # VALIDASI PPM
    # if ppm - 200 <= ppm_value <= ppm + 200:
    #     print("PPM Aman")
    # else:
    #     # ada yang ditambahin air / nutrisi
    #     if ppm_value < 1000:
    #         print("Tambahin nutrisi")
    #         # 1mL : 1mL : 1L -> PPM nya naik 270
    #         # berarti vol_estimated = 1mL * volume naik ppmnya 270
    #         # ppm tambahan target / 270 * vol_estimated
    #         peracikan_state["nutrisiAEnough"] = False
    #         peracikan_state["nutrisiBEnough"] = False
    #         vol_nutrisi = ppm-ppm_value / 270 * (volume / 1000)
    #         GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
    #             channel, vol_nutrisi, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
    #         GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
    #             channel, vol_nutrisi, actuator["RELAY_B"], sensor["WATERFLOW_B"], 'nutrisiB'))
    #         while not(peracikan_state["nutrisiAEnough"]) and not(peracikan_state["nutrisiBEnough"]):\
    #             asyncio.sleep(0.1)
    #     else:
    #         print("Tambahin air")

    # await asyncio.create_task(penyiraman(pin_selenoid, durasi))
    await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada isinya"}), qos=1)

    if pin_selenoid and durasi:
        print("Bisa didistribusi nih coy")

    await turn_off_peracikan()
    peracikan_state.update((key, False) for key in peracikan_state)


async def publish_sensor(client):
    while True:
        ppm_value, ph_value, temp_value = await asyncio.gather(
        EC_sensor.read_value(),
        pH_sensor.read_value(),
        temp_sensor.read_value()
    )
        ph_value = ph_value if ph_value > 0 else 0
        ppm_value = ppm_value if ppm_value > 0 else 0
        temp_value = temp_value if temp_value > 0 else 0

        await client.publish("iterahero2023/info", json.dumps({"sensor_adc": [
            {str(sensor_adc[0]): round(ph_value, 2) }, {sensor_adc[1]: ppm_value}], "sensor_non_adc": [{str(sensor_non_adc[0]): round(temp_value, 2)}]}))
        await asyncio.sleep(2.5)


def on_off_actuator(pin):
    state = GPIO.input(pin)
    GPIO.output(pin, not(state))
    print('Nyala' if not(state) else 'Mati')


async def main():
    # Inisialisasi TLS parameter buat MQTT
    global client
    client = aiomqtt.Client(config["mqtt_broker"],
                            8883,
                            username=config["mqtt_username"],
                            password=config["mqtt_password"],
                            protocol=paho.MQTTv5,
                            tls_params=tls_params)
    async with client:
        print("MQTT Ready")
        await asyncio.sleep(0.2)
        asyncio.create_task(publish_sensor(client))
        async with client.messages() as messages:
            await client.subscribe("iterahero2023/#")
            async for message in messages:
                if message.topic.matches("iterahero2023/kontrol"):
                    data = json.loads(message.payload)
                    print(data['pin'])
                    on_off_actuator(data['pin'])
                if message.topic.matches("iterahero2023/waterflow"):
                    data = json.loads(message.payload)
                    print(data)
                    asyncio.create_task(test_waterflow())
                if message.topic.matches("iterahero2023/peracikan"):
                    x = check_peracikan()
                    if x:
                        print("Masih ada peracikan yang berjalan")
                    else:
                        data = json.loads(message.payload)
                        komposisi = data['komposisi']
                        await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Meracik " + komposisi['nama']}), qos=1)
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
                        asyncio.create_task(peracikan(
                            ph, ppm, volume_a=nutrisiA, volume_b=nutrisiB,
                            volume_air=air))

                if message.topic.matches("iterahero2023/penjadwalan-peracikan"):
                    x = check_peracikan()
                    if x:
                        print("Masih ada peracikan yang berjalan")
                    else:
                        try:
                            await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Peracikan"}), qos=1)
                            data = json.loads(message.payload)
                            komposisi = data['komposisi']
                            volume = komposisi['volume']
                            ph = komposisi['ph']
                            ppm = komposisi['ppm']
                            durasi = data['lamaPenyiraman']
                            konstanta = data['konstanta']

                            # Menimbang ada konstanta rasio A : B : Air, maka:
                            nutrisiA = round(
                                ppm / konstanta['ppm'] * konstanta['rasioA'] * volume / 1000, 3)
                            nutrisiB = round(
                                ppm / konstanta['ppm'] * konstanta['rasioB'] * volume / 1000, 3)
                            air = volume - (nutrisiA + nutrisiB)

                            # Print value variabel
                            # checkVAR(locals())

                            port = [aktuator['GPIO'] or aktuator['channel']
                                    for aktuator in data['aktuator']]
                            aktuator = [
                                value for value in port if value in actuator.values()]

                            if len(aktuator) < 1:
                                raise ValueError('Aktuator gaada')

                            asyncio.create_task(peracikan(
                                ph, ppm, volume_a=nutrisiA, volume_b=nutrisiB,
                                volume_air=air, durasi=durasi, pin_selenoid=aktuator))

                        except KeyError as e:
                            print(f"Gaada {e}")

                        except (ValueError, KeyboardInterrupt) as e:
                            print(f"{e}")

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        pH_sensor = SensorADC("Sensor pH DF Robot",
                              "y = -54.465x + 858.77", 0, "ph")
        EC_sensor = SensorADC("Sensor EC DF Robot",
                              "y = (0.043x + 13.663) - 60", 1, "ec")
        temp_sensor = SensorSuhu("Sensor Suhu DS18B20", "y = x - 1.63", 15)

        sensor_adc = [pH_sensor.channel, EC_sensor.channel]
        sensor_non_adc = [temp_sensor.GPIO]

        loop.run_until_complete(main())

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

        loop.run_until_complete(turn_off_peracikan())

        GPIO.cleanup()
        sys.exit()
