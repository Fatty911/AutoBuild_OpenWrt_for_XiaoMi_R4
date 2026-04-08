import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

# Insert setup node before Setup Python
old_setup = """      - name: Setup Python
        uses: actions/setup-python@v4"""

new_setup = """      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Setup Python
        uses: actions/setup-python@v4"""

if old_setup in content:
    content = content.replace(old_setup, new_setup)
    with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
        f.write(content)
    print("Setup node patch applied successfully.")
else:
    print("Old setup block not found.")
