import re
import time
import threading
import subprocess
import os
from pathlib import Path
from flask import send_from_directory
import argparse
from collections import defaultdict
import json
import datetime
import pyttsx3

from flask import Flask, Response, render_template_string

STATE_LOCK = threading.Lock()
RESET_HOUR = 2

# Initialize global variables
counters = defaultdict(int)
CURRENT_OFFSET = 0
CURRENT_INODE = None
IS_LIVE = False
STATE_FILE = ""

# Event tracking object
class EventTracker:
    def __init__(self):
        self.last_event = None
        self.last_event_id = None

event_tracker = EventTracker()

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
            CURRENT_INODE = data.get("inode")
            print(f"[INFO] State loaded | inode={CURRENT_INODE} offset={CURRENT_OFFSET}")
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
            "counters": {f"{k[0]}|{k[1]}": v for k, v in counters.items()}
        }
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, STATE_FILE)

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

# Update global variables with parsed arguments
STATE_FILE = f"tray_state_conveyor_{args.conveyor}.json"
INODE_CHANGE_MODE = args.on_inode_change

LOG_FILE = os.path.expanduser(f"~/project/Bamul_Final/camera_{args.conveyor}.log")

if not os.path.isfile(LOG_FILE):
    raise FileNotFoundError(
        f"Log file not found for conveyor {args.conveyor}: {LOG_FILE}"
    )

print(f"[INFO] Monitoring conveyor {args.conveyor}")
print(f"[INFO] Log file: {LOG_FILE}")

# Customizable display and voice mappings
DISPLAY_MAPPINGS = {
    'two_hundred_ml': 'two hundred',
    'one': 'one',
    'half': 'half'
}

VOICE_MAPPINGS = {
    'two_hundred_ml': '200',
    'two_hundred': '200',
    'one': 'ಒಂದು',
    'half': 'ಅರ್ಧ',
    'toned': 'toned',
    'nsp': 'N.S.P',
    'desi': 'desi',
    'curd': 'ಮೊಸರು',
    'homogenised': 'H.C.M',
    'shubham': 'shubham',
    'six': 'six',
    'ttm': 'T.T.M'
}

# Enhanced Kannada audio translations
KANNADA_AUDIO = {
    'two_hundred_ml': 'ಇರುನೂರು', 'two_hundred': 'ಇರುನೂರು', 'toned': 'ಟೋನ್ಡ್', 'nsp': 'ಎನ್ಎಸ್ಪಿ',
    'shubham': 'ಶುಭಮ್', 'desi': 'ದೇಸಿ', 'curd': 'ಮೊಸರು', 
    'homogenised': 'ಹೋಮೋಜೆನೈಸ್ಡ್', 'one': 'ಒಂದು', 'half': 'ಅರ್ಧ', 'ttm': 'ಟಿಟಿಎಂ'
}

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

LOG_PATTERN = re.compile(
    r"(?:^.*?\|\s*)?FINALIZED Tray:\s*(\d+),\s*packet_type:\s*(\w+),\s*color:\s*(\w+),\s*packets:\s*(\d+)"
)

def generate_pyttsx3_audio(text, output_path):
    """Generate audio using pyttsx3"""
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 300)  # Faster speech rate
        engine.setProperty('volume', 1.0)
        engine.save_to_file(text, output_path)
        engine.runAndWait()
        return os.path.exists(output_path)
    except Exception as e:
        print(f"[WARN] pyttsx3 failed: {e}")
        return False

app = Flask(__name__)

def warmup_audio():
    print("[INFO] Pre-generating audio files using pyttsx3...")
    
    # Generate audio for all combinations that JavaScript expects
    packet_types = ['two_hundred_ml', 'one_litre', 'half_litre']
    colors = ["shubham", "toned", "nsp", "desi", "curd", "homogenised", "ttm"]
    
    for pkt in packet_types:
        for color in colors:
            # JavaScript expects: half_curd.wav, two_hundred_ml_curd.wav etc
            js_pkt = pkt.replace('_litre', '') if 'litre' in pkt else pkt
            safe_pkt = re.sub(r"\W+", "_", js_pkt).lower()
            safe_col = re.sub(r"\W+", "_", color).lower()
            
            wav_path = os.path.join(AUDIO_DIR, f"{safe_pkt}_{safe_col}.wav")

            if os.path.exists(wav_path):
                continue

            # Get Kannada text for pyttsx3
            kannada_pkt = KANNADA_AUDIO.get(pkt, pkt)
            kannada_col = KANNADA_AUDIO.get(color.lower(), color)
            text = f"{kannada_pkt} {kannada_col}"

            if generate_pyttsx3_audio(text, wav_path):
                print(f"[INFO] Generated audio for {safe_pkt}_{safe_col}")
            else:
                print(f"[WARN] Audio generation failed for {safe_pkt}_{safe_col}")
    
    print("[INFO] Audio warmup complete")



@app.route('/audio/<filename>')
def audio_file(filename):
    print(f"[DEBUG] Audio request: {filename}")
    
    if not filename.endswith('.wav'):
        print(f"[WARN] Rejecting non-WAV file: {filename}")
        return "Only WAV files supported", 404
    
    file_path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(file_path):
        # Auto-generate missing audio file
        base_name = filename.replace('.wav', '')
        parts = base_name.split('_')
        if len(parts) >= 2:
            color = parts[-1]
            pkt = '_'.join(parts[:-1])
            
            kannada_pkt = KANNADA_AUDIO.get(pkt, pkt)
            kannada_col = KANNADA_AUDIO.get(color.lower(), color)
            text = f"{kannada_pkt} {kannada_col}"
            
            print(f"[INFO] Auto-generating audio for {pkt}_{color}")
            if generate_pyttsx3_audio(text, file_path):
                print(f"[INFO] Generated missing audio: {filename}")
            else:
                print(f"[WARN] Failed to generate audio: {filename}")
                return "Audio generation failed", 404
        else:
            print(f"[WARN] Invalid audio filename format: {filename}")
            return "Invalid filename format", 404
    
    return send_from_directory(AUDIO_DIR, filename)

@app.route('/logo/<filename>')
def logo_file(filename):
    print(f"[DEBUG] Logo request: {filename}")
    logo_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo")
    file_path = os.path.join(logo_dir, filename)
    if not os.path.exists(file_path):
        print(f"[WARN] Logo file not found: {filename}")
        return "Logo file not found", 404
    return send_from_directory(logo_dir, filename)

# EXACT RESPONSIVE.PY FRONTEND
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Live Tray Counter {{ conveyor_number }}</title>
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
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    font-size: clamp(32px, 6vw, 80px);
    padding: clamp(16px, 3vh, 32px) clamp(32px, 6vw, 80px);
    border-radius: 20px;
    font-weight: 900;
    box-shadow: 0 10px 25px rgba(0,0,0,0.35);
    opacity: 0;
    transition: all 0.06s linear;
    z-index: 1000;
    white-space: nowrap;
}

#flash.show {
    opacity: 1;
    transform: translateX(-50%) scale(1.02);
}

.flash-shubham     { background: #f97316; color: white; }
.flash-toned       { background: #2563eb; color: white; }
.flash-nsp         { background: #16a34a; color: white; }
.flash-homegenized { background: #86efac; color: #065f46; }
.flash-desi        { background: #7c3aed; color: white; }
.flash-curd        { background: #fde047; color: #78350f; }

.topbar {
    width: 100%;              
    display: grid;            
    grid-template-columns: auto 1fr auto;
    align-items: center;
    margin-bottom: 8px;
}
.topbar .logo{max-height:64px;height:auto;width:auto}
.topbar .logo:first-child{max-height:38px;} /* Bamul logo 40% smaller */
.topbar .logo:last-child{max-height:51px;} /* Nandini logo 20% smaller */
.topbar .title{
    font-weight:900;
    font-size:clamp(22px, 3vh, 38px);
    color:#111827;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
    text-align:center;
}

table {
    border-collapse: collapse;
    width: 97%;
    height: 92%;
    background: white;
    box-shadow: 0 16px 45px rgba(0,0,0,0.2);
    border-radius: 20px;
    border: 4px solid #000;
    table-layout: fixed;
}

main {
    width: 100%;
    height: 100%;
    display: flex;
    justify-content: center;
    align-items: stretch;
    padding: 10px;
    box-sizing: border-box;
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
    white-space: nowrap;
}

th {
    font-size: clamp(18px, 2.6vh, 40px);
    letter-spacing: 1px;
}

.col-milk.flash-shubham     { background: #f97316; color: white; }
.col-milk.flash-toned       { background: #2563eb; color: white; }
.col-milk.flash-nsp         { background: #16a34a; color: white; }
.col-milk.flash-homogenised { background: #86efac; color: black; }
.col-milk.flash-desi        { background: #7c3aed; color: white; }
.col-milk.flash-curd        { background: #fde047; color: #78350f; }

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
    <div class="title">Bamul Live Crate Counter - Conveyor {{ conveyor_number }}</div>
    <img src="/logo/kmfnandini.jpg" alt="KMF" class="logo">
</header>

<div id="flash"></div>
<audio id="tts" preload="auto"></audio>

<main style="width:100%; height:100%; display:flex; justify-content:center; align-items:stretch; padding:10px; box-sizing:border-box;">
    <table id="counter-table">
        <thead>
            <tr>
                <th>Milk Type</th>
                <th>Quantity</th>
                <th>Tray Count</th>
            </tr>
        </thead>
        <tbody></tbody>
    </table>
</main>

<script>
const evtSource = new EventSource("/stream");
let lastEventId = null;
let audioQueue = [];
let isPlaying = false;

function playSound(pkt, color) {
    // Map packet types to match generated audio files
    const packetMapping = {
        'two_hundred_ml': 'two_hundred_ml',
        'two_hundred': 'two_hundred_ml',  // Map to actual generated file
        'one_litre': 'one',
        'one': 'one',
        'half_litre': 'half',
        'half': 'half'
    };
    
    const mappedPkt = packetMapping[pkt] || pkt;
    const baseName = `${mappedPkt}_${color}`.replace(/\s+/g, "_").toLowerCase();
    const wavFile = `${baseName}.wav`;
    
    console.log(`[DEBUG] Requesting audio: ${wavFile} for ${pkt}_${color}`);
    
    // Only queue if we expect the file to exist based on our generation logic
    const validPacketTypes = ['two_hundred_ml', 'one', 'half'];
    const validColors = ['shubham', 'toned', 'nsp', 'desi', 'curd', 'homogenised', 'ttm'];
    
    const normalizedPkt = mappedPkt.toLowerCase();
    const normalizedColor = color.toLowerCase();
    
    if (validPacketTypes.includes(normalizedPkt) && validColors.includes(normalizedColor)) {
        audioQueue.push({ files: [wavFile], pkt, color });
        if (!isPlaying) playNextAudio();
    } else {
        console.warn(`Skipping audio for unknown combination: ${pkt}_${color}`);
    }
}

function playNextAudio() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        return;
    }
    isPlaying = true;
    const { files, pkt, color } = audioQueue.shift();
    
    showFlash(pkt, color);
    
    const audio = document.getElementById('tts');
    audio.playbackRate = 1.5;  // Faster playback speed
    
    // Add error logging
    audio.src = `/audio/${files[0]}?${Date.now()}`;
    audio.onended = () => {
        setTimeout(playNextAudio, 10);  // Wait 500ms before next audio
    };
    audio.onerror = (e) => {
        console.error(`Audio error for ${files[0]}:`, e);
        console.error(`Full audio URL: /audio/${files[0]}`);
        setTimeout(playNextAudio, 1);
    };
    audio.play().catch((e) => {
        console.error(`Audio play failed for ${files[0]}:`, e);
        console.error(`Full audio URL: /audio/${files[0]}`);
        setTimeout(playNextAudio, 1);
    });
}

function showFlash(pkt, color) {
    const flash = document.getElementById("flash");
    
    flash.classList.remove("flash-shubham", "flash-toned", "flash-nsp", "flash-homegenised", "flash-desi", "flash-curd", "show");
    
    const colorLower = color.toLowerCase();
    if (colorLower === "shubham") flash.classList.add("flash-shubham");
    else if (colorLower === "toned") flash.classList.add("flash-toned");
    else if (colorLower === "nsp") flash.classList.add("flash-nsp");
    else if (colorLower === "homegenised") flash.classList.add("flash-homegenised");
    else if (colorLower === "desi") flash.classList.add("flash-desi");
    else if (colorLower === "curd") flash.classList.add("flash-curd");

    flash.textContent = `${pkt.toUpperCase()} – ${color.toUpperCase()}`;
    
    flash.offsetHeight;
    flash.classList.add("show");
    
    setTimeout(() => {
        flash.classList.remove("show");
    }, 400);  // 0.4 second flash
}

evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    renderTable(data);

    if (data.event && data.event_id !== lastEventId) {
        lastEventId = data.event_id;
        playSound(data.event.packet_type, data.event.color);
    }
};

function renderTable(data) {
    const tbody = document.querySelector("#counter-table tbody");
    const currentData = JSON.stringify(data.table);
    
    // Only update if data actually changed
    if (tbody.dataset.lastData === currentData) return;
    tbody.dataset.lastData = currentData;
    
    tbody.innerHTML = "";

    // Display mappings for better readability
    const displayMappings = {
        'two_hundred_ml': 'two hundred',
        'two_hundred': 'two hundred',
        'one': 'one',
        'half': 'half'
    };

    const grouped = {};
    data.table.forEach(row => {
        if (!grouped[row.color]) grouped[row.color] = [];
        grouped[row.color].push(row);
    });

    Object.entries(grouped).forEach(([color, rows]) => {
        rows.forEach((row, index) => {
            const tr = document.createElement("tr");
            const milkClass = `flash-${color.toLowerCase()}`;
            const displayText = displayMappings[row.packet_type] || row.packet_type;

            if (index === 0) {
                tr.innerHTML = `
                    <td class="col-milk ${milkClass}" rowspan="${rows.length}">${color}</td>
                    <td class="col-qty">${displayText}</td>
                    <td class="col-count">${row.count}</td>
                `;
            } else {
                tr.innerHTML = `
                    <td class="col-qty">${displayText}</td>
                    <td class="col-count">${row.count}</td>
                `;
            }
            tbody.appendChild(tr);
        });
    });
    adjustFontSize();
}

function fitTextToCell(cell) {
    const cellWidth = cell.clientWidth;
    const cellHeight = cell.clientHeight;

    let fontSize = Math.min(cellHeight * 0.9, 48);
    cell.style.whiteSpace = "nowrap";
    cell.style.overflow = "hidden";

    cell.style.fontSize = fontSize + "px";

    while (
        (cell.scrollWidth > cellWidth || cell.scrollHeight > cellHeight) &&
        fontSize > 10
    ) {
        fontSize--;
        cell.style.fontSize = fontSize + "px";
    }
}

function adjustFontSize() {
    const table = document.querySelector("#counter-table");
    const tbody = table.querySelector("tbody");
    const rows = tbody.querySelectorAll("tr");
    if (!rows.length) return;

    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;
    const headerHeight = document.querySelector(".topbar").offsetHeight;
    const padding = 20;
    
    // Calculate 92% of available space
    const availableHeight = (windowHeight - headerHeight - padding) * 0.92;
    
    // Header scales inversely with row count
    const headerScale = Math.max(0.3, Math.min(1.0, 8 / rows.length));
    const tableHeaderHeight = Math.floor(availableHeight * 0.15 * headerScale);
    
    // Remaining space for table body
    const bodyHeight = availableHeight - tableHeaderHeight;
    const rowHeight = Math.floor(bodyHeight / rows.length);
    
    // Set header height
    document.querySelectorAll("#counter-table th").forEach(th => {
        th.style.height = tableHeaderHeight + "px";
    });
    
    // Set row heights
    rows.forEach(row => {
        row.style.height = rowHeight + "px";
    });
    
    // Font sizing at 80% of cell height with single-line text
    const baseFontSize = Math.floor(rowHeight * 0.8);
    
    rows.forEach(row => {
        row.querySelectorAll("td").forEach(cell => {
            fitTextToCell(cell);
        });
    });
    
    // Dynamic flash sizing - top middle
    const flashSize = Math.max(32, Math.min(100, windowWidth / 120));
    document.getElementById("flash").style.fontSize = flashSize + "px";
}

// Enhanced resize handling
let resizeTimeout;
function handleResize() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(adjustFontSize, 150);
}

renderTable({table: []});
window.addEventListener("resize", handleResize);
document.addEventListener('DOMContentLoaded', adjustFontSize);

// Initial sizing with delay
setTimeout(adjustFontSize, 300);
</script>

</body>
</html>
"""

@app.route("/")
def index():
    # Add cache busting headers
    response = app.response_class(
        render_template_string(HTML_TEMPLATE, conveyor_number=args.conveyor),
        mimetype='text/html'
    )
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route("/stream")
def stream():
    def event_stream():
        while True:
            snapshot = [
                {"packet_type": packet_type, "color": color, "count": count}
                for (packet_type, color), count in sorted(
                    counters.items(), key=lambda x: (-x[1], x[0][1], x[0][0])
                )
            ]
            
            event = None
            event_id = None
            
            if IS_LIVE and event_tracker.last_event:
                event = event_tracker.last_event
                event_id = event_tracker.last_event_id
            
            payload = {
                "table": snapshot,
                "event": event,
                "event_id": event_id,
                "is_live": IS_LIVE
            }
            
            data = json.dumps(payload, separators=(",", ":"))
            yield f"data: {data}\n\n"
            time.sleep(0.0005)
    
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

def tail_log():
    global CURRENT_OFFSET, CURRENT_INODE, IS_LIVE
    
    while True:
        try:
            stat = os.stat(LOG_FILE)
            inode = stat.st_ino
            size = stat.st_size
            
            # Only reset offset IF inode existed AND changed
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
                            event_tracker.last_event = {"packet_type": packet_type, "color": color}
                            event_tracker.last_event_id = time.time()
        
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

if __name__ == "__main__":
    load_state()
    warmup_audio()
    
    threading.Thread(target=tail_log, daemon=True).start()
    threading.Thread(target=daily_reset_worker, daemon=True).start()
    
    app.run(host="0.0.0.0", port=args.port, debug=False)
