import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Since Artificial Analysis relies on dynamic Next.js data now and blocks simple table scraping,
# we need a fallback list of top models so ZEN doesn't completely fail when the scraper breaks.
# Also we need to make sure we scrape ZEN models and compare against this fallback if AA fails.

# Look at how top_15_names is built:
old_aa_scraping = """                resp = requests.get(ranking_url, headers=headers, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')
                table = soup.find('table')
                
                top_15_names = []
                if table:
                    # 前两行通常是表头
                    for row in table.find_all('tr')[2:17]:
                        cells = row.find_all(['th', 'td'])
                        if cells:
                            top_15_names.append(cells[0].get_text(strip=True).lower())
                
                # b. 获取 ZEN 的模型列表"""

new_aa_scraping = """                # 设置一个硬编码的保底前15名单，防止目标网站反爬或改版导致崩溃
                top_15_names = [
                    "gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro", "gemini-2.0-pro", "o1", "o3-mini",
                    "qwen-max", "qwen-3.6-plus", "qwen-3.6-max", "deepseek-v3", "deepseek-r1",
                    "claude-3-opus", "gpt-4-turbo", "llama-3.1-405b", "grok-2", "grok-3", "grok-4"
                ]
                
                try:
                    resp = requests.get(ranking_url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        # 尝试从新版 Next.js 数据中提取，或者简单地全文正则提取常见的大厂前缀
                        # 由于 Artificial Analysis 经常改版，我们优先使用保底列表，并结合网页中出现的关键词
                        page_text = resp.text.lower()
                        # 如果页面包含特定新模型，追加到名单中
                        for new_model in ["qwen-3.6-plus", "gemini-3.1", "gpt-5", "claude-4"]:
                            if new_model.replace("-", "") in page_text.replace("-", "") and new_model not in top_15_names:
                                top_15_names.append(new_model)
                except Exception as scrape_err:
                    print(f"爬取排行榜失败，降级使用硬编码的前 15 保底名单: {scrape_err}")
                
                # b. 获取 ZEN 的模型列表"""

content = content.replace(old_aa_scraping, new_aa_scraping)

# Let's fix the matching logic for Zen. Zen models usually have format "Provider/Model-Name"
# And we need to make sure the loop logic doesn't crash.
old_zen_match = """                        for top_name in top_15_names:
                            clean_top = top_name.replace("-", " ").replace("_", " ")
                            if base_name in clean_top or clean_top in base_name or all(part in clean_top for part in base_name.split()):
                                is_top_15 = True
                                break"""

new_zen_match = """                        for top_name in top_15_names:
                            clean_top = top_name.replace("-", " ").replace("_", " ").replace(".", "")
                            clean_base = base_name.replace(".", "")
                            # 提取纯名字部分，忽略 provider (如 qwen/qwen 36 plus -> qwen 36 plus)
                            core_base = clean_base.split('/')[-1] if '/' in clean_base else clean_base
                            
                            if core_base in clean_top or clean_top in core_base or all(part in clean_top for part in core_base.split()):
                                is_top_15 = True
                                break"""

content = content.replace(old_zen_match, new_zen_match)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("ZEN model matching and fallback applied.")

