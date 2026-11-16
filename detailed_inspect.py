import sys, re
sys.stdout.reconfigure(encoding="utf-8")

with open("arh_api_routes.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

print("--- Inspecting lines 1000 to 1200 (feedback endpoint & decorators) ---")
for i in range(1125, 1165):
    print(f"{i+1:4d}: {lines[i]}", end="")

print("\n--- Inspecting compare-revisions post L1360 to L1380 ---")
for i in range(1360, 1380):
    print(f"{i+1:4d}: {lines[i]}", end="")

print("\n--- Inspecting audit_dossier_via_dot_tm L1620 to L1645 ---")
for i in range(1620, 1645):
    print(f"{i+1:4d}: {lines[i]}", end="")

print("\n--- Inspecting cross_validate_arh_dossier L1925 to L1950 ---")
for i in range(1925, 1950):
    print(f"{i+1:4d}: {lines[i]}", end="")
