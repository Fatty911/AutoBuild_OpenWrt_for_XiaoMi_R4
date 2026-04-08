import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

# The previous replace didn't catch the flag because of regex/literal mismatch, let's just strip it globally
content = content.replace(" --dangerously-skip-permissions", "")

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(content)
print("Removed flag.")
