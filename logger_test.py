import re
import time
import threading
import pyttsx3  # pip install pyttsx3
from flask import send_from_directory
import argparse
import os
from collections import defaultdict
import json
import datetime
import threading

from flask import Flask, Response, render_template_string

STATE_LOCK = threading.Lock()
RESET_HOUR = 2  # 2 AM

def load_state():
    global counters, CURRENT_OFFSET, CURRENT_INODE

    if not os.path.isfile(STATE_FILE):
        return

    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)

        today = datetime.date.today().isoformat()
        state_date = data.get("date")

        if state_date == today:
            for k, v in data.get("counters", {}).items():
                packet_type, color = k.split("|")
                counters[(packet_type, color)] = v

            CURRENT_OFFSET = data.get("offset", 0)
            CURRENT_INODE = data.get("inode")  # may be None

            print(
                f"[INFO] State loaded | inode={CURRENT_INODE} "
                f"offset={CURRENT_OFFSET}"
            )
        else:
            CURRENT_OFFSET = 0
            CURRENT_INODE = None
            print("[INFO] State ignored (new day)")

    except Exception as e:
        CURRENT_OFFSET = 0
        CURRENT_INODE = None
        print("[WARN] Failed to load state:", e)

def save_state():
    with STATE_LOCK:
        data = {
            "date": datetime.date.today().isoformat(),
            "inode": CURRENT_INODE,
            "offset": CURRENT_OFFSET,
            "counters": {
                f"{k[0]}|{k[1]}": v for k, v in counters.items()
            }
        }

        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)

        os.replace(tmp, STATE_FILE)

# -------------------- ARGUMENTS --------------------
parser = argparse.ArgumentParser(description="Live Tray Counter Dashboard")

parser.add_argument(
    "--conveyor",
    type=int,
    required=True,
    help="Conveyor number (e.g. 1, 2, 3)"
)

parser.add_argument(
    "--port",
    type=int,
    default=5000,
    help="Web server port (default: 5000)"
)

parser.add_argument(
    "--on-inode-change",
    choices=["begin", "end"],
    default="end",
    help="On log inode change: 'begin' = read from start, 'end' = jump to EOF (default: end)"
)

args = parser.parse_args()

IS_LIVE = False
STATE_FILE = f"tray_state_conveyor_{args.conveyor}.json"
CURRENT_OFFSET = 0
CURRENT_INODE = None
INODE_CHANGE_MODE = args.on_inode_change

# -------------------- LOG FILE RESOLUTION --------------------
LOG_FILE = os.path.expanduser(
    f"~/project/Bamul_Final/camera_{args.conveyor}.log"
)

if not os.path.isfile(LOG_FILE):
    raise FileNotFoundError(
        f"Log file not found for conveyor {args.conveyor}: {LOG_FILE}"
    )

print(f"[INFO] Monitoring conveyor {args.conveyor}")
print(f"[INFO] Log file: {LOG_FILE}")

# -------------------- REGEX --------------------
LOG_PATTERN = re.compile(
    r"(?:^.*?\|\s*)?FINALIZED Tray:\s*(\d+),\s*packet_type:\s*(\w+),\s*color:\s*(\w+),\s*packets:\s*(\d+)"
)

# -------------------- DATA STORE --------------------
# (packet_type, color) -> tray count
counters = defaultdict(int)

app = Flask(__name__)

# -------------------- AUDIO / TTS --------------------
# Developer-editable mappings: change these strings as you like.
# Example: PACKET_LABELS = {'half': 'ardha'} will make 'half' announced as 'ardha'.
PACKET_LABELS = {
    # 'half': 'ardha',
}

# Example: COLOR_LABELS = {'toned': 'tooned'}
COLOR_LABELS = {
    # 'toned': 'tooned',
}

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

def create_audio(packet_type, color):
    # Build filename using original packet/color (sanitized)
    safe_pkt = re.sub(r"\W+", "_", packet_type).lower()
    safe_col = re.sub(r"\W+", "_", color).lower()
    file_name = f"{safe_pkt}_{safe_col}.wav"
    file_path = os.path.join(AUDIO_DIR, file_name)

    if os.path.exists(file_path):
        return file_path

    # Apply developer mappings (fall back to original text)
    announce_pkt = PACKET_LABELS.get(packet_type.lower(), packet_type)
    announce_col = COLOR_LABELS.get(color.lower(), color)

    text = f"{announce_pkt} {announce_col}"

    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 150)
        engine.setProperty('volume', 1.0)
        engine.save_to_file(text, file_path)
        engine.runAndWait()
    except Exception as e:
        print('[WARN] TTS generation failed:', e)

    return file_path


@app.route('/audio/<filename>')
def audio_file(filename):
    return send_from_directory(AUDIO_DIR, filename)


@app.route('/logo/<filename>')
def logo_file(filename):
    # Serve logo images from the "logo" subfolder next to this script
    logo_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo")
    return send_from_directory(logo_dir, filename)

# -------------------- HTML --------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Live Tray Counter</title>
<style>
html, body {
    width: 100vw;
    height: 100vh;
    margin: 0;
    padding: 0;
    overflow: hidden;
    font-family: "Segoe UI", Arial, sans-serif;
    background: #eef2f7;
    display: grid;
    grid-template-rows: auto 1fr;
}

#flash {
    position: absolute;
    top: 4%;
    font-size: clamp(28px, 5vh, 70px);                 
    padding: clamp(12px, 2vh, 26px) clamp(24px, 4vw, 65px);
    border-radius: 20px;
    font-weight: 900;
    box-shadow: 0 10px 25px rgba(0,0,0,0.35);
    opacity: 0;
    transform: scale(0.92);
    transition: all 0.06s linear;
}

#flash.show {
    opacity: 1;
    transform: scale(1.02);
}

/* Header */
.topbar {
    width: 100%;              
    display: grid;            
    grid-template-columns: auto 1fr auto;
    align-items: center;
    margin-bottom: 8px;
}
.topbar .logo{max-height:64px;height:auto;width:auto}
.topbar .title{
    font-weight:900;
    font-size:clamp(28px, 3.5vh, 48px);
    color:#111827;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
    text-align:center;
}

/* Table */
table {
    border-collapse: collapse;
    width: 100%;
    max-width: 95vw;
    background: white;
    box-shadow: 0 16px 45px rgba(0,0,0,0.2);
    border-radius: 20px;
    border: 4px solid #000;
    table-layout: fixed;
}

thead {
    background: linear-gradient(90deg, #0f172a, #1e40af);
    color: white;
    border-bottom: 5px solid #000;
}

th, td {
    text-align: center;
    border: 3px solid #000;
    padding: clamp(6px, 1.5vh, 20px);
    vertical-align: middle;
    word-break: break-word;
}

th {
    font-size: clamp(18px, 2.6vh, 40px);
    letter-spacing: 1px;
}

/* Milk type column colors */
.col-milk.flash-shubham     { background: #f97316; color: white; }
.col-milk.flash-toned       { background: #2563eb; color: white; }
.col-milk.flash-nsp         { background: #16a34a; color: white; }
.col-milk.flash-homogenised { background: #86efac; color: black; }
.col-milk.flash-desi        { background: #7c3aed; color: white; }
.col-milk.flash-curd        { background: #fde047; color: #78350f; }
.col-milk.flash-samruddhi   { background: #ff1493; color: white; }
.col-milk.flash-ttm         { background: #000080; color: white; }

.col-milk {
    font-weight: 900;
    font-size: clamp(18px, 2.8vh, 42px);
    text-transform: uppercase;
}

.col-qty {
    font-weight: 800;
    color: #7c2d12;
}

.col-count {
    font-weight: 900;
    font-size: clamp(22px, 3.5vh, 48px);
    color: #1d4ed8;
}

/* Zebra striping */
tbody tr:nth-child(even) td {
    background-color: #f8fafc;
}

td[rowspan] {
    border-right: 5px solid #000;
}
</style>
</head>
<body>

<header class="topbar">
    <img src="/logo/bamullogo.jpg" alt="Bamul" class="logo">
    <div class="title">Bamul Live Crate Counter</div>
    <img src="/logo/kmfnandini.jpg" alt="Kmfnandhini" class="logo">
</header>

<div id="flash"></div>

<audio id="tts"></audio>

<main style="width:100%; display:flex; justify-content:center; align-items:flex-start;">
    <table id="counter-table">
        <thead>
            <tr>
                <th>Milk Type</th>
                <th>Quantity</th>
                <th>Trays</th>
            </tr>
        </thead>
        <tbody></tbody>
    </table>
</main>

<script>
const evtSource = new EventSource("/stream");
let lastEventId = null;

let preferredVoice = null;

function playSound(pkt,color){
    const fileName = `${pkt}_${color}.wav`.replace(/\s+/g,"_").toLowerCase();
    const audio = document.getElementById('tts');
    audio.src = `/audio/${fileName}?${Date.now()}`;
    audio.play().catch(()=>{});
}

evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);

    /* UPDATE TABLE */
    const tbody = document.querySelector("#counter-table tbody");
    tbody.innerHTML = "";

    /* GROUP BY MILK TYPE */
    const grouped = {};
    data.table.forEach(row => {
        if (!grouped[row.color]) grouped[row.color] = [];
        grouped[row.color].push(row);
    });

    /* RENDER WITH ROWSPAN */
    Object.entries(grouped).forEach(([color, rows]) => {
        rows.forEach((row, index) => {
            const tr = document.createElement("tr");
            const milkClass = `flash-${color.toLowerCase()}`;

            if (index === 0) {
                tr.innerHTML = `
                    <td class="col-milk ${milkClass}" rowspan="${rows.length}">${color}</td>
                    <td class="col-qty">${row.packet_type}</td>
                    <td class="col-count">${row.count}</td>
                `;
            } else {
                tr.innerHTML = `
                    <td class="col-qty">${row.packet_type}</td>
                    <td class="col-count">${row.count}</td>
                `;
            }

            tbody.appendChild(tr);
        });
    });

    adjustFontSize();

    /* FAST FLASH ON NEW TRAY */
    if (data.event && data.event_id !== lastEventId) {
        lastEventId = data.event_id;

        const flash = document.getElementById("flash");

        flash.classList.remove(
            "flash-shubham",
            "flash-toned",
            "flash-nsp",
            "flash-homegenized",
            "flash-desi",
            "flash-curd",
            "show"
        );

        const pkt = data.event.color.toLowerCase();

        if (pkt === "shubham") flash.classList.add("flash-shubham");
        else if (pkt === "toned") flash.classList.add("flash-toned");
        else if (pkt === "nsp") flash.classList.add("flash-nsp");
        else if (pkt === "homegenized") flash.classList.add("flash-homegenized");
        else if (pkt === "desi") flash.classList.add("flash-desi");
        else if (pkt === "curd") flash.classList.add("flash-curd");

        flash.textContent =
            `${data.event.packet_type.toUpperCase()} – ${data.event.color.toUpperCase()}`;

        /* 🔊 VOICE ANNOUNCEMENT (packet + color) - server-generated audio */
        playSound(data.event.packet_type, data.event.color);

        flash.offsetHeight;
        flash.classList.add("show");

        setTimeout(() => {
            flash.classList.remove("show");
        }, 300);
    }
};
</script>

</body>
</html>
"""

# -------------------- ROUTES --------------------
@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        conveyor_number=args.conveyor
    )

@app.route("/stream")
def stream():
    def event_stream():
        last_event_id = None

        while True:
            snapshot = [
                {
                    "packet_type": packet_type,
                    "color": color,
                    "count": count
                }
                for (packet_type, color), count in sorted(
                    counters.items(),
                    key=lambda x: (-x[1], x[0][1], x[0][0])
                    # 1️⃣ trays ascending
                    # 2️⃣ milk_type
                    # 3️⃣ quantity
                )
            ]

            event = None
            event_id = None

            if IS_LIVE and hasattr(stream, "last_event"):
                event = stream.last_event
                event_id = stream.last_event_id

            payload = {
                "table": snapshot,
                "event": event,
                "event_id": event_id,
                "is_live": IS_LIVE
            }

            # ✅ ALWAYS serialize with json.dumps
            data = json.dumps(payload, separators=(",", ":"))

            yield f"data: {data}\n\n"

            time.sleep(0.5)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx
        },
    )

# -------------------- LOG TAILER --------------------
def tail_log():
    global CURRENT_OFFSET, CURRENT_INODE, IS_LIVE

    while True:
        try:
            stat = os.stat(LOG_FILE)
            inode = stat.st_ino
            size = stat.st_size

            # 🔑 Only reset offset IF inode existed AND changed
            if CURRENT_INODE is not None and inode != CURRENT_INODE:
                print(
                    f"[INFO] Inode changed for conveyor {args.conveyor} "
                    f"(old={CURRENT_INODE}, new={inode}) → resetting offset"
                )
                CURRENT_OFFSET = 0
                IS_LIVE = False   # replay silently

            # Always update CURRENT_INODE to latest
            CURRENT_INODE = inode

            with open(LOG_FILE, "r") as f:
                # Offset sanity check
                if CURRENT_OFFSET > size:
                    CURRENT_OFFSET = 0

                if CURRENT_OFFSET > 0:
                    f.seek(CURRENT_OFFSET)
                    catching_up = not IS_LIVE
                else:
                    f.seek(0, os.SEEK_END)
                    catching_up = False
                    IS_LIVE = True

                while True:
                    line = f.readline()

                    if not line:
                        if catching_up:
                            IS_LIVE = True
                            catching_up = False
                            print("[INFO] Caught up to live log")
                        time.sleep(0.5)
                        continue

                    CURRENT_OFFSET = f.tell()

                    match = LOG_PATTERN.search(line)
                    if match:
                        tray_id, packet_type, color, packets = match.groups()

                        with STATE_LOCK:
                            counters[(packet_type, color)] += 1

                        save_state()

                        if IS_LIVE:
                                                stream.last_event = {
                                                    "packet_type": packet_type,
                                                    "color": color
                                                }
                                                stream.last_event_id = time.time()

                                                # Generate server-side audio for this tray (non-blocking)
                                                try:
                                                    threading.Thread(target=create_audio, args=(packet_type, color), daemon=True).start()
                                                except Exception:
                                                    pass

        except FileNotFoundError:
            print("[WARN] Log file not found, waiting...")
            time.sleep(1)

def daily_reset_worker():
    global CURRENT_OFFSET
    last_reset_date = None

    while True:
        now = datetime.datetime.now()

        if now.hour == RESET_HOUR:
            today = now.date().isoformat()

            if last_reset_date != today:
                with STATE_LOCK:
                    counters.clear()
                    CURRENT_OFFSET = 0

                save_state()
                last_reset_date = today

                print(f"[INFO] Daily reset done for conveyor {args.conveyor}")

        time.sleep(30)

# -------------------- MAIN --------------------
if __name__ == "__main__":
    load_state()

    threading.Thread(target=tail_log, daemon=True).start()
    threading.Thread(target=daily_reset_worker, daemon=True).start()

    app.run(host="0.0.0.0", port=args.port, debug=False)