import os
import math
from random import randint, uniform
import ssl
import sys
import json
import asyncio
import time
import aiomqtt

import RPi.GPIO as GPIO
import paho.mqtt.client as paho

from sensor.Sensor import SensorADC, SensorSuhu, SensorWaterflow

with open(os.path.dirname(__file__) + "/config.json") as config_file:
    config_str = config_file.read()
    config = json.loads(config_str)

# DEKLARASI PIN  DAN VARIABEL #
actuator = {
    "RELAY_AIR": 5,
    "RELAY_A": 17,
    "RELAY_B": 2,
    "RELAY_ASAM": 20,
    "RELAY_BASA": 22,
    "RELAY_DISTRIBUSI": 6,
    "MOTOR_MIXING": 16,
    "MOTOR_NUTRISI": 25,
}

isi = {"tandon": 0}

sensor = {
    "WATERFLOW_A": 13,
    "WATERFLOW_B": 26,
    "WATERFLOW_ASAM_BASA": 18,
    "WATERFLOW_AIR": 24,
}

debit = {"air": 0, "asam": 0, "basa": 0, "distribusi": 0, "nutrisiA": 0, "nutrisiB": 0}

volume = {"nutrisiA": 0, "nutrisiB": 0, "air": 0, "asam": 0, "basa": 0}

peracikan_state = {
    "airEnough": False,
    "basaEnough": False,
    "asamEnough": False,
    "nutrisiAEnough": False,
    "nutrisiBEnough": False,
}

distribusi_start, distribusi_update = 0
a_start, a_update = 0
b_start, b_update = 0
air_start, air_update = 0


tls_params = aiomqtt.TLSParameters(
    ca_certs=None,
    certfile=None,
    keyfile=None,
    cert_reqs=ssl.CERT_NONE,
    tls_version=ssl.PROTOCOL_TLS,
    ciphers=None,
)

MQTT = None
NAME = "Raspberry Pi 4 B Peracikan"

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for actuator_name, actuator_pin in actuator.items():
    GPIO.setup(actuator_pin, GPIO.OUT)
    GPIO.output(actuator_pin, GPIO.LOW)

for sensor_name, sensor_pin in sensor.items():
    GPIO.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def countPulse(channel, volume, relay_aktuator, pin_sensor, cairan):
    """
    Menghtung volume yang keluar dari waterflow
    args:
        volume: volume target yang ingin dikeluarkan
        relay_aktuator: pin relay untuk mengontrol aktuator
        pin_sensor: pin sensor yang digunakan
        cairan: cairan yang dikeluarkan
        distribusi: apakah peracikan untuk distribusi
    """
    global distribusi_start, distribusi_update, air_start, air_update, a_start, a_update, b_start, b_update
    
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        volume[cairan] = debit[cairan] / 378
        if volume[cairan] >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            if cairan == "air":
                start_time = air_start
            elif cairan == "nutrisiB":
                start_time = b_start
            elif cairan == "nutiriA":
                start_time = a_start
            peracikan_state[cairan + "Enough"] = True
            print(f"{volume} L membutuhkan waktu {time.time() - start_time} ")
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
        if debit[cairan] % 75 == 0:
            print(f"Volume {cairan} yang keluar: {volume[cairan]}")


def countPulseManual(channel, relay_aktuator, pin_sensor, cairan):
    """
    Menghitung debit waterflow
    """
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        if debit[cairan] % 75 == 0:
            print(f"Volume {cairan} yang keluar: {debit[cairan]}")


def kontrol_peracikan(state=False, mix=False):
    """
    Mengontrol aktuator peracikan
    args:
        state: true jika ingin menyalakan, false untuk mematikan
        mix: apakah motor berputar
    """
    control = GPIO.HIGH if state else GPIO.LOW
    GPIO.output(actuator["RELAY_AIR"], control)
    GPIO.output(actuator["RELAY_A"], control)
    GPIO.output(actuator["RELAY_B"], control)
    if mix:
        GPIO.output(actuator["MOTOR_MIXING"], control)


def check_peracikan():
    """
    Mengecek apakah peracikan sedang berjalan
    """
    air = GPIO.input(actuator["RELAY_AIR"])
    a = GPIO.input(actuator["RELAY_A"])
    b = GPIO.input(actuator["RELAY_B"])
    motor = GPIO.input(actuator["MOTOR_MIXING"])
    return air or a or b or motor


def checkVAR(item):
    """
    Mengecek data variabel untuk debugging resep peracikan
    """
    for var_names, var_value in item.items():
        print(f"{var_names} = {var_value}")


def turn_off_actuator():
    """
    Mematikan semua aktuator
    """
    for actuator_name, actuator_pin in actuator.items():
        GPIO.output(actuator_pin, GPIO.LOW)


async def stop_peracikan():
    """
    Menghentikan peracikan
    """
    GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
    GPIO.remove_event_detect(sensor["WATERFLOW_A"])
    GPIO.remove_event_detect(sensor["WATERFLOW_B"])

    isi["tandon"] += volume["air"] + volume["nutrisiA"] + volume["nutrisiB"]
    volume.update((key, 0) for key in volume)
    debit.update((key, 0) for key in debit)

    peracikan_state.update((key, False) for key in peracikan_state)
    debit.update((key, 0) for key in debit)
    kontrol_peracikan(mix=True)

    print(
        "Peracikan Selesai" if peracikan_state["airEnough"] else "Peracikan Dihentikan"
    )

    relay_state = [
        {str(actuator["MOTOR_MIXING"]): bool(GPIO.input(actuator["MOTOR_MIXING"]))},
        {str(actuator["RELAY_AIR"]): bool(GPIO.input(actuator["RELAY_AIR"]))},
        {str(actuator["RELAY_A"]): bool(GPIO.input(actuator["RELAY_A"]))},
        {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))},
    ]

    await asyncio.gather(
        MQTT.publish(
            "iterahero2023/peracikan/info",
            json.dumps(
                {
                    "status": "Berisi nutrisi",
                    "volume": isi["tandon"],
                    "microcontrollerName": NAME,
                }
            ),
            qos=1,
        ),
        MQTT.publish(
            "iterahero2023/actuator",
            json.dumps({"actuator": relay_state, "microcontrollerName": NAME}),
            qos=1,
        ),
    )


async def test_waterflow(volume, cairan):
    """
    Trial and error waterflow
    args:
        volume: volume target yang ingin dikeluarkan
        cairan: cairan yang dikeluarkan
    """
    global distribusi_start, distribusi_update, air_start, air_update, a_start, a_update, b_start, b_update
    if cairan == "air":
        GPIO.add_event_detect(
            sensor["WATERFLOW_AIR"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel, volume, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], cairan
            ),
        )
        air_start = time.time()
        air_update = air_start
        GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    elif cairan == "nutrisiA":
        GPIO.add_event_detect(
            sensor["WATERFLOW_A"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel, volume, actuator["RELAY_A"], sensor["WATERFLOW_A"], cairan
            ),
        )
        a_start = time.time()
        a_update = a_start
        GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    elif cairan == "nutrisiB":
        GPIO.add_event_detect(
            sensor["WATERFLOW_B"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel, volume, actuator["RELAY_B"], sensor["WATERFLOW_B"], cairan
            ),
        )
        
        b_start = time.time()
        b_update = b_start
        GPIO.output(actuator["RELAY_B"], GPIO.HIGH)


async def validasi_ph(ph_min, ph_max, actual_ph):
    """
    Validasi PH nutrisi
    args:
        ph_min: nilai minimal dari ph target
        ph_max: nilai maksimal dari ph target
        actual_ph: nilai ph yang dibaca sensor
    """
    print("Validasi PH")
    if ph_min <= actual_ph <= ph_max:
        print("PH aman")
    else:
        if actual_ph < 6.2:
            print("Tambahin Basa")
            basa_tambahan = math.log10(1 / (10**-actual_ph)) / 0.1  # Belum final
            print(f"Perlu tambahan {basa_tambahan} mL basa")
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            # channel, vol_basa, actuator["RELAY_BASA"], sensor["WATERFLOW_ASAM_BASA"], 'basa'))
        else:
            print("Tambahin asam")
            asam_tambahan = (
                math.log10(1 / (10 ** -(14 - actual_ph))) / 0.1
            )  # belum final
            print(f"Perlu tambahan {asam_tambahan} mL asam")
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            #     channel, vol_asam, actuator["RELAY_ASAM"], sensor["WATERFLOW_ASAM_BASA"], 'asam'))


async def validasi_ppm(ppm_min, ppm_max, actual_ppm, konstanta, volume):
    print("Validasi PPM")
    if ppm_min <= actual_ppm <= ppm_max:
        print("PPM Aman")
    else:
        # ada yang ditambahin air / nutrisi
        GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)
        if actual_ppm < ppm_min - 200:
            print(f"Target ppm: {ppm_min} - {ppm_max}")
            print(f"Actual ppm: {actual_ppm}")

            nutrisi_tambahan_a = (
                (
                    (((ppm_min + ppm_max) / 2) * konstanta["rasioA"] / konstanta["ppm"])
                    - (actual_ppm * konstanta["rasioA"] / konstanta["ppm"])
                )
                / 1000
                * volume
            )
            nutrisi_tambahan_b = (
                (
                    (((ppm_min + ppm_max) / 2) * konstanta["rasioB"] / konstanta["ppm"])
                    - (actual_ppm * konstanta["rasioB"] / konstanta["ppm"])
                )
                / 1000
                * volume
            )

            print(f"Nutrisi A add: {nutrisi_tambahan_a}")
            print(f"Nutrisi B add: {nutrisi_tambahan_b}")

            # GPIO.add_event_detect(
            #     sensor["WATERFLOW_A"],
            #     GPIO.FALLING,
            #     callback=lambda channel: countPulse(
            #         channel,
            #         nutrisi_tambahan_a,
            #         actuator["RELAY_A"],
            #         sensor["WATERFLOW_A"],
            #         "nutrisiA",
            #     ),
            # )
            # GPIO.add_event_detect(
            #     sensor["WATERFLOW_B"],
            #     GPIO.FALLING,
            #     callback=lambda channel: countPulse(
            #         channel,
            #         nutrisi_tambahan_b,
            #         actuator["RELAY_B"],
            #         sensor["WATERFLOW_B"],
            #         "nutrisiB",
            #     ),
            # )

            # GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
            # GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
            # while not (peracikan_state['nutrisiAEnough']) or not (peracikan_state['nutrisiBEnough']):
            #     await asyncio.sleep(0.1)
        elif actual_ppm > ppm_max + 200:
            # Ngitung air yang mau ditambahin
            air_tambahan = (
                (
                    (actual_ppm * konstanta["rasioAir"] / konstanta["ppm"])
                    - (
                        ((ppm_min + ppm_max) / 2)
                        * konstanta["rasioAir"]
                        / konstanta["ppm"]
                    )
                )
                / 1000
                * volume
            )
            print(f"Air tambahan : {air_tambahan}")
            # GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
            #     channel, air_tambahan, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
            # GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
            # print("Tambahin air")
            # while not (peracikan_state['airEnough']):
            #     await asyncio.sleep(0.1)


async def validasi_peracikan():
    reason = []
    await asyncio.sleep(5)
    if debit["air"] < 10:
        reason.append(sensor["WATERFLOW_AIR"])
    if debit["nutrisiA"] < 10:
        reason.append(sensor["WATERFLOW_A"])
    if debit["nutrisiB"] < 10:
        reason.append(sensor["WATERFLOW_B"])

    valid = not bool(len(reason))

    return valid, reason


async def peracikan(
    ph_min,
    ph_max,
    ppm_min,
    ppm_max,
    volume_air,
    volume_a,
    volume_b,
    konstanta,
    volume,
    resep,
):
    """
    Melakukan peracikan nutrisi
    args:
        ph_min: target nilai ph_min nutrisi
        ph_max: target nilai ph_max nutrisi
        ppm_min: target nilai ppm_min nutrisi
        ppm_max: target nilai ppm_max nutrisi
        volume_air: volume air yang dibutuhkan
        volume_a: volume nutrisi A yang dibutuhkan
        volume_b: volume nutrisi B yang dibutuhkan
        kosntanta: konstanta pupuk yang digunakan
        volume: volume total nutrisi yang dibuat
        resep: nama resep dari nutrisi yang dibuat
    """
    try:
        GPIO.add_event_detect(
            sensor["WATERFLOW_AIR"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel,
                volume_air,
                actuator["RELAY_AIR"],
                sensor["WATERFLOW_AIR"],
                "air",
            ),
        )
        GPIO.add_event_detect(
            sensor["WATERFLOW_A"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel,
                volume_a,
                actuator["RELAY_A"],
                sensor["WATERFLOW_A"],
                "nutrisiA",
            ),
        )
        GPIO.add_event_detect(
            sensor["WATERFLOW_B"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel,
                volume_b,
                actuator["RELAY_B"],
                sensor["WATERFLOW_B"],
                "nutrisiB",
            ),
        )

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

        valid, reason = await validasi_peracikan()
        if valid:
            GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)

            relay_state = [
                {
                    str(actuator["MOTOR_MIXING"]): bool(
                        GPIO.input(actuator["MOTOR_MIXING"])
                    )
                },
                {str(actuator["RELAY_AIR"]): bool(GPIO.input(actuator["RELAY_AIR"]))},
                {str(actuator["RELAY_A"]): bool(GPIO.input(actuator["RELAY_A"]))},
                {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))},
            ]

            await MQTT.publish(
                "iterahero2023/actuator",
                json.dumps({"actuator": relay_state, "microcontrollerName": NAME}),
                qos=1,
            )

            logging_time = time.time()
            while (
                not (peracikan_state["airEnough"])
                or not (peracikan_state["nutrisiBEnough"])
                or not (peracikan_state["nutrisiAEnough"])
            ):
                if (time.time() - logging_time) >= 4:
                    await MQTT.publish(
                        "iterahero2023/peracikan/info",
                        json.dumps(
                            {
                                "status": f"Meracik {resep}",
                                "volume": isi["tandon"],
                                "microcontrollerName": NAME,
                            }
                        ),
                        qos=1,
                    )
                    print("Sedang melakukan peracikan nutrisi...")
                    logging_time = time.time()

            peracikan_state.update((key, False) for key in peracikan_state)

            kontrol_peracikan()

            ppm_value, ph_value, temp_value = await asyncio.gather(
                EC_sensor.read_value(), pH_sensor.read_value(), temp_sensor.read_value()
            )
            print(
                f"\npH Larutan: {ph_value}\nPPM Larutan: {ppm_value}\nSuhu Larutan: {temp_value}\n"
            )

            await asyncio.gather(
                validasi_ppm(ppm_min, ppm_max, ppm_value, konstanta, volume),
                validasi_ph(ph_min, ph_max, ph_value),
            )
        else:
            await MQTT.publish(
                "iterahero2023/peracikan/log",
                json.dumps(
                    {
                        "mikrokontroler": NAME,
                        "status": "terminated",
                        "sensor": reason,
                    }
                ),
            )
            print(f"Peracikan gagal karena waterflow bermasalah")

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

    finally:
        await MQTT.publish(
            "iterahero2023/peracikan/info",
            json.dumps(
                {
                    "status": f"Berisi pupuk {resep}",
                    "volume": isi["tandon"],
                    "microcontrollerName": NAME,
                }
            ),
            qos=1,
        )

        stop_peracikan()
        turn_off_actuator()


async def count_distribusi_nutrisi():
    """
    Menghitung volume nutrisi yang terdistribusi untuk mengurangnya dengan isi tandon
    """
    global distribusi_start, distribusi_update
    while True:
        if GPIO.input(actuator["RELAY_DISTRIBUSI"]) == GPIO.HIGH:
            now = time.time()
            isi["tandon"] -= (now - distribusi_update) * 0.1
            distribusi_update = now
            await asyncio.sleep(1)


async def volume_pompa_air():
    """
    Menghitung volume air yang mengisi tandon
    """
    global air_start, air_update
    while True:
        if GPIO.input(actuator["RELAY_AIR"]) == GPIO.HIGH:
            now = time.time()
            isi["tandon"] += (now - air_update) * 0.1
            air_update = now
            await asyncio.sleep(1)


async def volume_pompa_A():
    """
    Menghitung volume A yang mengisi tandon
    """
    global a_start, a_update
    while True:
        if GPIO.input(actuator["RELAY_A"]) == GPIO.HIGH:
            now = time.time()
            isi["tandon"] += (now - a_update) * 0.1
            a_update = now
            await asyncio.sleep(1)


async def volume_pompa_B():
    """
    Menghitung volume nutrisi B yang mengisi tandon
    """
    global b_start, b_update
    while True:
        if GPIO.input(actuator["RELAY_B"]) == GPIO.HIGH:
            now = time.time()
            isi["tandon"] += (now - b_update) * 0.1
            b_update = now
            await asyncio.sleep(1)


def on_off_actuator(pin):
    global distribusi_start, distribusi_update, air_start, air_update, a_start, a_update, b_start, b_update
    state = GPIO.input(pin)
    if not state:
        if pin == actuator["RELAY_DISTRIBUSI"]:
            distribusi_start = time.time()
            distribusi_update = distribusi_start
        elif pin == actuator["RELAY_AIR"]:
            GPIO.add_event_detect(
                sensor["WATERFLOW_AIR"],
                GPIO.FALLING,
                callback=lambda channel: countPulseManual(
                    channel,
                    actuator["RELAY_AIR"],
                    sensor["WATERFLOW_AIR"],
                    "air",
                ),
            )
            air_start = time.time()
            air_update = air_start

        elif pin == actuator["RELAY_A"]:
            GPIO.add_event_detect(
                sensor["WATERFLOW_A"],
                GPIO.FALLING,
                callback=lambda channel: countPulseManual(
                    channel,
                    actuator["RELAY_A"],
                    sensor["WATERFLOW_A"],
                    "nutrisiA",
                ),
            )
            a_start = time.time()
            a_update = a_start

        elif pin == actuator["RELAY_B"]:
            GPIO.add_event_detect(
                sensor["WATERFLOW_AIR"],
                GPIO.FALLING,
                callback=lambda channel: countPulseManual(
                    channel,
                    actuator["RELAY_AIR"],
                    sensor["WATERFLOW_B"],
                    "nutrisiB",
                ),
            )
            b_start = time.time()
            b_update = b_start
    else:
        if pin == actuator["RELAY_AIR"]:
            GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
            debit.update("air", 0)
        elif pin == actuator["RELAY_A"]:
            GPIO.remove_event_detect(sensor["WATERFLOW_A"])
            debit.update("nutrisiA", 0)
        elif pin == actuator["RELAY_B"]:
            GPIO.remove_event_detect(sensor["WATERFLOW_B"])
            debit.update("nurtisiB", 0)

    GPIO.output(pin, not (state))
    print("Mati" if state else "Nyala")


async def publish_sensor():
    while True:
        try:
            ppm_value, ph_value, temp_value = await asyncio.gather(
                EC_sensor.read_value(), pH_sensor.read_value(), temp_sensor.read_value()
            )

            print("======= INFO SENSOR ========")
            print(f"PH \t: {ph_value}")
            print(f"PPM \t: {ppm_value}")
            print(f"Suhu \t: {temp_value}")
            print("============================")
            print()

            ph_value = ph_value if ph_value > 0 else 0
            ppm_value = ppm_value if ppm_value > 0 else 0
            temp_value = temp_value if temp_value > 0 else 0
            debit_air = (
                (debit["air"] / 378) / (time.time() - air_start)
                if debit["air"] > 0
                else 0
            )
            debit_a = (
                (debit["nutrisiA"] / 378) / (time.time() - a_start)
                if debit["nutrisiA"] > 0
                else 0
            )
            debit_b = (
                (debit["nutrisiB"] / 378) / (time.time() - b_start)
                if debit["nutrisiB"] > 0
                else 0
            )

            await MQTT.publish(
                "iterahero2023/info/sensor",
                json.dumps(
                    {
                        "microcontrollerName": NAME,
                        "sensor_adc": [
                            {str(sensor_adc[0]): round(ph_value, 2) + 5},
                            {sensor_adc[1]: ppm_value},
                        ],
                        "sensor_non_adc": [
                            {str(sensor_non_adc[0]): round(temp_value, 2)},
                            {str(sensor_non_adc[1]): round(debit_air, 3)},
                            {str(sensor_non_adc[2]): round(debit_a, 3)},
                            {str(sensor_non_adc[3]): round(debit_b, 3)},
                        ],
                    }
                ),
                qos=1,
            )

        except (asyncio.CancelledError, KeyboardInterrupt):
            print("Publish Sensor dihentikan")


async def publish_actuator(halt=False):
    while True and not halt:
        try:
            data = []
            for key, value in actuator.items():
                data.append({value: GPIO.input(value)})
            await MQTT.publish(
                "iterahero2023/info/aktuator",
                json.dumps({"aktuator": data, "microcontrollerName": NAME}),
                qos=1,
            )
            await asyncio.sleep(1)

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            print(f"Publish Aktuator dihentikan{e}")
            break

    if halt:
        await MQTT.publish(
            "iterahero2023/info/aktuator",
            json.dumps({"aktuator": data, "microcontrollerName": NAME}),
            qos=1,
        )


async def publish_status():
    while True:
        try:
            await MQTT.publish(
                "iterahero2023/mikrokontroller/status",
                json.dumps({"mikrokontroler": NAME, "status": 1}),
                qos=1,
            )
            await asyncio.sleep(1)

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            print(f"Publish Status mikrokontroller dihentikan {e}")
            break


async def timerActuator(pin, duration):
    global distribusi_start, distribusi_update, air_start, air_update, a_start, a_update, b_start, b_update
    state = GPIO.input(pin)
    if state:
        print("Udah nyala")
    else:
        if pin == actuator["RELAY_DISTRIBUSI"]:
            distribusi_start = time.time()
            distribusi_update = distribusi_start
        elif pin == actuator["RELAY_AIR"]:
            air_start = time.time()
            air_update = air_start
        elif pin == actuator["RELAY_A"]:
            a_start = time.time()
            a_update = a_start
        elif pin == actuator["RELAY_B"]:
            b_start = time.time()
            b_update = b_start

        GPIO.output(pin, GPIO.HIGH)  # Nyala
        print("Nyala")
        await asyncio.sleep(duration * 60)
        GPIO.output(pin, GPIO.LOW)  # Mati


async def main():
    # Inisialisasi TLS parameter buat MQTT
    global MQTT
    # MQTT = aiomqtt.Client(config["mqtt_broker"],
    #                          8883,
    #                          username=config["mqtt_username"],
    #                          password=config["mqtt_password"],
    #                          protocol=paho.MQTTv5,
    #                          tls_params=tls_params,
    #                          keepalive=1800)
    MQTT = aiomqtt.Client(config["mqtt_broker_public"], 1883)
    MQTT.will_set("iterahero2023/mikrokontroller/status", json.dumps({"mikrokontroler": NAME, "status": 0}), qos=1, retain=True)
    
    while True:
        try:
            async with MQTT:
                try:
                    print("MQTT Ready")
                    await asyncio.sleep(0.2)
                    await MQTT.subscribe("iterahero2023/#")
                    asyncio.gather(
                        publish_sensor(),
                        publish_actuator(),
                        publish_status(),
                        count_distribusi_nutrisi(),
                        volume_pompa_air(),
                        volume_pompa_A(),
                        volume_pompa_B(),
                    )
                    async with MQTT.messages() as messages:
                        async for message in messages:
                            data = json.loads(message.payload)
                            print(data)
                            if message.topic.matches("iterahero2023/automation"):
                                if data["microcontroller"] == NAME:
                                    if data["pin"] and "durasi" in data:
                                        timerActuator(data["pin"], data["durasi"])
                                    elif data["pin"]:
                                        on_off_actuator(data["pin"])
                            if message.topic.matches("iterahero2023/kontrol"):
                                if data["pin"] and data["microcontroller"] == NAME:
                                    on_off_actuator(data["pin"])
                            if message.topic.matches("iterahero2023/waterflow"):
                                asyncio.create_task(
                                    test_waterflow(data["volume"], data["cairan"])
                                )
                            if message.topic.matches("iterahero2023/tandon/volume"):
                                if data["mikrokontroller"] == NAME:
                                    isi["tandon"] = data["volume"]
                            if (
                                message.topic.matches("iterahero2023/peracikan")
                                and data["konstanta"]["aktuator"][0]["microcontroller"][
                                    "name"
                                ]
                                == NAME
                            ):
                                x = check_peracikan()
                                if x:
                                    print("Masih ada peracikan yang berjalan")
                                else:
                                    komposisi = data["komposisi"]
                                    volume = komposisi["volume"]
                                    ph_min = komposisi["ph_min"]
                                    ph_max = komposisi["ph_max"]
                                    ppm_min = komposisi["ppm_min"]
                                    ppm_max = komposisi["ppm_max"]
                                    resep = komposisi["nama"]
                                    konstanta = data["konstanta"]
                                    print(konstanta)
                                    nutrisiA = round(
                                        ((ppm_min + ppm_max) / 2)
                                        / konstanta["ppm"]
                                        * konstanta["rasioA"]
                                        * volume
                                        / 1000,
                                        3,
                                    )
                                    nutrisiB = round(
                                        ((ppm_min + ppm_max) / 2)
                                        / konstanta["ppm"]
                                        * konstanta["rasioB"]
                                        * volume
                                        / 1000,
                                        3,
                                    )
                                    air = volume - (nutrisiA + nutrisiB)

                                    # Print value variabel
                                    checkVAR(locals())

                                    asyncio.create_task(
                                        peracikan(
                                            ph_min,
                                            ph_max,
                                            ppm_min,
                                            ppm_max,
                                            nutrisiA,
                                            nutrisiB,
                                            air,
                                            konstanta,
                                            volume,
                                            resep,
                                        )
                                    )
                            if (
                                message.topic_matches("iterahero2023/peracikan/cancel")
                                and data["microcontroller"] == NAME
                            ):
                                if check_peracikan():
                                    stop_peracikan()
                                    turn_off_actuator()

                except KeyError as e:
                    print(f"Gaada {e}")

                except (ValueError, KeyboardInterrupt, asyncio.CancelledError) as e:
                    print(f"{e}")

        except aiomqtt.MqttError:
            print(f"Connection lost; Reconnecting in {3} seconds ...")
            await asyncio.sleep(3)

        except KeyboardInterrupt:
            print("Koneksi MQTT dihentikan")
            break


if __name__ == "__main__":
    try:
        pH_sensor = SensorADC(
            "Sensor pH DF Robot", "1000 * voltage / 820 / 200 * 1.45", 0, "ph"
        )
        EC_sensor = SensorADC(
            "Sensor EC DF Robot", "y = (0.043x + 13.663) - 60", 1, "ec"
        )
        temp_sensor = SensorSuhu("Sensor Suhu DS18B20", "y = x - 1.63", 15)
        waterflow_air = SensorWaterflow(
            name="Waterflow Air",
            persamaan="y = (x / 378) - (time_now - time_start)",
            gpio=sensor["WATERFLOW_AIR"],
            pulse=378,
        )
        waterflow_a = SensorWaterflow(
            name="Waterflow A",
            persamaan="y = (x / 378) - (time_now - time_start)",
            gpio=sensor["WATERFLOW_A"],
            pulse=378,
        )
        waterflow_b = SensorWaterflow(
            name="Waterflow B",
            persamaan="y = (x / 378) - (time_now - time_start)",
            gpio=sensor["WATERFLOW_B"],
            pulse=378,
        )

        sensor_adc = [pH_sensor.channel, EC_sensor.channel]
        sensor_non_adc = [
            temp_sensor.GPIO,
            waterflow_air.GPIO,
            waterflow_a.GPIO,
            waterflow_b.GPIO,
        ]

        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

        loop.run_until_complete(
            MQTT.publish(
                "iterahero2023/peracikan/info",
                json.dumps(
                    {
                        "status": "Berisi nutrisi",
                        "volume": isi["tandon"],
                        "microcontrollerName": NAME,
                    }
                ),
                qos=1,
            )
        )

        if check_peracikan():
            loop.run_until_complete(stop_peracikan())
        else:
            print("Sistem Dihentikan")

        turn_off_actuator()
        loop.run_until_complete(publish_actuator(halt=True))

    finally:
        GPIO.cleanup()
        sys.exit()
