import os
import ssl
import secrets
import threading
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
import paho.mqtt.client as mqtt


load_dotenv()

# =========================
# 設定
# =========================

MQTT_BROKER = os.environ["MQTT_BROKER"]
MQTT_PORT = 8883
MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]

MQTT_COMMAND_TOPIC = "yukimi/sg90"
MQTT_STATUS_TOPIC = "yukimi/sg90/status"

APP_PASSWORD = os.environ["APP_PASSWORD"]
SESSION_SECRET = os.environ["SESSION_SECRET"]

latest_status = "まだ状態を受信していません"
status_lock = threading.Lock()

mqtt_client = None


# =========================
# MQTT
# =========================

def on_connect(client, userdata, flags, reason_code, properties):
    print("MQTT connected:", reason_code)

    if reason_code == 0:
        client.subscribe(MQTT_STATUS_TOPIC)
        print("Subscribed:", MQTT_STATUS_TOPIC)


def on_message(client, userdata, msg):
    global latest_status

    text = msg.payload.decode("utf-8", errors="replace")

    print("STATUS RECEIVED:", text)

    with status_lock:
        latest_status = text


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt_client

    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2
    )

    mqtt_client.username_pw_set(
        MQTT_USERNAME,
        MQTT_PASSWORD
    )

    mqtt_client.tls_set_context(
        ssl.create_default_context()
    )

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    print("Connecting MQTT:", MQTT_BROKER, MQTT_PORT)

    mqtt_client.connect(
        MQTT_BROKER,
        MQTT_PORT,
        60
    )

    mqtt_client.loop_start()

    yield

    mqtt_client.loop_stop()
    mqtt_client.disconnect()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    https_only=True,
    same_site="lax",
    max_age=60 * 60 * 24 * 30
)


# =========================
# 認証
# =========================

class LoginData(BaseModel):
    password: str


def require_login(request: Request):
    if not request.session.get("logged_in"):
        raise HTTPException(
            status_code=401,
            detail="ログインしてください"
        )


@app.get("/")
def root():
    return RedirectResponse("/control")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):

    if request.session.get("logged_in"):
        return RedirectResponse("/control")

    return """
<!DOCTYPE html>
<html lang="ja">

<head>
<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>エアコンログイン</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 30px 20px;
    background: #f5f5f7;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}

.container {
    max-width: 420px;
    margin: 80px auto;
    padding: 35px;
    background: white;
    border-radius: 25px;
    text-align: center;
    box-shadow: 0 8px 30px rgba(0,0,0,0.08);
}

h1 {
    margin-bottom: 35px;
}

input {
    width: 100%;
    padding: 18px;
    font-size: 18px;
    border: 1px solid #ccc;
    border-radius: 14px;
    margin-bottom: 20px;
}

button {
    width: 100%;
    padding: 18px;
    border: none;
    border-radius: 14px;
    background: #4f7ee8;
    color: white;
    font-size: 20px;
}

#error {
    margin-top: 20px;
    color: red;
}

</style>
</head>

<body>

<div class="container">

<h1>エアコン</h1>

<input
    id="password"
    type="password"
    placeholder="パスワード"
>

<button onclick="login()">
ログイン
</button>

<div id="error"></div>

</div>


<script>

async function login() {

    const password =
        document.getElementById("password").value;

    const response =
        await fetch("/login", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                password: password
            })
        });


    if (response.ok) {

        location.href = "/control";

    } else {

        document.getElementById("error").innerText =
            "パスワードが違います";

    }
}


document
    .getElementById("password")
    .addEventListener("keydown", function(event) {

        if (event.key === "Enter") {
            login();
        }

    });

</script>

</body>
</html>
"""


@app.post("/login")
def login(data: LoginData, request: Request):

    if not secrets.compare_digest(
        data.password,
        APP_PASSWORD
    ):
        raise HTTPException(
            status_code=401,
            detail="パスワードが違います"
        )

    request.session["logged_in"] = True

    return {
        "status": "ok"
    }


@app.get("/logout")
def logout(request: Request):

    request.session.clear()

    return RedirectResponse("/login")


# =========================
# エアコン API
# =========================

def send_mqtt(payload: str):

    if mqtt_client is None:
        raise HTTPException(
            status_code=503,
            detail="MQTT接続準備中"
        )

    if not mqtt_client.is_connected():
        raise HTTPException(
            status_code=503,
            detail="MQTTに接続されていません"
        )

    result = mqtt_client.publish(
        MQTT_COMMAND_TOPIC,
        payload
    )

    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise HTTPException(
            status_code=500,
            detail="MQTT送信失敗"
        )

    print("MQTT SEND:", payload)


@app.get("/status")
def get_status(request: Request):

    require_login(request)

    with status_lock:
        status = latest_status

    return {
        "status": status
    }


@app.post("/power")
def power(request: Request):

    require_login(request)

    send_mqtt("power")

    return {
        "status": "ok",
        "command": "power"
    }


@app.post("/auto-on")
def auto_on(request: Request):

    require_login(request)

    send_mqtt("auto_on")

    return {
        "status": "ok",
        "command": "auto_on"
    }


@app.post("/auto-off")
def auto_off(request: Request):

    require_login(request)

    send_mqtt("auto_off")

    return {
        "status": "ok",
        "command": "auto_off"
    }


# =========================
# 操作画面
# =========================

@app.get("/control", response_class=HTMLResponse)
def control(request: Request):

    if not request.session.get("logged_in"):
        return RedirectResponse("/login")

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
    margin: 0;
    padding: 30px 20px;
    background: #f5f5f7;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}

.container {
    max-width: 420px;
    margin: auto;
    padding: 30px;
    background: white;
    border-radius: 25px;
    text-align: center;
    box-shadow: 0 8px 30px rgba(0,0,0,0.08);
}

h1 {
    margin-bottom: 30px;
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
}

button {
    width: 100%;
    padding: 20px;
    margin: 10px 0;
    border: none;
    border-radius: 16px;
    font-size: 20px;
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

.logout {
    margin-top: 30px;
    background: #ddd;
    color: black;
    font-size: 15px;
    padding: 12px;
}

#commandStatus {
    margin-top: 20px;
}

</style>

</head>


<body>

<div class="container">

<h1>エアコン操作</h1>

<div class="current-status">

    <div class="status-title">
        現在の状態
    </div>

    <div id="deviceStatus">
        読み込み中...
    </div>

</div>


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


<button
    class="logout"
    onclick="location.href='/logout'"
>
ログアウト
</button>

</div>


<script>

async function sendCommand(path) {

    const status =
        document.getElementById("commandStatus");

    status.innerText = "送信中...";

    const response =
        await fetch(path, {
            method: "POST"
        });


    if (response.status === 401) {
        location.href = "/login";
        return;
    }


    if (!response.ok) {
        status.innerText = "送信失敗";
        return;
    }


    const data = await response.json();

    status.innerText =
        "送信成功: " + data.command;
}


async function updateStatus() {

    const response =
        await fetch("/status");


    if (response.status === 401) {
        location.href = "/login";
        return;
    }


    if (!response.ok) {
        return;
    }


    const data = await response.json();

    document
        .getElementById("deviceStatus")
        .innerText = data.status;
}


updateStatus();

setInterval(
    updateStatus,
    1000
);

</script>

</body>
</html>
"""