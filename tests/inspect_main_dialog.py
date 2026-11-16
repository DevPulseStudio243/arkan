with open("electron-app/main.js", "r", encoding="utf-8") as f:
    text = f.read()

pos = text.find("ipcMain.handle('dialog:openPlanFile'")
print(text[pos:pos+900])
