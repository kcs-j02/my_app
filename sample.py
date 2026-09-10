import paho.mqtt.publish as publish

publish.single(
    topic="yukimi/sg90",
    payload="power",
    hostname="broker.hivemq.com",
    port=1883
)

print("送信しました")