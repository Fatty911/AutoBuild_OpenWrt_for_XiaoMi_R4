import re

with open("custom_scripts/extract_last_error.py", "r") as f:
    content = f.read()

# Replace the tight fallback logic
content = content.replace(
    "start = max(0, i - 15)\n                        end = min(len(lines), i + 5)",
    "start = max(0, i - 100)\n                        end = min(len(lines), i + 50)"
)
content = content.replace(
    "content[-2000:]",
    "content[-15000:]"
)

with open("custom_scripts/extract_last_error.py", "w") as f:
    f.write(content)
print("Patch applied.")
