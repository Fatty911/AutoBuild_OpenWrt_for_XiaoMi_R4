import requests

url = "https://api.siliconflow.cn/v1/models"
headers = {"Authorization": "Bearer sk-something", "Accept": "application/json"}
try:
    resp = requests.get(url, headers=headers, timeout=10)
    print("SiliconFlow /models status:", resp.status_code)
    # The API might require auth, or it might be public.
    # If the user provides auth, `get_resolved_models` sends it!
except Exception as e:
    print(e)
    
