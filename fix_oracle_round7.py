import re
import os

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# 1. Expand required steps to cover all monitored workflows
# The monitor watches 9 workflows. We should require at least "Upload" and "Release" if they exist, 
# or just dynamically require that NO steps from the original file are deleted!
# That's much safer: "AI is not allowed to delete any existing steps, only modify them or add new ones."
# But wait, AI might need to replace a step.
# A simpler approach: require "Checkout" and "Maximize build space" which are in all of them.
# Let's just define the critical steps for all 9 workflows.
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

content = content.replace(old_required, new_required)

# 2. Oracle mentioned claude_models was still inside zen block.
# Wait, I removed the dynamic `claude_models.append` inside the loop in the previous step.
# Where else is claude_models inside an `if zen_api_key:` block?
# Ah! Oracle is talking about the `split_models(...)` assignment!
# Let's check the code:
"""
    if zen_api_key:
        ...
        claude_models = split_models(...)
"""
# I must have missed this because I couldn't see the exact file content. Let me use regex to find and move it.

