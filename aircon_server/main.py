import os
import ssl
import threading
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
import paho.mqtt.client as mqtt



# =========================
# MQTT 設定
# =========================

MQTT_BROKER = os.getenv(
    "MQTT_BROKER",
    "e9871b84c4a546cc863726db7c7efe07.s1.eu.hivemq.cloud"
)

MQTT_PORT = 8883

MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

MQTT_COMMAND_TOPIC = "yukimi/sg90"
MQTT_STATUS_TOPIC = "yukimi/sg90/status"


# =========================
# API 認証
# =========================

API_KEY = os.getenv("API_KEY", "test-secret")


# =========================
# 状態保存
# =========================

latest_status = "まだ状態を受信していません"

status_lock = threading.Lock()

mqtt_client = None


# =========================
# API Key チェック
# =========================

def check_api_key(x_api_key: str | None):

    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )


# =========================
# MQTT 接続時
# =========================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties
):

    print("MQTT connected:", reason_code)

    client.subscribe(
        MQTT_STATUS_TOPIC,
        qos=0
    )

    print(
        "Subscribed:",
        MQTT_STATUS_TOPIC
    )


# =========================
# MQTT切断時
# =========================

def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties
):

    print(
        "MQTT disconnected:",
        reason_code
    )


# =========================
# MQTTメッセージ受信
# =========================

def on_message(
    client,
    userdata,
    msg
):

    global latest_status

    text = msg.payload.decode(
        "utf-8",
        errors="replace"
    )

    print(
        "STATUS RECEIVED:",
        text
    )

    with status_lock:
        latest_status = text


# =========================
# FastAPI 起動 / 終了
# =========================

@asynccontextmanager
async def lifespan(app: FastAPI):

    global mqtt_client

    if not MQTT_USERNAME:
        raise RuntimeError(
            "MQTT_USERNAME が設定されていません"
        )

    if not MQTT_PASSWORD:
        raise RuntimeError(
            "MQTT_PASSWORD が設定されていません"
        )

    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2
    )

    # MQTTユーザー認証
    mqtt_client.username_pw_set(
        MQTT_USERNAME,
        MQTT_PASSWORD
    )

    # TLS
    ssl_context = ssl.create_default_context()

    mqtt_client.tls_set_context(
        ssl_context
    )

    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    mqtt_client.reconnect_delay_set(
        min_delay=1,
        max_delay=30
    )

    print(
        "Connecting MQTT:",
        MQTT_BROKER,
        MQTT_PORT
    )

    mqtt_client.connect(
        MQTT_BROKER,
        MQTT_PORT,
        60
    )

    mqtt_client.loop_start()

    yield

    mqtt_client.loop_stop()
    mqtt_client.disconnect()


# =========================
# FastAPI
# =========================

app = FastAPI(
    title="Aircon Server",
    lifespan=lifespan
)


# =========================
# MQTT送信
# =========================

def send_mqtt(payload: str):

    if mqtt_client is None:
        raise HTTPException(
            status_code=503,
            detail="MQTT client is not ready"
        )

    if not mqtt_client.is_connected():
        raise HTTPException(
            status_code=503,
            detail="MQTT broker is disconnected"
        )

    result = mqtt_client.publish(
        MQTT_COMMAND_TOPIC,
        payload,
        qos=0
    )

    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise HTTPException(
            status_code=500,
            detail="MQTT publish failed"
        )

    print(
        "MQTT SEND:",
        MQTT_COMMAND_TOPIC,
        payload
    )


# =========================
# 状態取得API
# =========================

@app.get("/status")
def get_status(
    x_api_key: str | None = Header(default=None)
):

    check_api_key(x_api_key)

    with status_lock:
        current = latest_status

    return {
        "status": current
    }


# =========================
# POWER
# =========================

@app.post("/power")
def power(
    x_api_key: str | None = Header(default=None)
):

    check_api_key(x_api_key)

    send_mqtt("power")

    return {
        "status": "ok",
        "command": "power"
    }


# =========================
# AUTO ON
# =========================

@app.post("/auto-on")
def auto_on(
    x_api_key: str | None = Header(default=None)
):

    check_api_key(x_api_key)

    send_mqtt("auto_on")

    return {
        "status": "ok",
        "command": "auto_on"
    }


# =========================
# AUTO OFF
# =========================

@app.post("/auto-off")
def auto_off(
    x_api_key: str | None = Header(default=None)
):

    check_api_key(x_api_key)

    send_mqtt("auto_off")

    return {
        "status": "ok",
        "command": "auto_off"
    }


# =========================
# スマホ操作画面
# =========================

@app.get(
    "/control",
    response_class=HTMLResponse
)
def control():

    return """
<!DOCTYPE html>

<html lang="ja">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>エアコン操作</title>

<style>

* {
    box-sizing: border-box;
}

body {
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    background: #f5f5f7;

    margin: 0;

    padding: 30px 20px;
}

.container {

    max-width: 420px;

    margin: auto;

    background: white;

    padding: 30px;

    border-radius: 25px;

    box-shadow:
        0 8px 30px
        rgba(0, 0, 0, 0.08);

    text-align: center;
}

h1 {

    margin-top: 10px;

    margin-bottom: 30px;

    font-size: 35px;
}

.current-status {

    background: #f2f2f7;

    padding: 20px;

    border-radius: 18px;

    margin-bottom: 25px;
}

.status-title {

    color: #777;

    font-size: 14px;

    margin-bottom: 10px;
}

#deviceStatus {

    font-size: 18px;

    font-weight: bold;

    line-height: 1.6;

    white-space: pre-wrap;
}

input {

    width: 100%;

    padding: 16px;

    font-size: 17px;

    border-radius: 12px;

    border: 1px solid #ccc;

    margin-bottom: 20px;
}

button {

    width: 100%;

    padding: 20px;

    margin: 10px 0;

    border: none;

    border-radius: 16px;

    font-size: 20px;

    cursor: pointer;

    transition: 0.1s;
}

button:active {

    transform: scale(0.97);
}

.power {

    background: #4f7ee8;

    color: white;
}

.on {

    background: #56a85c;

    color: white;
}

.off {

    background: #df4e3e;

    color: white;
}

#commandStatus {

    margin-top: 25px;

    font-size: 17px;
}

</style>

</head>

<body>

<div class="container">

<h1>
    エアコン操作
</h1>


<div class="current-status">

    <div class="status-title">
        現在の状態
    </div>

    <div id="deviceStatus">
        読み込み中...
    </div>

</div>


<input
    id="apiKey"
    type="password"
    placeholder="API Key"
>


<button
    class="power"
    onclick="sendCommand('/power')"
>
    POWER
</button>


<button
    class="on"
    onclick="sendCommand('/auto-on')"
>
    AUTO ON
</button>


<button
    class="off"
    onclick="sendCommand('/auto-off')"
>
    AUTO OFF
</button>


<div id="commandStatus">
    待機中
</div>

</div>


<script>


async function sendCommand(path) {

    const commandStatus =
        document.getElementById(
            "commandStatus"
        );

    const apiKey =
        document.getElementById(
            "apiKey"
        ).value;


    commandStatus.innerText =
        "送信中...";


    try {

        const response =
            await fetch(
                path,
                {
                    method: "POST",

                    headers: {
                        "x-api-key":
                            apiKey
                    }
                }
            );


        if (!response.ok) {

            const text =
                await response.text();

            commandStatus.innerText =
                "エラー: "
                + response.status;

            console.log(text);

            return;
        }


        const data =
            await response.json();


        commandStatus.innerText =
            "送信成功: "
            + data.command;


        setTimeout(
            updateStatus,
            500
        );

    }

    catch (error) {

        commandStatus.innerText =
            "通信エラー";

        console.error(error);
    }
}



async function updateStatus() {

    const deviceStatus =
        document.getElementById(
            "deviceStatus"
        );

    const apiKey =
        document.getElementById(
            "apiKey"
        ).value;


    if (!apiKey) {

        deviceStatus.innerText =
            "API Keyを入力してください";

        return;
    }


    try {

        const response =
            await fetch(
                "/status",
                {
                    headers: {
                        "x-api-key":
                            apiKey
                    }
                }
            );


        if (!response.ok) {

            deviceStatus.innerText =
                "状態取得エラー";

            return;
        }


        const data =
            await response.json();


        deviceStatus.innerText =
            data.status;

    }

    catch (error) {

        deviceStatus.innerText =
            "サーバーに接続できません";

    }
}


setInterval(
    updateStatus,
    1000
);


</script>


</body>

</html>
"""


# =========================
# 動作確認
# =========================

@app.get("/")
def root():

    return {
        "message":
            "Aircon Server is running",

        "control":
            "/control",

        "docs":
            "/docs"
    }