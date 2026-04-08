import re
import os

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# I see what happened. My round 7 patch script failed to apply because of a regex mismatch, 
# and I didn't verify the python script was updated correctly. Let's do it robustly now.

old_required = """        required_steps = {
            ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
            ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
        }"""

new_required = """        required_steps = {
            ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml": ["Generate release tag", "Upload firmware to release"],
            ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml": ["Generate release tag", "Upload firmware to release"],
            ".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml": ["Generate release tag", "Upload firmware to release"],
            ".github/workflows/Build_coolsnowwolf-LEDE-full_for_XIAOMI_R4.yml": ["Generate release tag", "Upload firmware to release"],
            ".github/workflows/Build_Lienol_OpenWrt_1_for_XIAOMI_R4.yml": ["Upload bin directory", "Upload firmware directory"],
            ".github/workflows/Build_OpenWRT.org_1_for_XIAOMI_R4.yml": ["Upload bin directory", "Upload firmware directory"],
            ".github/workflows/Build_coolsnowwolf-LEDE-1_for_XIAOMI_R4-toolchain_kernel.yml": ["Upload bin directory", "Upload firmware directory"],
            ".github/workflows/Simple1.yml": ["Upload bin directory", "Upload firmware directory"],
            ".github/workflows/SimpleBuildOpenWRT_Official.yml": ["Upload bin directory", "Upload firmware directory"],
        }"""

if old_required in content:
    content = content.replace(old_required, new_required)
    print("Validator updated via exact string match.")
else:
    # Use regex
    content = re.sub(
        r'        required_steps = \{.*?\n        \}',
        new_required,
        content,
        flags=re.DOTALL
    )
    print("Validator updated via regex.")

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
