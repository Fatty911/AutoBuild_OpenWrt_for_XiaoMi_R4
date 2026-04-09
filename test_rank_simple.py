import requests
import re
import json

# Fallback: Just get the top models from OpenRouter as a proxy for top models
url = "https://openrouter.ai/api/v1/models"
try:
    resp = requests.get(url, timeout=10)
    models = resp.json().get("data", [])
    
    # Openrouter models don't have a strict ranking, but we can just use the user's hardcoded lists if all else fails.
    # BUT the user asked specifically about Qwen3.6 Plus on Zen.
    # Let's check Zen API directly.
except Exception as e:
    print(e)
    
zen_url = "https://api.opencode.ai/api/v1/models" # Wait, the script uses opencode.ai/zen/v1/models
# Let's check the script again.
with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()
    if "opencode.ai/zen/v1/models" in content:
        print("Zen URL: opencode.ai/zen/v1/models")

