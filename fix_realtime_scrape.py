import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

old_scrape = """                try:
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
                    print(f"爬取排行榜失败，降级使用硬编码的前 15 保底名单: {scrape_err}")"""

new_scrape = """                try:
                    resp = requests.get(ranking_url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        # 从新版 Next.js 数据流中提取真实实时的模型名字/slug
                        import re
                        matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text)
                        live_models = []
                        for block in matches:
                            block = block.replace('\\\\"', '"')
                            # 提取 slug ("slug":"gpt-4o") 或 name ("name":"GPT-4o")
                            slugs = re.findall(r'"slug":"([a-z0-9\-.]+)"', block)
                            names = re.findall(r'"name":"([A-Za-z0-9\-.+ ]+?)"', block)
                            live_models.extend(slugs)
                            live_models.extend([n.lower().replace(" ", "-") for n in names])
                            
                        if live_models:
                            # 去重并加入排行榜列表（维持出现顺序，最早出现的一般排名更高或最活跃）
                            seen = set(top_15_names) # 保底名单依然优先
                            for m in live_models:
                                if len(m) > 2 and not m.isdigit() and "{" not in m and m not in seen:
                                    seen.add(m)
                                    top_15_names.append(m)
                            print(f"动态成功抓取到 {len(live_models)} 个实时模型，已加入白名单。")
                except Exception as scrape_err:
                    print(f"动态爬取排行榜失败，降级使用硬编码保底名单: {scrape_err}")"""

content = content.replace(old_scrape, new_scrape)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Scraper upgraded to real-time Next.js parser.")
