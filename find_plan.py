import os, glob

for pattern in ["*300002*", "*300002*.*", "*300002*/*"]:
    for p in glob.glob(f"**/{pattern}", recursive=True):
        print(p)

for root, dirs, files in os.walk("."):
    for f in files:
        if "300002" in f:
            print(os.path.join(root, f))
