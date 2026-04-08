import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

old_git = """          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || echo "No changes to commit"
          git push origin HEAD:main || echo "Push failed or nothing to push" """

new_git = """          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git remote set-url origin https://${ACTIONS_TRIGGER_PAT}@github.com/${{ github.repository }}.git
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || echo "No changes to commit"
          git push origin HEAD:main || echo "Push failed or nothing to push" """

if "git push origin HEAD:main" in content:
    content = content.replace(
        'git push origin HEAD:main || echo "Push failed or nothing to push"\n',
        'git remote set-url origin https://${ACTIONS_TRIGGER_PAT}@github.com/${{ github.repository }}.git\n          git push origin HEAD:main || echo "Push failed or nothing to push"\n'
    )
    with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
        f.write(content)
    print("Git patch applied successfully.")
else:
    print("Old git block not found.")
