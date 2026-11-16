with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

pos = text.find("ph-paperclip")
print(text[pos-200:pos+300])
