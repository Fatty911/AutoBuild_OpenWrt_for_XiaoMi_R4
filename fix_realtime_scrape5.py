with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Let's fix the double backslashes that were inserted.
content = content.replace("r'self\\\\.__next_f\\\\.push\\\\(\\\\[1,\"(.*?)\"\\\\]\\\\)'", "r'self\\.__next_f\\.push\\(\\[1,\"(.*?)\"\\]\\)'")

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
