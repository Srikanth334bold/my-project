import os
import re
import threading
import time
import argparse
from collections import defaultdict
import json
import datetime
from flask import Flask, Response, render_template_string, send_from_directory

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
parser.add_argument("--conveyor", type=int, required=True, help="Conveyor number (e.g. 1, 2, 3)")
parser.add_argument("--port", type=int, default=5000, help="Web server port (default: 5000)")
parser.add_argument("--on-inode-change", choices=["begin", "end"], default="end", 
                   help="On log inode change: 'begin' = read from start, 'end' = jump to EOF (default: end)")

args = parser.parse_args()

# Update global variables with parsed arguments
STATE_FILE = f"tray_state_conveyor_{args.conveyor}.json"
INODE_CHANGE_MODE = args.on_inode_change
LOG_FILE = os.path.expanduser(f"~/project/Bamul_Final/camera_{args.conveyor}.log")

if not os.path.isfile(LOG_FILE):
    raise FileNotFoundError(f"Log file not found for conveyor {args.conveyor}: {LOG_FILE}")

print(f"[INFO] Monitoring conveyor {args.conveyor}")
print(f"[INFO] Log file: {LOG_FILE}")

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

def warmup_audio():
    print("[INFO] Audio files already exist, skipping generation...")
    # Check if audio files exist
    packet_types = ['two_hundred', 'one', 'half']
    colors = ["shubham", "toned", "nsp", "desi", "curd", "homogenised", "ttm"]
    
    missing_files = []
    for pkt in packet_types:
        for color in colors:
            safe_pkt = re.sub(r"\W+", "_", pkt).lower()
            safe_col = re.sub(r"\W+", "_", color).lower()
            wav_path = os.path.join(AUDIO_DIR, f"{safe_pkt}_{safe_col}.wav")
            if not os.path.exists(wav_path):
                missing_files.append(f"{safe_pkt}_{safe_col}.wav")
    
    if missing_files:
        print(f"[WARN] Missing audio files: {missing_files[:5]}{'...' if len(missing_files) > 5 else ''}")
    else:
        print("[INFO] All audio files present")

@app.route('/audio/<filename>')
def audio_file(filename):
    print(f"[DEBUG] Audio request: {filename}")
    
    # Handle both .mp3 and .wav requests by serving .wav files
    if filename.endswith('.mp3'):
        wav_filename = filename.replace('.mp3', '.wav')
        print(f"[DEBUG] Converting {filename} request to {wav_filename}")
        filename = wav_filename
    elif not filename.endswith('.wav'):
        print(f"[WARN] Rejecting unsupported file type: {filename}")
        return "Only WAV files supported", 404
    
    file_path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(file_path):
        print(f"[WARN] Audio file not found: {filename}")
        return "File not found", 404
    
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

.flash-shubham { background: #f97316; color: white; }
.flash-toned { background: #2563eb; color: white; }
.flash-nsp { background: #16a34a; color: white; }
.flash-homogenised { background: #86efac; color: #065f46; }
.flash-desi { background: #7c3aed; color: white; }
.flash-curd { background: #fde047; color: #78350f; }

.topbar {
    width: 100%;
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    margin-bottom: 8px;
}

.topbar .logo { max-height: 64px; height: auto; width: auto; }
.topbar .logo:first-child { max-height: 38px; }
.topbar .logo:last-child { max-height: 51px; }

.topbar .title {
    font-weight: 900;
    font-size: clamp(22px, 3vh, 38px);
    color: #111827;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: center;
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

.col-milk {
    font-size: clamp(16px, 2.2vh, 32px);
    font-weight: 700;
    transition: all 0.15s ease;
}

.col-count {
    font-size: clamp(20px, 3vh, 48px);
    font-weight: 900;
    color: #1f2937;
    transition: all 0.15s ease;
}

.col-count.flash {
    background: #fbbf24;
    color: #92400e;
    transform: scale(1.05);
}

.row-total {
    background: linear-gradient(90deg, #374151, #6b7280);
    color: white;
    font-weight: 900;
}

.row-total .col-count {
    color: #fbbf24;
    font-size: clamp(22px, 3.2vh, 52px);
}

@media (max-width: 768px) {
    .topbar { grid-template-columns: 1fr; text-align: center; }
    .topbar .logo { max-height: 32px; }
    .topbar .title { font-size: clamp(18px, 2.5vh, 28px); }
    th, td { padding: clamp(4px, 1vh, 12px); }
}
</style>
</head>
<body>
<div class="topbar">
    <img src="/logo/bamullogo.jpg" alt="Bamul" class="logo">
    <div class="title">Live Tray Counter - Conveyor {{ conveyor_number }}</div>
    <img src="/logo/kmfnandini.jpg" alt="Nandini" class="logo">
</div>

<div id="flash"></div>

<main>
<table>
<thead>
<tr>
    <th>Milk Type</th>
    <th>Shubham</th>
    <th>Toned</th>
    <th>NSP</th>
    <th>Desi</th>
    <th>Curd</th>
    <th>Homogenised</th>
    <th>TTM</th>
    <th>Total</th>
</tr>
</thead>
<tbody>
<tr>
    <td class="col-milk">200ml</td>
    <td class="col-count" id="two_hundred_ml-shubham">0</td>
    <td class="col-count" id="two_hundred_ml-toned">0</td>
    <td class="col-count" id="two_hundred_ml-nsp">0</td>
    <td class="col-count" id="two_hundred_ml-desi">0</td>
    <td class="col-count" id="two_hundred_ml-curd">0</td>
    <td class="col-count" id="two_hundred_ml-homogenised">0</td>
    <td class="col-count" id="two_hundred_ml-ttm">0</td>
    <td class="col-count" id="two_hundred_ml-total">0</td>
</tr>
<tr>
    <td class="col-milk">1 Litre</td>
    <td class="col-count" id="one-shubham">0</td>
    <td class="col-count" id="one-toned">0</td>
    <td class="col-count" id="one-nsp">0</td>
    <td class="col-count" id="one-desi">0</td>
    <td class="col-count" id="one-curd">0</td>
    <td class="col-count" id="one-homogenised">0</td>
    <td class="col-count" id="one-ttm">0</td>
    <td class="col-count" id="one-total">0</td>
</tr>
<tr>
    <td class="col-milk">500ml</td>
    <td class="col-count" id="half-shubham">0</td>
    <td class="col-count" id="half-toned">0</td>
    <td class="col-count" id="half-nsp">0</td>
    <td class="col-count" id="half-desi">0</td>
    <td class="col-count" id="half-curd">0</td>
    <td class="col-count" id="half-homogenised">0</td>
    <td class="col-count" id="half-ttm">0</td>
    <td class="col-count" id="half-total">0</td>
</tr>
<tr class="row-total">
    <td class="col-milk">TOTAL</td>
    <td class="col-count" id="total-shubham">0</td>
    <td class="col-count" id="total-toned">0</td>
    <td class="col-count" id="total-nsp">0</td>
    <td class="col-count" id="total-desi">0</td>
    <td class="col-count" id="total-curd">0</td>
    <td class="col-count" id="total-homogenised">0</td>
    <td class="col-count" id="total-ttm">0</td>
    <td class="col-count" id="total-total">0</td>
</tr>
</tbody>
</table>
</main>

<script>
let eventSource;
let audioQueue = [];
let isPlaying = false;

function playAudio(filename) {
    return new Promise((resolve) => {
        const audio = new Audio(`/audio/${filename}?${Date.now()}`);
        audio.onended = resolve;
        audio.onerror = () => {
            console.warn(`Audio failed: ${filename}`);
            resolve();
        };
        audio.play().catch(() => {
            console.warn(`Audio play failed: ${filename}`);
            resolve();
        });
    });
}

async function processAudioQueue() {
    if (isPlaying || audioQueue.length === 0) return;
    isPlaying = true;
    
    while (audioQueue.length > 0) {
        const filename = audioQueue.shift();
        await playAudio(filename);
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    
    isPlaying = false;
}

function queueAudio(packetType, color) {
    const jsPacketType = packetType.replace('_litre', '');
    const safePacket = jsPacketType.replace(/\\W+/g, '_').toLowerCase();
    const safeColor = color.replace(/\\W+/g, '_').toLowerCase();
    const filename = `${safePacket}_${safeColor}.wav`;
    
    audioQueue.push(filename);
    processAudioQueue();
}

function flashElement(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    element.classList.add('flash');
    setTimeout(() => element.classList.remove('flash'), 800);
}

function showFlashMessage(packetType, color, count) {
    const flash = document.getElementById('flash');
    const displayPacket = packetType === 'two_hundred_ml' ? '200ml' : 
                         packetType === 'one' ? '1L' : '500ml';
    
    flash.textContent = `${displayPacket} ${color.toUpperCase()} - ${count}`;
    flash.className = `flash-${color} show`;
    
    setTimeout(() => {
        flash.classList.remove('show');
    }, 1500);
}

function updateCounter(packetType, color, count) {
    const cellId = `${packetType}-${color}`;
    const cell = document.getElementById(cellId);
    if (cell) {
        cell.textContent = count;
        flashElement(cellId);
    }
}

function updateTotals(data) {
    const colors = ['shubham', 'toned', 'nsp', 'desi', 'curd', 'homogenised', 'ttm'];
    const packets = ['two_hundred_ml', 'one', 'half'];
    
    // Update column totals
    colors.forEach(color => {
        let total = 0;
        packets.forEach(packet => {
            const key = `${packet}|${color}`;
            total += data[key] || 0;
        });
        const totalCell = document.getElementById(`total-${color}`);
        if (totalCell) totalCell.textContent = total;
    });
    
    // Update row totals
    packets.forEach(packet => {
        let total = 0;
        colors.forEach(color => {
            const key = `${packet}|${color}`;
            total += data[key] || 0;
        });
        const totalCell = document.getElementById(`${packet}-total`);
        if (totalCell) totalCell.textContent = total;
    });
    
    // Update grand total
    let grandTotal = 0;
    Object.values(data).forEach(count => grandTotal += count);
    const grandTotalCell = document.getElementById('total-total');
    if (grandTotalCell) grandTotalCell.textContent = grandTotal;
}

function connectEventSource() {
    if (eventSource) eventSource.close();
    
    eventSource = new EventSource('/events');
    
    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            
            if (data.type === 'update') {
                Object.entries(data.counters).forEach(([key, count]) => {
                    const [packetType, color] = key.split('|');
                    updateCounter(packetType, color, count);
                });
                updateTotals(data.counters);
            } else if (data.type === 'event') {
                const { packet_type, color, packets } = data;
                queueAudio(packet_type, color);
                showFlashMessage(packet_type, color, packets);
            }
        } catch (e) {
            console.error('Error parsing event data:', e);
        }
    };
    
    eventSource.onerror = function() {
        console.log('EventSource error, reconnecting in 3s...');
        setTimeout(connectEventSource, 3000);
    };
}

connectEventSource();
</script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE, conveyor_number=args.conveyor)

@app.route('/events')
def events():
    def event_stream():
        last_counters = {}
        last_event_id = None
        
        while True:
            try:
                with STATE_LOCK:
                    current_counters = dict(counters)
                    current_event_id = event_tracker.last_event_id
                
                # Send counter updates if changed
                if current_counters != last_counters:
                    yield f"data: {json.dumps({'type': 'update', 'counters': current_counters})}\n\n"
                    last_counters = current_counters.copy()
                
                # Send event if new
                if current_event_id != last_event_id and event_tracker.last_event:
                    yield f"data: {json.dumps({'type': 'event', **event_tracker.last_event})}\n\n"
                    last_event_id = current_event_id
                
                time.sleep(0.5)
            except Exception as e:
                print(f"[ERROR] Event stream error: {e}")
                break
    
    return Response(event_stream(), mimetype='text/plain')

def process_log_line(line):
    match = LOG_PATTERN.search(line)
    if not match:
        return
    
    tray_id, packet_type, color, packets = match.groups()
    packets = int(packets)
    
    # Normalize packet type
    if packet_type == "two_hundred_ml":
        packet_type = "two_hundred_ml"
    elif packet_type in ["one_litre", "one"]:
        packet_type = "one"
    elif packet_type in ["half_litre", "half"]:
        packet_type = "half"
    
    key = (packet_type, color.lower())
    
    with STATE_LOCK:
        counters[key] += packets
        
        # Update event tracker
        event_tracker.last_event = {
            'packet_type': packet_type,
            'color': color.lower(),
            'packets': packets,
            'tray_id': tray_id
        }
        event_tracker.last_event_id = time.time()
        
        save_state()
    
    print(f"[EVENT] Tray {tray_id}: {packet_type} {color} +{packets} (total: {counters[key]})")

def monitor_log():
    global CURRENT_OFFSET, CURRENT_INODE
    
    while True:
        try:
            if not os.path.exists(LOG_FILE):
                time.sleep(1)
                continue
            
            stat = os.stat(LOG_FILE)
            current_inode = stat.st_ino
            
            # Handle inode change (log rotation)
            if CURRENT_INODE is not None and current_inode != CURRENT_INODE:
                print(f"[INFO] Log rotation detected (inode {CURRENT_INODE} -> {current_inode})")
                if INODE_CHANGE_MODE == "begin":
                    CURRENT_OFFSET = 0
                else:
                    CURRENT_OFFSET = stat.st_size
                CURRENT_INODE = current_inode
                save_state()
                continue
            
            CURRENT_INODE = current_inode
            
            # Handle file truncation
            if stat.st_size < CURRENT_OFFSET:
                print("[INFO] Log file truncated, resetting offset")
                CURRENT_OFFSET = 0
                save_state()
            
            # Read new content
            if stat.st_size > CURRENT_OFFSET:
                with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(CURRENT_OFFSET)
                    new_content = f.read()
                    CURRENT_OFFSET = f.tell()
                
                for line in new_content.strip().split('\n'):
                    if line.strip():
                        process_log_line(line)
                
                save_state()
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"[ERROR] Monitor error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    # Load previous state
    load_state()
    
    # Generate audio files
    warmup_audio()
    
    # Start log monitoring in background
    monitor_thread = threading.Thread(target=monitor_log, daemon=True)
    monitor_thread.start()
    
    print(f"[INFO] Starting web server on port {args.port}")
    print(f"[INFO] Dashboard: http://localhost:{args.port}")
    
    app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)