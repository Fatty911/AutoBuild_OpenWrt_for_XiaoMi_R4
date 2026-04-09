import re
with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Revert my bad regex replacement in round 2
bad_re = r'matches = re.findall\(r\'self\\\\.__next_f\\\\.push\\\\(\\\\[1,"(.*?)"]\\\\)\', resp.text\)'
good_re = r'matches = re.findall(r\'self\.__next_f\.push\(\[1,"(.*?)"\]\)\', resp.text)'

content = re.sub(bad_re, good_re, content)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
