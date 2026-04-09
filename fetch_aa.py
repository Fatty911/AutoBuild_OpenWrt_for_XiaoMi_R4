import requests
url = "https://artificialanalysis.ai/api/v1/leaderboard"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
try:
    resp = requests.get(url, headers=headers, timeout=10)
    print(resp.status_code)
    print(resp.text[:500])
except Exception as e:
    print(e)
    
url2 = "https://artificialanalysis.ai/api/models/leaderboard"
try:
    resp = requests.get(url2, headers=headers, timeout=10)
    print(resp.status_code)
    print(resp.text[:500])
except Exception as e:
    print(e)
