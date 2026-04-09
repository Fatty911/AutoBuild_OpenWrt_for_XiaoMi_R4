import requests
import re
url = "https://artificialanalysis.ai/leaderboards/models"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
resp = requests.get(url, headers=headers, timeout=15)
# Artificial Analysis injects data via Next.js <script id="__NEXT_DATA__" type="application/json">
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text)
if match:
    import json
    data = json.loads(match.group(1))
    print("Found NEXT_DATA")
    try:
        models = data['props']['pageProps']['models']
        for i, m in enumerate(models[:20]):
            print(f"{i+1}: {m.get('name')}")
    except Exception as e:
        print("Couldn't find models in NEXT_DATA:", e)
else:
    print("No NEXT_DATA found")
    
# Alternatively, it might use <script> self.__next_f.push([1,"...
match2 = re.search(r'self\.__next_f\.push\(\[.*?\]\)', resp.text)
if match2:
    print("Found modern nextjs push data")
    # Instead of parsing the complex AST, let's just do a dumb regex for model names on the page:
    # They often have a certain pattern in the HTML.
    
    # Or what if we use the OpenRouter API which provides `top_provider` and pricing, and we just pick models that are free on Zen?
    # Actually, Zen models are already a curated list. Do we really need to check against ArtificialAnalysis?
    pass

