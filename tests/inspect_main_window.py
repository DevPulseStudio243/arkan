with open("electron-app/main.js", "r", encoding="utf-8") as f:
    text = f.read()

pos = text.find("createWindow")
print(text[pos:pos+1500].encode('ascii', errors='replace').decode('ascii'))
