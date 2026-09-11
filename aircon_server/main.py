import json
import os
import secrets
import ssl
import threading
import time
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware


# ============================================================
# 環境変数
# ============================================================

load_dotenv()

MQTT_BROKER = os.environ["MQTT_BROKER"]
MQTT_PORT = 8883

MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]

APP_PASSWORD = os.environ["APP_PASSWORD"]
SESSION_SECRET = os.environ["SESSION_SECRET"]


# ============================================================
# MQTT Topic
# ============================================================

# FastAPI → D1 mini
MQTT_COMMAND_TOPIC = "yukimi/sg90"

# D1 mini → FastAPI
MQTT_STATUS_TOPIC = "yukimi/sg90/status"

# D1 mini 生存確認
MQTT_HEARTBEAT_TOPIC = "yukimi/sg90/heartbeat"


# ============================================================
# 状態
# ============================================================

latest_status = {
    "power": "UNKNOWN",
    "auto": "UNKNOWN",
    "message": "まだ状態を受信していません",
}

status_lock = threading.Lock()

mqtt_client = None

# Renderサーバ起動時刻
SERVER_START_TIME = time.time()

# D1 miniから最後に通信を受けた時刻
last_device_seen = None


# ============================================================
# MQTT 接続時
# ============================================================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties,
):
    print(
        "MQTT connected:",
        reason_code
    )

    if reason_code == 0:

        # 状態
        client.subscribe(
            MQTT_STATUS_TOPIC,
            qos=0,
        )

        # Heartbeat
        client.subscribe(
            MQTT_HEARTBEAT_TOPIC,
            qos=0,
        )

        print(
            "Subscribed:",
            MQTT_STATUS_TOPIC
        )

        print(
            "Subscribed:",
            MQTT_HEARTBEAT_TOPIC
        )


# ============================================================
# MQTT 切断時
# ============================================================

def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties,
):
    print(
        "MQTT disconnected:",
        reason_code
    )


# ============================================================
# MQTT メッセージ受信
# ============================================================

def on_message(
    client,
    userdata,
    msg,
):
    global latest_status
    global last_device_seen

    text = msg.payload.decode(
        "utf-8",
        errors="replace"
    )

    print(
        "MQTT RX:",
        msg.topic,
        text
    )

    # --------------------------------------------------------
    # Heartbeat
    # --------------------------------------------------------

    if msg.topic == MQTT_HEARTBEAT_TOPIC:

        last_device_seen = time.time()

        print(
            "D1 mini heartbeat received"
        )

        return


    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    if msg.topic == MQTT_STATUS_TOPIC:

        # 状態通知も生存確認として扱う
        last_device_seen = time.time()

        try:

            data = json.loads(
                text
            )

            new_status = {
                "power": str(
                    data.get(
                        "power",
                        "UNKNOWN"
                    )
                ),

                "auto": str(
                    data.get(
                        "auto",
                        "UNKNOWN"
                    )
                ),

                "message": str(
                    data.get(
                        "message",
                        ""
                    )
                ),
            }

        except Exception:

            # 古いマイコンなどが
            # JSONではなく文字列を返した場合
            new_status = {
                "power": "UNKNOWN",
                "auto": "UNKNOWN",
                "message": text,
            }

        with status_lock:

            latest_status = (
                new_status
            )


# ============================================================
# FastAPI 起動 / MQTT接続
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    global mqtt_client

    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2
    )

    # HiveMQ認証
    mqtt_client.username_pw_set(
        MQTT_USERNAME,
        MQTT_PASSWORD
    )

    # TLS
    mqtt_client.tls_set_context(
        ssl.create_default_context()
    )

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.on_disconnect = on_disconnect

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


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(
    title="Aircon Control Server",
    lifespan=lifespan,
)


# ============================================================
# セッション
# ============================================================

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    https_only=True,
    same_site="lax",
    max_age=60 * 60 * 24 * 30,
)


# ============================================================
# ログイン
# ============================================================

class LoginData(BaseModel):
    password: str


def require_login(
    request: Request
):
    if not request.session.get(
        "logged_in"
    ):
        raise HTTPException(
            status_code=401,
            detail="ログインしてください"
        )


# ============================================================
# /
# ============================================================

@app.get("/")
def root():

    return RedirectResponse(
        "/control"
    )


# ============================================================
# ログイン画面
# ============================================================

@app.get(
    "/login",
    response_class=HTMLResponse
)
def login_page(
    request: Request
):

    if request.session.get(
        "logged_in"
    ):
        return RedirectResponse(
            "/control"
        )

    return """
<!DOCTYPE html>
<html lang="ja">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>エアコン ログイン</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;

    min-height: 100vh;

    display: flex;
    justify-content: center;
    align-items: center;

    padding: 20px;

    background: #f5f7fb;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    color: #343946;
}

.card {
    width: 100%;
    max-width: 420px;

    padding: 35px 28px;

    background: white;

    border-radius: 28px;

    box-shadow:
        0 15px 45px
        rgba(0, 0, 0, 0.08);

    text-align: center;
}

.icon {
    width: 70px;
    height: 70px;

    margin:
        0 auto
        18px;

    display: flex;
    justify-content: center;
    align-items: center;

    border-radius: 22px;

    background: #edf2ff;

    font-size: 32px;
}

h1 {
    margin: 0 0 8px;
}

.description {
    color: #8991a3;

    margin-bottom: 25px;
}

input {
    width: 100%;

    padding: 17px;

    border:
        1px solid
        #e4e8f0;

    border-radius: 15px;

    font-size: 17px;

    outline: none;
}

button {
    width: 100%;

    margin-top: 15px;

    padding: 17px;

    border: none;

    border-radius: 15px;

    background: #a8bdf2;

    color: white;

    font-size: 18px;

    font-weight: bold;
}

#error {
    min-height: 24px;

    margin-top: 15px;

    color: #d36e79;
}

</style>

</head>

<body>

<div class="card">

<div class="icon">
❄️
</div>

<h1>
エアコン
</h1>

<div class="description">
共有パスワードを入力してください
</div>

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
        document
        .getElementById(
            "password"
        )
        .value;


    const response =
        await fetch(
            "/login",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify({
                        password: password
                    })
            }
        );


    if (response.ok) {

        location.href =
            "/control";

    } else {

        document
            .getElementById(
                "error"
            )
            .innerText =
                "パスワードが違います";
    }
}


document
    .getElementById(
        "password"
    )
    .addEventListener(
        "keydown",
        function(event) {

            if (
                event.key === "Enter"
            ) {
                login();
            }
        }
    );

</script>

</body>

</html>
"""


# ============================================================
# ログイン処理
# ============================================================

@app.post("/login")
def login(
    data: LoginData,
    request: Request,
):

    if not secrets.compare_digest(
        data.password,
        APP_PASSWORD
    ):

        raise HTTPException(
            status_code=401,
            detail="パスワードが違います"
        )

    request.session[
        "logged_in"
    ] = True

    return {
        "status": "ok"
    }


# ============================================================
# ログアウト
# ============================================================

@app.get("/logout")
def logout(
    request: Request
):

    request.session.clear()

    return RedirectResponse(
        "/login"
    )


# ============================================================
# MQTT Publish
# ============================================================

def send_mqtt(
    payload: str
):

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
        payload,
        qos=0
    )


    if (
        result.rc
        != mqtt.MQTT_ERR_SUCCESS
    ):

        raise HTTPException(
            status_code=500,
            detail="MQTT送信失敗"
        )


    print(
        "MQTT SEND:",
        MQTT_COMMAND_TOPIC,
        payload
    )


# ============================================================
# Status API
# ============================================================

@app.get("/status")
def get_status(
    request: Request
):

    require_login(
        request
    )

    with status_lock:

        current = (
            latest_status.copy()
        )

    return current


# ============================================================
# POWER
# ============================================================

@app.post("/power")
def power(
    request: Request
):

    require_login(
        request
    )

    send_mqtt(
        "power"
    )

    return {
        "status": "ok",
        "command": "power"
    }


# ============================================================
# AUTO ON
# ============================================================

@app.post("/auto-on")
def auto_on(
    request: Request
):

    require_login(
        request
    )

    send_mqtt(
        "auto_on"
    )

    return {
        "status": "ok",
        "command": "auto_on"
    }


# ============================================================
# AUTO OFF
# ============================================================

@app.post("/auto-off")
def auto_off(
    request: Request
):

    require_login(
        request
    )

    send_mqtt(
        "auto_off"
    )

    return {
        "status": "ok",
        "command": "auto_off"
    }


# ============================================================
# HEALTH API
# ============================================================

@app.get("/health")
def health(
    request: Request
):

    require_login(
        request
    )


    now = time.time()


    # --------------------------------------------------------
    # Render / FastAPI uptime
    # --------------------------------------------------------

    uptime_seconds = int(
        now
        - SERVER_START_TIME
    )


    # --------------------------------------------------------
    # MQTT Broker
    # --------------------------------------------------------

    mqtt_ok = (

        mqtt_client
        is not None

        and

        mqtt_client.is_connected()
    )


    # --------------------------------------------------------
    # D1 mini
    # --------------------------------------------------------

    device_online = False

    last_seen_seconds = None


    if last_device_seen is not None:

        last_seen_seconds = int(
            now
            - last_device_seen
        )

        # D1 miniは30秒に1回Heartbeat
        # 90秒以上来なければOFFLINE
        device_online = (
            last_seen_seconds
            < 90
        )


    with status_lock:

        current = (
            latest_status.copy()
        )


    return {

        "server":
            "online",

        "mqtt":
            "connected"
            if mqtt_ok
            else "disconnected",

        "device":
            "online"
            if device_online
            else "offline",

        "last_seen_seconds":
            last_seen_seconds,

        "uptime_seconds":
            uptime_seconds,

        "power":
            current.get(
                "power",
                "UNKNOWN"
            ),

        "auto":
            current.get(
                "auto",
                "UNKNOWN"
            ),

        "message":
            current.get(
                "message",
                ""
            ),
    }


# ============================================================
# 操作画面
# ============================================================

@app.get(
    "/control",
    response_class=HTMLResponse
)
def control(
    request: Request
):

    if not request.session.get(
        "logged_in"
    ):

        return RedirectResponse(
            "/login"
        )


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

    min-height: 100vh;

    padding: 20px;

    background: #f5f7fb;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    color: #343946;
}


.container {

    width: 100%;

    max-width: 460px;

    margin: auto;

    padding: 25px;

    background: white;

    border-radius: 28px;

    box-shadow:
        0 15px 45px
        rgba(0, 0, 0, 0.08);
}


h1 {

    text-align: center;

    margin-top: 5px;
}


.subtitle {

    text-align: center;

    color: #8991a3;

    margin-bottom: 25px;
}


.status-grid {

    display: grid;

    grid-template-columns:
        1fr 1fr;

    gap: 12px;

    margin-bottom: 15px;
}


.status-card {

    padding: 18px;

    background: #f7f8fc;

    border-radius: 18px;

    text-align: center;
}


.label {

    font-size: 12px;

    color: #8991a3;

    margin-bottom: 7px;
}


.value {

    font-size: 25px;

    font-weight: 800;
}


.message-box {

    padding: 17px;

    margin-bottom: 18px;

    background: #f7f8fc;

    border-radius: 18px;
}


.message-label {

    font-size: 12px;

    color: #8991a3;

    margin-bottom: 7px;
}


#messageStatus {

    font-weight: 700;

    line-height: 1.5;
}


button {

    width: 100%;

    padding: 18px;

    margin-bottom: 12px;

    border: none;

    border-radius: 17px;

    font-size: 19px;

    font-weight: 700;
}


.power {

    background: #bacaf2;

    color: #394152;
}


.auto-on {

    background: #c4e5cb;

    color: #394152;
}


.auto-off {

    background: #f1c7cc;

    color: #394152;
}


.health {

    margin-top: 12px;

    background: #ebeef5;

    color: #4d5565;

    font-size: 15px;
}


.logout {

    background: #f1f2f5;

    color: #656c79;

    font-size: 14px;
}


#commandStatus {

    min-height: 25px;

    margin-bottom: 12px;

    text-align: center;

    color: #687184;
}

</style>

</head>


<body>

<div class="container">

<h1>
エアコン操作
</h1>

<div class="subtitle">
Remote Air Conditioner
</div>


<div class="status-grid">

<div class="status-card">

<div class="label">
電源
</div>

<div
    id="powerStatus"
    class="value"
>
--
</div>

</div>


<div class="status-card">

<div class="label">
自動
</div>

<div
    id="autoStatus"
    class="value"
>
--
</div>

</div>

</div>


<div class="message-box">

<div class="message-label">
現在の状態
</div>

<div id="messageStatus">
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
    class="auto-on"
    onclick="sendCommand('/auto-on')"
>
AUTO ON
</button>


<button
    class="auto-off"
    onclick="sendCommand('/auto-off')"
>
AUTO OFF
</button>


<div id="commandStatus">
待機中
</div>


<button
    class="health"
    onclick="location.href='/health-page'"
>
システム状況
</button>


<button
    class="logout"
    onclick="location.href='/logout'"
>
ログアウト
</button>

</div>


<script>

async function sendCommand(
    path
) {

    const commandStatus =
        document
            .getElementById(
                "commandStatus"
            );


    commandStatus.innerText =
        "送信中...";


    const response =
        await fetch(
            path,
            {
                method: "POST"
            }
        );


    if (
        response.status
        === 401
    ) {

        location.href =
            "/login";

        return;
    }


    if (!response.ok) {

        commandStatus.innerText =
            "送信失敗";

        return;
    }


    const data =
        await response.json();


    commandStatus.innerText =
        "送信成功: "
        + data.command;


    setTimeout(
        updateStatus,
        300
    );
}


async function updateStatus() {

    const response =
        await fetch(
            "/status"
        );


    if (
        response.status
        === 401
    ) {

        location.href =
            "/login";

        return;
    }


    if (!response.ok) {

        return;
    }


    const data =
        await response.json();


    document
        .getElementById(
            "powerStatus"
        )
        .innerText =
            data.power;


    document
        .getElementById(
            "autoStatus"
        )
        .innerText =
            data.auto;


    document
        .getElementById(
            "messageStatus"
        )
        .innerText =
            data.message;
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


# ============================================================
# システム状況画面
# ============================================================

@app.get(
    "/health-page",
    response_class=HTMLResponse
)
def health_page(
    request: Request
):

    if not request.session.get(
        "logged_in"
    ):

        return RedirectResponse(
            "/login"
        )


    return """
<!DOCTYPE html>
<html lang="ja">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>システム状況</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    min-height: 100vh;

    padding: 20px;

    background: #f5f7fb;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    color: #343946;
}


.container {

    width: 100%;

    max-width: 460px;

    margin: auto;

    padding: 25px;

    background: white;

    border-radius: 28px;

    box-shadow:
        0 15px 45px
        rgba(0,0,0,0.08);
}


h1 {

    text-align: center;

    margin:
        5px 0
        25px;
}


.item {

    display: flex;

    justify-content:
        space-between;

    align-items: center;

    padding:
        18px 4px;

    border-bottom:
        1px solid #edf0f5;
}


.label {

    color: #7b8392;
}


.value {

    font-weight: 700;
}


.online {

    color: #63a876;
}


.offline {

    color: #cf7079;
}


.status-grid {

    display: grid;

    grid-template-columns:
        1fr 1fr;

    gap: 12px;

    margin-top: 20px;
}


.status-card {

    padding: 17px;

    background: #f7f8fc;

    border-radius: 17px;

    text-align: center;
}


.status-label {

    color: #8991a3;

    font-size: 12px;

    margin-bottom: 7px;
}


.status-value {

    font-size: 25px;

    font-weight: 800;
}


.message {

    margin-top: 15px;

    padding: 16px;

    background: #f7f8fc;

    border-radius: 17px;

    line-height: 1.5;

    color: #5e6675;
}


button {

    width: 100%;

    margin-top: 22px;

    padding: 15px;

    border: none;

    border-radius: 15px;

    background: #e9edf5;

    color: #4c5565;

    font-size: 15px;
}

</style>

</head>


<body>

<div class="container">

<h1>
システム状況
</h1>


<div class="item">

<span class="label">
Web Server
</span>

<span
    id="server"
    class="value"
>
--
</span>

</div>


<div class="item">

<span class="label">
MQTT Broker
</span>

<span
    id="mqtt"
    class="value"
>
--
</span>

</div>


<div class="item">

<span class="label">
D1 mini
</span>

<span
    id="device"
    class="value"
>
--
</span>

</div>


<div class="item">

<span class="label">
最終確認
</span>

<span
    id="lastSeen"
    class="value"
>
--
</span>

</div>


<div class="item">

<span class="label">
Server Uptime
</span>

<span
    id="uptime"
    class="value"
>
--
</span>

</div>


<div class="status-grid">

<div class="status-card">

<div class="status-label">
電源
</div>

<div
    id="power"
    class="status-value"
>
--
</div>

</div>


<div class="status-card">

<div class="status-label">
自動
</div>

<div
    id="auto"
    class="status-value"
>
--
</div>

</div>

</div>


<div
    id="message"
    class="message"
>
--
</div>


<button
    onclick="location.href='/control'"
>
操作画面へ戻る
</button>


</div>


<script>


function setColor(
    element,
    good
) {

    element.classList.remove(
        "online",
        "offline"
    );


    element.classList.add(
        good
        ? "online"
        : "offline"
    );
}


function formatUptime(
    seconds
) {

    const days =
        Math.floor(
            seconds
            / 86400
        );


    const hours =
        Math.floor(
            (seconds % 86400)
            / 3600
        );


    const minutes =
        Math.floor(
            (seconds % 3600)
            / 60
        );


    if (days > 0) {

        return (
            days
            + "日 "
            + hours
            + "時間 "
            + minutes
            + "分"
        );
    }


    return (
        hours
        + "時間 "
        + minutes
        + "分"
    );
}


async function updateHealth() {

    const response =
        await fetch(
            "/health"
        );


    if (
        response.status
        === 401
    ) {

        location.href =
            "/login";

        return;
    }


    if (!response.ok) {

        return;
    }


    const data =
        await response.json();


    # server

    const server =
        document
            .getElementById(
                "server"
            );


    server.innerText =
        "● ONLINE";


    setColor(
        server,
        true
    );


    # MQTT

    const mqtt =
        document
            .getElementById(
                "mqtt"
            );


    const mqttOk =
        data.mqtt
        ===
        "connected";


    mqtt.innerText =
        mqttOk
        ? "● CONNECTED"
        : "● DISCONNECTED";


    setColor(
        mqtt,
        mqttOk
    );


    # Device

    const device =
        document
            .getElementById(
                "device"
            );


    const deviceOk =
        data.device
        ===
        "online";


    device.innerText =
        deviceOk
        ? "● ONLINE"
        : "● OFFLINE";


    setColor(
        device,
        deviceOk
    );


    # Last Seen

    const lastSeen =
        document
            .getElementById(
                "lastSeen"
            );


    if (
        data.last_seen_seconds
        === null
    ) {

        lastSeen.innerText =
            "未受信";

    } else {

        lastSeen.innerText =
            data.last_seen_seconds
            + "秒前";
    }


    # Uptime

    document
        .getElementById(
            "uptime"
        )
        .innerText =
            formatUptime(
                data.uptime_seconds
            );


    # Power

    document
        .getElementById(
            "power"
        )
        .innerText =
            data.power;


    # Auto

    document
        .getElementById(
            "auto"
        )
        .innerText =
            data.auto;


    # Message

    document
        .getElementById(
            "message"
        )
        .innerText =
            data.message;
}


updateHealth();


setInterval(
    updateHealth,
    5000
);

</script>

</body>

</html>
"""