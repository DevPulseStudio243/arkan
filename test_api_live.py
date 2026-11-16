import requests

def test_api():
    print("Testing live API http://127.0.0.1:8000/mto/calculate ...")
    with open(r"C:\Users\MSI\Desktop\test007.pdf", "rb") as f:
        resp = requests.post("http://127.0.0.1:8000/mto/calculate", files={"file": ("test007.pdf", f, "application/pdf")})
    print("HTTP Status:", resp.status_code)
    data = resp.json()
    val = data.get("validation", {})
    anomalies = data.get("anomalies", [])
    print("is_valid:", val.get("is_valid"))
    print("summary:", val.get("summary"))
    print("anomalies count:", len(anomalies))
    for a in anomalies:
        sev = a.get("severity")
        code = a.get("code")
        title = a.get("title") or a.get("message")
        print(f"  * [{sev}] {code}: {title}")

if __name__ == "__main__":
    test_api()
