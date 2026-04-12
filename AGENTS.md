# 全局规则（所有 AI Agent 必须遵守）

## 指令分类
- 收到用户指令时，必须判断这是**单次任务**（解决具体报错、一次性操作）还是**全局提示**（应贯穿所有会话始终遵守的规则）。
- 如果是全局提示，必须立即修改或追加到本文件（`AGENTS.md`）中，确保上下文压缩后仍可恢复。

## 语言
- 所有回复使用中文。

## 代码修改与提交
- 调试过程中产生的临时文件（如 `fix_*.py`、`test_*.py`、`patch_*.py`），在验证完成后必须删除，不得留在仓库根目录中。
- 生产代码只放 `custom_scripts/` 目录下，根目录不得出现 `.py` 文件。
- 本地 commit 可以随时做，但只有用户明确说"推送"或"push"时才 push 到远端。
- 单次解决报错的改动可自动 push，但多次循环尝试时注意 push 间隔时间。
- **每次修改完代码后必须进行严格的语法校验**（YAML 用 LSP/`actionlint`，Python 用 `python3 -c "import ast; ast.parse(open(...).read())"` 或 `ruff`，Shell 用 `shellcheck`）。

## 文档同步
- 每次执行完任务后，必须检查 README.md 和 AGENTS.md 是否需要更新（新增/删除/重命名了文件、功能、配置项，或新增了全局规则等）。

## 工作流保护
- **绝对禁止**修改、删除以下关键步骤：`Generate release tag`、`Upload firmware to release`、`Auto fix with AI on failure`、`Delete workflow runs`。
- 必须使用集中式 `AI_Auto_Fix_Monitor.yml` + `custom_scripts/auto_fix_with_AI_LLM.py`，不允许在每个单独编译工作流里重复复制 AI 逻辑。

## 模型与 API 选择
- opencode 用什么模型必须根据用户提供的 secrets 环境变量读取 key，可选 `_proxy_url` 和 `_model_list`，此要求全局生效。
- opencode Zen 对 mimo-v2-pro 已不再免费，不要优先选择它。
- 动态模型解析逻辑必须实时抓取 Artificial Analysis 排行榜数据，不能长期依赖硬编码列表。
- 优先选择排行榜前十且有免费资源的模型（如 Qwen3.6-Plus:free via OpenRouter）。
- 当日志过长导致超出当前模型上下文时，必须清晰打印提示信息并优雅降级到下一个模型/提供商。
- 所有 secrets 环境变量（包括 BAILIAN_API_KEY、MOONSHOT_API_KEY 等）必须在 AI Fix workflow 中完整暴露。

## opencode 配置
- opencode.json 必须使用合法 schema：`provider`（单数）和 `agent`（单数），不能用复数形式。
- 必须安装 opencode 本体和 oh-my-opencode 插件。
- oh-my-opencode 的多 agent 协同效果更好，优先使用。
