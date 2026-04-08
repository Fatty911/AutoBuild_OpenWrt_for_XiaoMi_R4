import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Replace the "all(part in c_clean for part in req_clean.split())" logic 
# which is incorrectly matching "glm 5" to "z ai glm 5v turbo" and returning MULTIPLE models!
# If it returns multiple models, it might be appending things we don't want or hitting rate limits.
# Even worse, in the logs we saw:
# [GLM-OR] 模型 glm-5 失败: 请求失败: HTTP 404
# This means OpenRouter got "glm-5" and rejected it! Why didn't it get "z-ai/glm-5"?
# Wait! `req_clean` is "glm 5", `c_clean` is "z ai glm 5".
# `all(part in c_clean for part in req_clean.split())` -> "glm" in "z ai glm 5", "5" in "z ai glm 5". True!
# So it APPENDED "z-ai/glm-5".
# But why did the log print "[GLM-OR] 模型 glm-5 失败"?
# Ah, maybe the API key was empty and the fetch failed?
# If `fetched_models` is empty, it returns `requested_models`, which is ["glm-5"].

