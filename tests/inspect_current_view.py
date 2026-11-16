with open("arkan-ui.html", "r", encoding="utf-8") as f:
    text = f.read()

pos = text.find("window.currentView =")
if pos == -1: pos = text.find("currentView =")
print(text[pos-50:pos+300])
