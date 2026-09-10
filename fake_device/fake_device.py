import os
import ssl

from dotenv import load_dotenv

load_dotenv()

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_BROKER")
USERNAME = os.getenv("MQTT_USERNAME")
PASSWORD = os.getenv("MQTT_PASSWORD")

COMMAND_TOPIC = "yukimi/sg90"
STATUS_TOPIC = "yukimi/sg90/status"


def on_connect(client, userdata, flags, reason_code, properties):
    print("connected:", reason_code)
    client.subscribe(COMMAND_TOPIC)


def on_message(client, userdata, msg):
    command = msg.payload.decode()

    print("受信:", command)

    if command == "power":
        status = "電源操作を受信"

    elif command == "auto_on":
        status = "自動モード: ON"

    elif command == "auto_off":
        status = "自動モード: OFF"

    else:
        status = "不明な命令"

    client.publish(
        STATUS_TOPIC,
        status
    )

    print("状態送信:", status)


client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2
)

client.username_pw_set(
    USERNAME,
    PASSWORD
)

client.tls_set_context(
    ssl.create_default_context()
)

client.on_connect = on_connect
client.on_message = on_message

client.connect(
    BROKER,
    8883,
    60
)

client.loop_forever()