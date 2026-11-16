with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

pos = text.find("window.processMtoUpload =")
if pos == -1: pos = text.find("processMtoUpload =")
print(text[pos:pos+1500])
