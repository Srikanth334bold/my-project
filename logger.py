import re
import time
import threading
import pyttsx3
from flask import send_from_directory
import argparse
import os
from collections import defaultdict
import json
import datetime

from flask import Flask, Response, render_template_string

STATE_LOCK = threading.Lock()
RESET_HOUR = 2

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
parser.add_argument("--conveyor", type=int, required=True, help="Conveyor number")
parser.add_argument("--port", type=int, default=5000, help="Web server port")
args = parser.parse_args()

IS_LIVE = False
STATE_FILE = f"tray_state_conveyor_{args.conveyor}.json"
CURRENT_OFFSET = 0
CURRENT_INODE = None

LOG_FILE = os.path.expanduser(
    f"~/project/Bamul_Final/camera_{args.conveyor}.log"
)
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

LOG_PATTERN = re.compile(
    r"(?:^.*?\|\s*)?FINALIZED Tray:\s*(\d+),\s*packet_type:\s*(\w+),\s*color:\s*(\w+),\s*packets:\s*(\d+)"
)

counters = defaultdict(int)
app = Flask(__name__)

def create_audio(packet_type, color):
    safe_pkt = re.sub(r"\W+", "_", packet_type).lower()
    safe_col = re.sub(r"\W+", "_", color).lower()
    file_name = f"{safe_pkt}_{safe_col}.wav"
    file_path = os.path.join(AUDIO_DIR, file_name)
    
    if os.path.exists(file_path):
        return file_path
    
    text = f"{packet_type} {color}"
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
    logo_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo")
    return send_from_directory(logo_dir, filename)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Live Tray Counter {{ conveyor_number }}</title>
<style>
* { box-sizing: border-box; }
html, body {
    width: 100vw;
    height: 100vh;
    margin: 0;
    padding: 0;
    overflow: hidden;
    font-family: "Segoe UI", Arial, sans-serif;
    background: #000000;
    display: flex;
    flex-direction: column;
}

.topbar {
    width: 100%;
    height: 80px;
    display: grid;
    grid-template-columns: 120px 1fr 120px;
    align-items: center;
    padding: 0 20px;
    background: rgba(20,20,20,0.95);
    backdrop-filter: blur(10px);
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
    position: fixed;
    top: 0;
    z-index: 100;
}

.logo { 
    height: 60px;
    width: auto;
    object-fit: contain;
}

.title {
    font-weight: 900;
    font-size: clamp(1.5vw, 32px, 3vw);
    color: white;
    text-align: center;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

#flash {
    position: fixed;
    top: 90px;
    left: 50%;
    transform: translateX(-50%) scale(0.8);
    font-size: clamp(2vw, 48px, 4vw);
    font-weight: 900;
    padding: clamp(1vh, 20px, 2vh) clamp(2vw, 40px, 4vw);
    border-radius: 25px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.4);
    opacity: 0;
    transition: all 0.15s cubic-bezier(0.68, -0.55, 0.265, 1.55);
    z-index: 1000;
    white-space: nowrap;
    border: 4px solid rgba(255,255,255,0.3);
}

#flash.show {
    opacity: 1;
    transform: translateX(-50%) scale(1);
}

.flash-shubham { background: linear-gradient(45deg, #f97316, #fb923c); color: white; }
.flash-toned { background: linear-gradient(45deg, #2563eb, #3b82f6); color: white; }
.flash-nsp { background: linear-gradient(45deg, #16a34a, #22c55e); color: white; }
.flash-homegenised { background: linear-gradient(45deg, #86efac, #bbf7d0); color: #065f46; }
.flash-desi { background: linear-gradient(45deg, #7c3aed, #8b5cf6); color: white; }
.flash-curd { background: linear-gradient(45deg, #fde047, #fef08a); color: #78350f; }

main {
    flex: 1;
    display: flex;
    padding: 0;
    margin-top: 80px;
    width: 100vw;
    height: calc(100vh - 80px);
}

table {
    width: 100vw;
    height: 100%;
    border-collapse: collapse;
    background: rgba(255,255,255,0.95);
    backdrop-filter: blur(15px);
    box-shadow: 0 25px 80px rgba(0,0,0,0.25);
    border: 4px solid black;
    table-layout: fixed;
}

thead {
    background: linear-gradient(135deg, #1e40af, #3730a3);
    color: white;
    height: 15vh;
}

th {
    font-size: var(--dynamic-header-font, 48px);
    font-weight: 900;
    padding: var(--dynamic-padding, 20px);
    text-transform: uppercase;
    letter-spacing: 1px;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
    border-right: 2px solid black;
    vertical-align: middle;
    width: 33.33%;
}

tbody {
    display: table-row-group;
    height: 85vh;
}

td {
    text-align: center;
    padding: var(--dynamic-padding, 15px);
    vertical-align: middle;
    border-bottom: 2px solid black;
    border-right: 2px solid black;
    height: var(--dynamic-row-height, auto);
}

.col-milk {
    font-weight: 900;
    text-transform: uppercase;
    font-size: var(--dynamic-milk-font, 40px);
    border-right: 3px solid rgba(0,0,0,0.2);
    width: 33.33%;
}

.col-milk.flash-shubham { background: linear-gradient(45deg, #f97316, #fb923c); color: white; }
.col-milk.flash-toned { background: linear-gradient(45deg, #2563eb, #3b82f6); color: white; }
.col-milk.flash-nsp { background: linear-gradient(45deg, #16a34a, #22c55e); color: white; }
.col-milk.flash-homegenised { background: linear-gradient(45deg, #86efac, #bbf7d0); color: #065f46; }
.col-milk.flash-desi { background: linear-gradient(45deg, #7c3aed, #8b5cf6); color: white; }
.col-milk.flash-curd { background: linear-gradient(45deg, #fde047, #fef08a); color: #78350f; }

.col-qty {
    font-weight: 800;
    color: #7c2d12;
    font-size: var(--dynamic-qty-font, 35px);
    width: 33.33%;
}

.col-count {
    font-weight: 900;
    font-size: var(--dynamic-count-font, 55px);
    color: #1d4ed8;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
    width: 33.33%;
}

tbody {
    display: table-row-group;
}

thead, tbody tr {
    display: table-row;
}

tbody tr:nth-child(even) {
    background-color: rgba(248,250,252,0.5);
}

tbody tr:hover {
    background-color: rgba(59,130,246,0.1);
    transform: scale(1.02);
    transition: all 0.2s ease;
}

@media (max-width: 768px) {
    .topbar {
        grid-template-columns: 80px 1fr 80px;
        height: 60px;
        padding: 0 10px;
    }
    .logo { height: 40px; }
    .title { font-size: clamp(16px, 5vw, 28px); }
    main { margin-top: 60px; }
}

@media (min-width: 1920px) {
    :root {
        --min-header-font: 40px;
        --min-milk-font: 35px;
        --min-qty-font: 30px;
        --min-count-font: 50px;
    }
}
</style>
</head>
<body>

<header class="topbar">
    <img src="/logo/bamullogo.png" alt="Bamul" class="logo">
    <div class="title">Bamul Live Crate Counter - Conveyor {{ conveyor_number }}</div>
    <img src="/logo/kmfnandhinilogo.jpg" alt="KMF" class="logo">
</header>

<div id="flash"></div>
<audio id="tts" preload="auto"></audio>

<main>
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

function playSound(pkt, color) {
    const fileName = `${pkt}_${color}.wav`.replace(/\s+/g, "_").toLowerCase();
    const audio = document.getElementById('tts');
    audio.src = `/audio/${fileName}?${Date.now()}`;
    
    // Ensure audio plays immediately with no delay
    const playPromise = audio.play();
    if (playPromise !== undefined) {
        playPromise.catch(() => {});
    }
}

function showFlash(packetType, color) {
    const flash = document.getElementById("flash");
    
    // Remove all existing classes
    flash.className = '';
    
    // Add color class
    const colorClass = `flash-${color.toLowerCase()}`;
    flash.classList.add(colorClass);
    
    flash.textContent = `${packetType.toUpperCase()} – ${color.toUpperCase()}`;
    
    // Force reflow and show
    flash.offsetHeight;
    flash.classList.add("show");
    
    setTimeout(() => {
        flash.classList.remove("show");
    }, 2000);
}

function renderTable(data) {
    const tbody = document.querySelector("#counter-table tbody");
    tbody.innerHTML = "";
    
    // Group by milk type
    const grouped = {};
    data.table.forEach(row => {
        if (!grouped[row.color]) grouped[row.color] = [];
        grouped[row.color].push(row);
    });
    
    // Calculate total rows for dynamic sizing
    const totalRows = Object.values(grouped).reduce((sum, rows) => sum + rows.length, 0);
    const availableHeight = window.innerHeight - 120; // Header space
    const headerHeight = Math.max(80, availableHeight * 0.15);
    const bodyHeight = availableHeight - headerHeight;
    const rowHeight = Math.max(60, Math.floor(bodyHeight / totalRows));
    
    // Calculate font sizes based on screen size and row count
    const screenWidth = window.innerWidth;
    const baseFontMultiplier = Math.min(screenWidth / 1920, 2); // Scale based on screen width
    
    const headerFont = Math.max(24, Math.min(80, rowHeight * 0.6 * baseFontMultiplier));
    const milkFont = Math.max(20, Math.min(70, rowHeight * 0.5 * baseFontMultiplier));
    const qtyFont = Math.max(18, Math.min(60, rowHeight * 0.45 * baseFontMultiplier));
    const countFont = Math.max(28, Math.min(100, rowHeight * 0.7 * baseFontMultiplier));
    const padding = Math.max(10, Math.min(30, rowHeight * 0.2));
    
    // Apply dynamic sizing
    document.documentElement.style.setProperty('--dynamic-header-font', `${headerFont}px`);
    document.documentElement.style.setProperty('--dynamic-milk-font', `${milkFont}px`);
    document.documentElement.style.setProperty('--dynamic-qty-font', `${qtyFont}px`);
    document.documentElement.style.setProperty('--dynamic-count-font', `${countFont}px`);
    document.documentElement.style.setProperty('--dynamic-padding', `${padding}px`);
    document.documentElement.style.setProperty('--dynamic-row-height', `${rowHeight}px`);
    
    // Render with rowspan
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
}

evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    renderTable(data);
    
    // Synchronized flash and sound
    if (data.event && data.event_id !== lastEventId && data.is_live) {
        lastEventId = data.event_id;
        
        // Play sound and show flash simultaneously
        playSound(data.event.packet_type, data.event.color);
        showFlash(data.event.packet_type, data.event.color);
    }
};

// Handle window resize
window.addEventListener('resize', () => {
    // Re-render table on resize to recalculate sizes
    const lastData = window.lastTableData;
    if (lastData) {
        renderTable(lastData);
    }
});

// Store last data for resize handling
let originalOnMessage = evtSource.onmessage;
evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    window.lastTableData = data;
    originalOnMessage.call(this, event);
};

// Enable audio on first user interaction
document.addEventListener('click', () => {
    const audio = document.getElementById('tts');
    audio.play().catch(() => {});
}, { once: true });
</script>

</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, conveyor_number=args.conveyor)

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
            
            if IS_LIVE and hasattr(stream, "last_event"):
                event = stream.last_event
                event_id = stream.last_event_id
            
            payload = {
                "table": snapshot,
                "event": event,
                "event_id": event_id,
                "is_live": IS_LIVE
            }
            
            data = json.dumps(payload, separators=(",", ":"))
            yield f"data: {data}\n\n"
            time.sleep(0.5)
    
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

def tail_log():
    global CURRENT_OFFSET, CURRENT_INODE, IS_LIVE
    
    while True:
        try:
            if not os.path.exists(LOG_FILE):
                time.sleep(1)
                continue
                
            stat = os.stat(LOG_FILE)
            inode = stat.st_ino
            size = stat.st_size
            
            if CURRENT_INODE is not None and inode != CURRENT_INODE:
                print(f"[INFO] Inode changed for conveyor {args.conveyor}")
                CURRENT_OFFSET = 0
                IS_LIVE = False
            
            CURRENT_INODE = inode
            
            with open(LOG_FILE, "r") as f:
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
                            stream.last_event = {"packet_type": packet_type, "color": color}
                            stream.last_event_id = time.time()
                            
                            # Generate audio in background
                            try:
                                threading.Thread(
                                    target=create_audio, 
                                    args=(packet_type, color), 
                                    daemon=True
                                ).start()
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

if __name__ == "__main__":
    load_state()
    
    threading.Thread(target=tail_log, daemon=True).start()
    threading.Thread(target=daily_reset_worker, daemon=True).start()
    
    app.run(host="0.0.0.0", port=args.port, debug=False)