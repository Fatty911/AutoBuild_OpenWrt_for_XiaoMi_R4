import re

with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "r") as f:
    content = f.read()

# I need to completely strip the old AI step from the finalize block if it exists
# Let's just find "Auto fix with AI on failure" and remove that step
content = re.sub(
    r'      - name: Auto fix with AI on failure.*?(?=      - name: Delete workflow runs)',
    '',
    content,
    flags=re.DOTALL
)

with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "w") as f:
    f.write(content)

with open(".github/workflows/Build_coolsnowwolf-LEDE-full_for_XIAOMI_R4.yml", "r") as f:
    content_full = f.read()

content_full = re.sub(
    r'      - name: Auto fix with AI on failure.*?(?=      - name: Delete workflow runs)',
    '',
    content_full,
    flags=re.DOTALL
)

with open(".github/workflows/Build_coolsnowwolf-LEDE-full_for_XIAOMI_R4.yml", "w") as f:
    f.write(content_full)
print("Removed old AI auto fix step fully.")
