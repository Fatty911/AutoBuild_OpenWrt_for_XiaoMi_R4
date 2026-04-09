import requests
import re
import json

url = "https://artificialanalysis.ai/models"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
try:
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    
    # Try openrouter models instead as a proxy for top models?
    # OpenRouter API: https://openrouter.ai/api/v1/models
    
    # Or just grep for all common model naming patterns from the raw text!
    # \b(gpt-4o|claude-3-5|gemini-1-5|qwen2-5|llama-3-1|grok-3)[a-z0-9-]*\b
    # This is still a bit hardcoded.
    
    # Let's extract JSON payload from Next.js push arrays
    matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)\]\)', resp.text)
    print(f"Found {len(matches)} push blocks.")
    for block in matches:
        if 'GPT-4o' in block or 'gpt-4o' in block:
            # Decode the JS string to see what it contains
            decoded = block.encode('utf-8').decode('unicode_escape')
            if 'model_name' in decoded or '"name"' in decoded:
                # Find all names
                names = re.findall(r'\\"name\\":\\"([A-Za-z0-9_.\- ]+?)\\"', block)
                if names:
                    # Let's see what we get
                    print(list(set(names))[:30])
                    break
            
except Exception as e:
    print(f"Failed: {e}")
