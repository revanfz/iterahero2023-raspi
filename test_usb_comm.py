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

NAME = 'Raspi Mitra'

try:
    with open(os.path.dirname(__file__) + '/config.json') as config_file:
        config_str = config_file.read()
        config = json.loads(config_str)
except FileNotFoundError:
    print("file nya gaada")

async def readSensor():    
    def find_serial_port():
        ports = serial.tools.list_ports.comports()
        for port, desc, hwid in sorted(ports):
            if "USB" in desc:
                return port

        return None

    with serial.Serial(find_serial_port(), 115200) as ESP_ser:
        ESP_ser.flush()

        while True:
            try:
                if ESP_ser.in_waiting > 0:
                    data = ESP_ser.readline().decode('utf-8').rstrip()
                    json_data = json.loads(data)

                    temperature = json_data["temperature"]
                    ph = json_data["ph"]
                    ec = json_data["ec"]

                    print(f"Suhu: {temperature}\nEC: {ec}\npH: {ph}")
                await asyncio.sleep(1)
                    
            except json.JSONDecodeError as e:
                print(f"Gagal memparsing json : {e}")
                continue

            except UnicodeDecodeError as e:
                print(f"Error decoding data: {e}")
                continue

            except KeyError:
                print(f"Key yang diperlukan tidak ditemukan")
                continue

            except KeyboardInterrupt as e:
                print(f"Pembacaan sensor dihentikan")
                ESP_ser.close()
                break


async def main():
    # Inisialisasi TLS parameter buat MQTT
    global client
    client = aiomqtt.Client(config["mqtt_broker_public"], 1883)
        
    async with client:
        try:
            print("MQTT Ready")
            await asyncio.sleep(0.2)
            await client.subscribe("iterahero2023/#")
            # asyncio.create_task(publish_sensor(client))
            # asyncio.create_task(publish_actuator(client))
            asyncio.create_task(readSensor())
            async for messages in client.messages:
                async for message in messages:
                    data = json.loads(message.payload)
                    print(data)

        except KeyError as e:
            print(f"Gaada {e}")

        except (ValueError, KeyboardInterrupt) as e:
            print(f"{e}")

            
if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())

    except aiomqtt.MqttError as e:
        print(f"{e}")
        loop.run_until_complete(main())

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

        print("Sistem Dihentikan")

        sys.exit()
