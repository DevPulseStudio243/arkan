import subprocess
import json

def run_ps(cmd):
    p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, errors="ignore")
    return p.stdout.strip()

def inspect():
    print("=" * 65)
    print("BILAN SYSTEME (CPU & MEMOIRE)")
    print("=" * 65)
    
    # OS Memory
    mem_raw = run_ps("Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json")
    try:
        mem_data = json.loads(mem_raw)
        total_kb = float(mem_data["TotalVisibleMemorySize"])
        free_kb = float(mem_data["FreePhysicalMemory"])
        used_kb = total_kb - free_kb
        total_gb = total_kb / (1024 * 1024)
        used_gb = used_kb / (1024 * 1024)
        free_gb = free_kb / (1024 * 1024)
        pct = (used_kb / total_kb) * 100
        print(f"RAM Totale      : {total_gb:.2f} GB")
        print(f"RAM Utilisee    : {used_gb:.2f} GB ({pct:.1f}%)")
        print(f"RAM Disponible  : {free_gb:.2f} GB")
    except Exception as e:
        print("Erreur lecture RAM:", e)

    # Global CPU Load
    cpu_raw = run_ps("(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average")
    print(f"Charge CPU Global: {cpu_raw}%")

    print("\n" + "=" * 65)
    print("TOP 15 PROCESSUS PAR CONSOMMATION RAM")
    print("=" * 65)
    
    ps_cmd_ram = """
    Get-Process | Where-Object { $_.WorkingSet64 -gt 50MB } | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 | ForEach-Object {
        [PSCustomObject]@{
            Id = $_.Id
            Name = $_.ProcessName
            RamMB = [math]::Round($_.WorkingSet64 / 1MB, 1)
            CPU = [math]::Round($_.CPU, 1)
        }
    } | ConvertTo-Json
    """
    res_ram = run_ps(ps_cmd_ram)
    try:
        procs_ram = json.loads(res_ram)
        if isinstance(procs_ram, dict):
            procs_ram = [procs_ram]
        for p in procs_ram:
            print(f" - {p['Name']:<26} (PID {p['Id']:<6}) : {p['RamMB']:>7.1f} MB  [Total CPU: {p['CPU']}s]")
    except Exception as e:
        print("Erreur analyse top RAM:", e)

    print("\n" + "=" * 65)
    print("FOCUS SUR LES PROCESSUS DEVELOPPEMENT & IA (Python, Ollama, Node, Electron, IDE)")
    print("=" * 65)
    
    ps_cmd_dev = """
    Get-Process | Where-Object { $_.ProcessName -match 'python|ollama|node|electron|code|chrome|msedge' } | Sort-Object WorkingSet64 -Descending | ForEach-Object {
        [PSCustomObject]@{
            Id = $_.Id
            Name = $_.ProcessName
            RamMB = [math]::Round($_.WorkingSet64 / 1MB, 1)
            CPU = [math]::Round($_.CPU, 1)
        }
    } | ConvertTo-Json
    """
    res_dev = run_ps(ps_cmd_dev)
    try:
        procs_dev = json.loads(res_dev)
        if isinstance(procs_dev, dict):
            procs_dev = [procs_dev]
        for p in procs_dev:
            print(f" * {p['Name']:<24} (PID {p['Id']:<6}) : {p['RamMB']:>7.1f} MB  [Total CPU: {p['CPU']}s]")
    except Exception as e:
        print("Erreur analyse dev:", e)

if __name__ == "__main__":
    inspect()
