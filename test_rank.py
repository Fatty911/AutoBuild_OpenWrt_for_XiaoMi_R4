import requests
from bs4 import BeautifulSoup

def get_top_15():
    ranking_url = "https://artificialanalysis.ai/models"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get(ranking_url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # We used to find 'table' and get 'tr'[2:17]
    table = soup.find('table')
    if not table:
        print("No table found")
        return []
        
    top_15_names = []
    for i, row in enumerate(table.find_all('tr')[:20]):
        cells = row.find_all(['th', 'td'])
        if cells:
            name = cells[0].get_text(strip=True).lower()
            print(f"Row {i}: {name}")
            top_15_names.append(name)
            
    return top_15_names

print(get_top_15())
