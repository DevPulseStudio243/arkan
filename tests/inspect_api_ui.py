with open("api_enhanced.py", "r", encoding="utf-8") as f:
    text = f.read()

pos = text.find('"/ui"')
if pos == -1: pos = text.find("'/ui'")
print(text[pos-50:pos+350])
