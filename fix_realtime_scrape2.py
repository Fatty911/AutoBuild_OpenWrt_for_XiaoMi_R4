import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix the raw string warning
old_re = "matches = re.findall(r'self\.__next_f\.push\(\[1,\"(.*?)\"\]\)', resp.text)"
new_re = "matches = re.findall(r'self\\\\.__next_f\\\\.push\\\\(\\\\[1,\"(.*?)\"\\\\]\\\\)', resp.text)"
content = content.replace(old_re, new_re)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Regex fixed.")
