# autocad_worker.py
import sys
import os
import win32com.client

def convert_dwg_to_dxf_direct(dwg_path, dxf_path):
    dwg_path = os.path.abspath(dwg_path)
    dxf_path = os.path.abspath(dxf_path)
    
    # Connect to running AutoCAD, or spawn a new instance
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        print("Connected to running AutoCAD instance.")
    except Exception:
        acad = win32com.client.Dispatch("AutoCAD.Application")
        print("Started new AutoCAD instance.")
        
    # Suppress UI and popups as much as possible
    acad.Visible = False
    
    # Check if the document is already open in AutoCAD and close it to release locks
    for d in list(acad.Documents):
        try:
            if os.path.abspath(d.FullName).lower() == dwg_path.lower():
                print("Document is currently open in AutoCAD. Closing existing instance...")
                d.Close(False)
                break
        except Exception:
            pass
            
    print(f"Opening DWG file (ReadOnly=True): {dwg_path}")
    doc = acad.Documents.Open(dwg_path, True)
        
    # SaveAs format enum: 61 = 2018 DXF, 49 = 2013 DXF, 37 = 2010 DXF, 25 = 2004 DXF
    save_success = False
    for fmt in (61, 49, 37, 25):
        try:
            print(f"Saving to DXF format code {fmt}: {dxf_path}")
            doc.SaveAs(dxf_path, fmt)
            save_success = True
            break
        except Exception as save_err:
            print(f"SaveAs format {fmt} failed: {save_err}")
            
    # Close document without saving changes to the original DWG
    try:
        doc.Close(False)
    except Exception:
        pass
        
    if save_success and os.path.exists(dxf_path) and os.path.getsize(dxf_path) > 100:
        print("DEXPI AutoCAD worker: DXF export completed successfully.")
        return True
    return False

def convert_dwg_to_dxf(dwg_path, dxf_path):
    """
    Automates AutoCAD via COM to silently export a DWG plan into a DXF plan.
    Self-heals by terminating hung acad.exe processes and retrying if a COM error occurs.
    """
    try:
        return convert_dwg_to_dxf_direct(dwg_path, dxf_path)
    except Exception as e:
        print(f"AutoCAD automation error on first attempt: {e}", file=sys.stderr)
        print("Attempting to kill hung acad.exe process and retry...", file=sys.stderr)
        
        import subprocess
        subprocess.run("taskkill /F /IM acad.exe", shell=True, capture_output=True)
        
        # Wait a bit for the system to clean up COM handles
        import time
        time.sleep(2)
        
        try:
            return convert_dwg_to_dxf_direct(dwg_path, dxf_path)
        except Exception as retry_e:
            print(f"AutoCAD automation retry failed: {retry_e}", file=sys.stderr)
            return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python autocad_worker.py <dwg_path> <dxf_path>", file=sys.stderr)
        sys.exit(1)
        
    dwg = sys.argv[1]
    dxf = sys.argv[2]
    
    success = convert_dwg_to_dxf(dwg, dxf)
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
