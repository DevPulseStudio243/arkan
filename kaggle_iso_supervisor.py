import time
import subprocess
import json
import re
from pathlib import Path

KERNEL_ID = "adleneboulouisa/arkan-isometric-mto-finetune"
OUTPUT_DIR = Path("kaggle_kernel_iso_mto/live_output")
STATUS_FILE = Path("kaggle_training_status.json")

def check_training():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Status
    res = subprocess.run(["kaggle", "kernels", "status", KERNEL_ID], capture_output=True, text=True)
    status_str = res.stdout.strip()
    
    # 2. Try fetching live logs from stdout
    res_logs = subprocess.run(["kaggle", "kernels", "logs", KERNEL_ID], capture_output=True, text=True)
    live_text = res_logs.stdout or ""
    
    # 3. Try fetching output directory
    subprocess.run(["kaggle", "kernels", "output", KERNEL_ID, "-p", str(OUTPUT_DIR)], capture_output=True, text=True)
    
    pct = 0.0
    current_step = 0
    total_steps = 175
    loss = "N/A"
    epoch = "0.0"
    
    # Search in live_text first
    if live_text:
        matches = re.findall(r'Step\s+(\d+)/(\d+)\s+\(([\d.]+)%\)\s+\|\s+Loss:\s+([\d.]+)\s+\|\s+Epoch:\s+([\d.]+)', live_text)
        if matches:
            last_m = matches[-1]
            current_step = int(last_m[0])
            total_steps = int(last_m[1])
            pct = float(last_m[2])
            loss = last_m[3]
            epoch = last_m[4]

    for log_file in OUTPUT_DIR.glob("*.log"):
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                matches = re.findall(r'Step\s+(\d+)/(\d+)\s+\(([\d.]+)%\)\s+\|\s+Loss:\s+([\d.]+)\s+\|\s+Epoch:\s+([\d.]+)', content)
                if matches:
                    last_m = matches[-1]
                    current_step = int(last_m[0])
                    total_steps = int(last_m[1])
                    pct = float(last_m[2])
                    loss = last_m[3]
                    epoch = last_m[4]
        except Exception:
            pass
            
    is_complete = "COMPLETE" in status_str
    if is_complete:
        pct = 100.0
        
    state = {
        "timestamp": time.time(),
        "kernel_id": KERNEL_ID,
        "raw_status": status_str,
        "is_complete": is_complete,
        "is_running": "RUNNING" in status_str,
        "progress_pct": pct,
        "current_step": current_step,
        "total_steps": total_steps,
        "loss": loss,
        "epoch": epoch
    }
    
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        
    return state

if __name__ == "__main__":
    s = check_training()
    print("Training Status:")
    print(json.dumps(s, indent=2))
