import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# I need to fix the fallback logic! 
# Because for AtomGit and SiliconFlow, `glm-5` is actually translated to `ZhipuAI/glm-5` by my fallback,
# BUT the actual model on SiliconFlow might be `ZhipuAI/glm-4-9b-chat` or `Pro/zhipuai/glm-4-9b-chat`.
# The user specifically mentioned: "为什么要请求gpt-4o、grok-2、glm-4-plus，再变体也得是同一代模型啊"
# Aha! The user is right, I should NOT fallback `gpt-5.4` to `gpt-4o` or `glm-5` to `glm-4-plus` inside the configuration.
# The fallback was added by me previously when I thought they didn't exist. Let me remove it and let it strictly be gpt-5.4

# Wait, previously I hardcoded `gpt_models = split_models("OPENAI_MODEL_LIST", "openai/gpt-5.4,openai/gpt-4o")`
# Let me change it back to ONLY gpt-5 series, since the user insists on it.

new_model_list = """    claude_models = split_models("CLAUDE_MODEL_LIST", "anthropic/claude-sonnet-4.6,anthropic/claude-opus-4.6")
    gemini_models = split_models("GEMINI_MODEL_LIST", "google/gemini-3.1-pro,google/gemini-3.1-pro-preview")
    gpt_models = split_models("OPENAI_MODEL_LIST", "openai/gpt-5.4,openai/gpt-5.3,openai/gpt-5.2")
    grok_models = split_models("GROK_MODEL_LIST", "x-ai/grok-4.2,x-ai/grok-4.1")
    glm_models_or = split_models("GLM_MODEL_LIST", "z-ai/glm-5-turbo,z-ai/glm-5")
    glm_models_cn = split_models("GLM_MODEL_LIST", "glm-5-turbo,glm-5")
    # minimax_models = split_models("MINIMAX_MODEL_LIST", "MiniMax-M2.7") # 注释掉 MiniMax，防幻觉"""

start_idx = content.find('claude_models = split_models("CLAUDE_MODEL_LIST"')
if start_idx != -1:
    end_idx = content.find('    providers = []', start_idx)
    if end_idx != -1:
        new_content = content[:start_idx] + new_model_list + "\n\n" + content[end_idx:]
        with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
            f.write(new_content)
        print("Updated static list to purely future generation models")
