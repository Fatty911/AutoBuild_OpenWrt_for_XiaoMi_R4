import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

# Fix the trailing space in "Build OpenWRT.org 2 fix and transplant for XIAOMI_R4 "
content = content.replace(
    '"Build OpenWRT.org 2 fix and transplant for XIAOMI_R4 "',
    '"Build OpenWRT.org 2 fix and transplant for XIAOMI_R4"'
)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(content)
print("Monitor workflow names fixed.")
