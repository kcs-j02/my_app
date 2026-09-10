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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>エアコンログイン</title>

<style>
:root {
    --bg: #f7f8fc;
    --card: rgba(255, 255, 255, 0.92);
    --text: #2f3441;
    --sub: #7d8597;
    --line: #e6e9f2;
    --accent: #9fb8ff;
    --accent-strong: #7ea0ff;
    --shadow: 0 20px 50px rgba(115, 130, 170, 0.12);
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;
    padding: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    background:
        radial-gradient(circle at top left, #eef3ff 0%, transparent 35%),
        radial-gradient(circle at bottom right, #fceff4 0%, transparent 30%),
        var(--bg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: var(--text);
}

.card {
    width: 100%;
    max-width: 420px;
    background: var(--card);
    border: 1px solid rgba(255,255,255,0.7);
    backdrop-filter: blur(12px);
    border-radius: 28px;
    box-shadow: var(--shadow);
    padding: 36px 28px 30px;
    text-align: center;
}

.icon {
    width: 72px;
    height: 72px;
    margin: 0 auto 20px;
    border-radius: 24px;
    background: linear-gradient(135deg, #dfe8ff, #f5e8f2);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 34px;
}

h1 {
    margin: 0 0 8px;
    font-size: 32px;
    font-weight: 800;
    letter-spacing: 0.02em;
}

p {
    margin: 0 0 24px;
    color: var(--sub);
    font-size: 15px;
    line-height: 1.7;
}

.input-wrap {
    text-align: left;
    margin-bottom: 14px;
}

.label {
    font-size: 13px;
    color: var(--sub);
    margin-bottom: 8px;
    display: block;
}

input {
    width: 100%;
    padding: 16px 18px;
    border: 1px solid var(--line);
    border-radius: 16px;
    background: #fbfcff;
    font-size: 17px;
    outline: none;
    transition: 0.2s;
}

input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 4px rgba(159, 184, 255, 0.18);
    background: white;
}

button {
    width: 100%;
    margin-top: 8px;
    padding: 16px;
    border: none;
    border-radius: 16px;
    background: linear-gradient(135deg, #a8bcff, #8fafee);
    color: white;
    font-size: 18px;
    font-weight: 700;
    cursor: pointer;
    transition: 0.15s;
}

button:active {
    transform: scale(0.98);
}

#error {
    margin-top: 16px;
    min-height: 24px;
    font-size: 14px;
    color: #d96b7c;
}
</style>
</head>

<body>
<div class="card">
    <div class="icon">❄️</div>
    <h1>エアコン</h1>
    <p>共有パスワードを入力して<br>操作画面へ進んでください</p>

    <div class="input-wrap">
        <label class="label">パスワード</label>
        <input id="password" type="password" placeholder="パスワードを入力">
    </div>

    <button onclick="login()">ログイン</button>
    <div id="error"></div>
</div>

<script>
async function login() {
    const password = document.getElementById("password").value;

    const response = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: password })
    });

    if (response.ok) {
        location.href = "/control";
    } else {
        document.getElementById("error").innerText = "パスワードが違います";
    }
}

document.getElementById("password").addEventListener("keydown", function(event) {
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>エアコン操作</title>

<style>
:root {
    --bg: #f7f8fc;
    --card: rgba(255,255,255,0.94);
    --text: #2f3441;
    --sub: #7d8597;
    --line: #e8ebf3;
    --shadow: 0 20px 50px rgba(115, 130, 170, 0.12);

    --blue1: #b8c9ff;
    --blue2: #95afff;

    --green1: #bee7c5;
    --green2: #99d7a6;

    --pink1: #f7c6c6;
    --pink2: #efabab;

    --gray1: #eef1f7;
    --gray2: #e3e7f0;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;
    padding: 20px;
    background:
        radial-gradient(circle at top left, #eef3ff 0%, transparent 35%),
        radial-gradient(circle at bottom right, #fceff4 0%, transparent 28%),
        var(--bg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: var(--text);
}

.container {
    width: 100%;
    max-width: 460px;
    margin: 0 auto;
    background: var(--card);
    border: 1px solid rgba(255,255,255,0.75);
    backdrop-filter: blur(12px);
    border-radius: 30px;
    box-shadow: var(--shadow);
    padding: 26px 22px 22px;
}

.header {
    text-align: center;
    margin-bottom: 22px;
}

.header-icon {
    width: 70px;
    height: 70px;
    margin: 0 auto 14px;
    border-radius: 22px;
    background: linear-gradient(135deg, #dfe8ff, #f5e8f2);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 32px;
}

.header h1 {
    margin: 0;
    font-size: 32px;
    font-weight: 800;
    letter-spacing: 0.02em;
}

.header p {
    margin: 8px 0 0;
    font-size: 14px;
    color: var(--sub);
}

.status-panel {
    background: linear-gradient(135deg, #f8f9ff, #f6f5fb);
    border: 1px solid #eceef8;
    border-radius: 22px;
    padding: 20px 18px;
    margin-bottom: 18px;
}

.status-title {
    font-size: 13px;
    color: var(--sub);
    margin-bottom: 8px;
}

#deviceStatus {
    font-size: 22px;
    font-weight: 800;
    line-height: 1.6;
    word-break: break-word;
}

.note-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-bottom: 18px;
}

.note-card {
    background: #fbfcff;
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: 14px;
    text-align: center;
}

.note-label {
    font-size: 12px;
    color: var(--sub);
    margin-bottom: 6px;
}

.note-value {
    font-size: 16px;
    font-weight: 700;
}

.button-group {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

button {
    width: 100%;
    padding: 18px;
    border: none;
    border-radius: 18px;
    font-size: 21px;
    font-weight: 700;
    cursor: pointer;
    transition: 0.15s;
    color: #384055;
}

button:active {
    transform: scale(0.985);
}

.power {
    background: linear-gradient(135deg, var(--blue1), var(--blue2));
}

.on {
    background: linear-gradient(135deg, var(--green1), var(--green2));
}

.off {
    background: linear-gradient(135deg, var(--pink1), var(--pink2));
}

#commandStatus {
    margin-top: 18px;
    min-height: 24px;
    text-align: center;
    color: #5f6678;
    font-size: 15px;
}

.logout {
    margin-top: 18px;
    padding: 14px;
    font-size: 15px;
    background: linear-gradient(135deg, var(--gray1), var(--gray2));
    color: #4f5667;
}

.footer-note {
    margin-top: 14px;
    text-align: center;
    color: #97a0b3;
    font-size: 12px;
    line-height: 1.6;
}
</style>
</head>

<body>

<div class="container">

    <div class="header">
        <div class="header-icon">❄️</div>
        <h1>エアコン操作</h1>
        <p>やさしい色合いのシンプル操作画面</p>
    </div>

    <div class="status-panel">
        <div class="status-title">現在の状態</div>
        <div id="deviceStatus">読み込み中...</div>
    </div>

    <div class="note-row">
        <div class="note-card">
            <div class="note-label">接続</div>
            <div class="note-value">オンライン</div>
        </div>
        <div class="note-card">
            <div class="note-label">更新</div>
            <div class="note-value">1秒ごと</div>
        </div>
    </div>

    <div class="button-group">
        <button class="power" onclick="sendCommand('/power')">POWER</button>
        <button class="on" onclick="sendCommand('/auto-on')">AUTO ON</button>
        <button class="off" onclick="sendCommand('/auto-off')">AUTO OFF</button>
    </div>

    <div id="commandStatus">待機中</div>

    <button class="logout" onclick="location.href='/logout'">ログアウト</button>

    <div class="footer-note">
        状態は自動更新されます
    </div>
</div>

<script>
async function sendCommand(path) {
    const status = document.getElementById("commandStatus");
    status.innerText = "送信中...";

    const response = await fetch(path, {
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
    status.innerText = "送信成功: " + data.command;
}

async function updateStatus() {
    const response = await fetch("/status");

    if (response.status === 401) {
        location.href = "/login";
        return;
    }

    if (!response.ok) {
        return;
    }

    const data = await response.json();
    document.getElementById("deviceStatus").innerText = data.status;
}

updateStatus();
setInterval(updateStatus, 1000);
</script>

</body>
</html>
"""