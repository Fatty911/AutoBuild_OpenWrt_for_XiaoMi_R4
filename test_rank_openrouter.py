import requests
import json

def get_top_openrouter():
    url = "https://openrouter.ai/api/v1/models"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json().get("data", [])
        
        # Sort by top_provider.max_completion_tokens or contextual length as a proxy, 
        # or maybe we can just get openrouter rankings?
        # Openrouter models have pricing. We can maybe find a reliable API for leaderboard.
        
        # Another option: https://chat.lmsys.org/ API? Too complex.
        # Let's just look at how artificialanalysis HTML is structured now.
    except Exception as e:
        print(e)

import requests
from bs4 import BeautifulSoup
def scrape_aa():
    ranking_url = "https://artificialanalysis.ai/leaderboards/models"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get(ranking_url, headers=headers, timeout=15)
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Let's dump text and search for qwen
    text = soup.get_text()
    if "Qwen" in text:
        print("Found Qwen in page text")
        
    # How are models listed? They use divs now instead of tables probably.
    # Let's find all links or specific classes.
    links = soup.find_all('a')
    models = []
    for l in links:
        href = l.get('href', '')
        if href.startswith('/models/'):
            models.append(l.get_text(strip=True))
            
    # Deduplicate and clean
    clean_models = []
    for m in models:
        if m and m not in clean_models and not m.startswith('View'):
            clean_models.append(m)
            
    print("Found models via links:", clean_models[:30])

scrape_aa()
