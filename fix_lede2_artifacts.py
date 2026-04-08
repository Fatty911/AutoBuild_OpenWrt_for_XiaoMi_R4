import re

with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "r") as f:
    content = f.read()

# Add log extraction and artifact upload to LEDE-2
upload_block = """      - name: Validate build output
        run: |
          python $GITHUB_WORKSPACE/custom_scripts/validate_build_output.py

      - name: Extract Error Log
        if: failure()
        run: |
          python $GITHUB_WORKSPACE/custom_scripts/extract_last_error.py --output last_error.log --max-chars 15000

      - name: Upload Error Log Artifact
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: error-log
          path: last_error.log
          retention-days: 7"""

content = content.replace("""      - name: Validate build output
        run: |
          python $GITHUB_WORKSPACE/custom_scripts/validate_build_output.py""", upload_block)

# Remove inner AI auto fix block to prevent double-fixing
auto_fix_block = re.search(r'      - name: Auto fix with AI on failure.*?        continue-on-error: true\n', content, re.DOTALL)
if auto_fix_block:
    content = content.replace(auto_fix_block.group(0), "")

with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "w") as f:
    f.write(content)
print("LEDE-2 fixed artifacts.")

with open(".github/workflows/Build_coolsnowwolf-LEDE-full_for_XIAOMI_R4.yml", "r") as f:
    content_full = f.read()

content_full = content_full.replace("""      - name: Validate build output
        run: |
          python $GITHUB_WORKSPACE/custom_scripts/validate_build_output.py""", upload_block)

auto_fix_block_full = re.search(r'      - name: Auto fix with AI on failure.*?        continue-on-error: true\n', content_full, re.DOTALL)
if auto_fix_block_full:
    content_full = content_full.replace(auto_fix_block_full.group(0), "")

with open(".github/workflows/Build_coolsnowwolf-LEDE-full_for_XIAOMI_R4.yml", "w") as f:
    f.write(content_full)
print("LEDE-full fixed artifacts.")
