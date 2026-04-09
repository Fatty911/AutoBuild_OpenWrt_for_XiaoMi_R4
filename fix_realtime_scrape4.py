import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix the regex literal backslash issue one more time perfectly
old_re = r"matches = re.findall(r'self\\\\.__next_f\\\\.push\\\\(\\\\[1,\"(.*?)\"\\\\]\\\\)', resp.text)"
new_re = r"matches = re.findall(r'self\.__next_f\.push\(\[1,\"(.*?)\"\]\)', resp.text)"

content = content.replace(old_re, new_re)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
