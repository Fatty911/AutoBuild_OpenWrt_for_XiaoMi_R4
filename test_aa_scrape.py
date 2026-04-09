import requests
import re
import json

url = "https://artificialanalysis.ai/leaderboards/models"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
try:
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    
    # Next.js App Router injects data in self.__next_f.push scripts.
    # It contains lots of JSON-like strings.
    # Let's search for "provider_name" or "model_name" or specific model identifiers.
    
    # We can use regex to find all "slug":"[a-z0-9-]+" or "name":"[a-zA-Z0-9- .]+"
    # But it's easier to find the exact array of models if it's there.
    
    # Let's try to find a block of JSON that contains the models.
    matches = re.findall(r'"name":"([^"]+)","provider":{"name":"([^"]+)"', resp.text)
    
    if matches:
        # Deduplicate and keep order (first seen is likely highest ranked, but let's just collect all unique)
        seen = set()
        top_models = []
        for name, provider in matches:
            if name not in seen:
                seen.add(name)
                top_models.append(f"{name}".lower())
        
        print(f"Found {len(top_models)} models via regex.")
        print(top_models[:20])
    else:
        print("Regex 1 failed. Trying regex 2...")
        # Sometimes it's just "name":"GPT-4o"
        matches2 = re.findall(r'"name":"(GPT-[^"]+|Claude [^"]+|Gemini [^"]+|Qwen[^"]+|DeepSeek[^"]+|Llama[^"]+|Grok[^"]+|Mistral[^"]+)"', resp.text)
        if matches2:
            seen = set()
            top_models = []
            for name in matches2:
                if name not in seen:
                    seen.add(name)
                    top_models.append(name.lower())
            print(f"Found {len(top_models)} models via regex 2.")
            print(top_models[:20])
            
except Exception as e:
    print(f"Failed: {e}")
