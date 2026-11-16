import os

folder = r"generated_visuals\C3421-ROK1-100-PRC-DM-300002_2_pid_pipeline\blocks"
if os.path.exists(folder):
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        print(f, os.path.getsize(p))
