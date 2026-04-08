import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

# I noticed the previous replace didn't work because of exact string mismatch. Let's do it robustly.
content = re.sub(
    r'curl -fsSL.*?npm install -g oh-my-opencode',
    'npm install -g oh-my-opencode',
    content,
    flags=re.DOTALL
)

content = content.replace('opencode run "分析 last_error.log', 'git config --local --unset-all http.https://github.com/.extraheader || true\n          oh-my-opencode run "分析 last_error.log')

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(content)
print("Track 3 fixed robustly.")
