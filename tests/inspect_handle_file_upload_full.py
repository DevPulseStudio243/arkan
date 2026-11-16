with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

pos = text.find("window.handleFileUpload =")
print(text[pos:pos+1200])
