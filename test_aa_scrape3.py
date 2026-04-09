import requests
import re
import json

url = "https://artificialanalysis.ai/models"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
try:
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    
    matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text)
    
    # We want to combine all text that looks like a JSON block
    all_names = []
    for block in matches:
        # Decode the escaped JSON string slightly to make regex easier
        block = block.replace('\\"', '"')
        
        # "name":"GPT-4o" or "slug":"gpt-4o"
        # Often models are in an array of objects
        
        # Let's extract anything that looks like a model ID or name
        slugs = re.findall(r'"slug":"([a-z0-9\-.]+)"', block)
        if slugs:
            all_names.extend(slugs)
            
        names = re.findall(r'"name":"([A-Za-z0-9\-.+ ]+?)"', block)
        if names:
            all_names.extend([n.lower().replace(" ", "-") for n in names])
            
    # Deduplicate but maintain some order (slugs are better)
    seen = set()
    final_models = []
    for n in all_names:
        if n not in seen and len(n) > 2 and not n.isdigit() and "{" not in n:
            seen.add(n)
            final_models.append(n)
            
    print(f"Found {len(final_models)} unique names.")
    print("Top 50:", final_models[:50])
    
    if "qwen-3.6-plus" in final_models or "qwen-3-6-plus" in final_models or "qwen3.6-plus" in final_models:
        print("Success! Found Qwen 3.6 Plus dynamically.")
            
except Exception as e:
    print(f"Failed: {e}")
