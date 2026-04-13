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
- **只使用当前排行榜前 20 的模型**（如 GLM-5、GLM-5.1、Qwen3.6-Plus、Qwen3.5-398B、Claude Opus 4.6、GPT-5.4、DeepSeek-R1 等），绝对不要使用已落榜的旧模型（如 GLM-4、Qwen2、GPT-4o、Claude 3.5 等）。保底模型也必须满足此要求。
- **模型列表不得硬编码**，必须运行时实时从 Artificial Analysis 排行榜抓取。排行榜抓取失败时不过滤（放行所有模型），而不是退回硬编码列表。硬编码的模型列表一两个月就会过时。
- **允许缓存兜底**：实时抓取成功后必须把结果写回缓存文件（如 `.leaderboard_cache.json`），供下次抓取失败时兜底。缓存超过 14 天未更新时必须打印警告但仍可使用。无论是本地还是 GitHub Action 中，只要有自动回退机制，就可以用缓存兜底，但必须保证每一两周至少爬一次排行榜更新缓存，不能长期不更新。
- 优先选择排行榜前 20 且有免费资源的模型。当前已知免费渠道：
  - AtomGit：`zai-org/GLM-5`、`Qwen/Qwen3.5-397B-A17B`（无限量，500次/分，端点 `https://api-ai.gitcode.com/v1`）
  - OpenRouter：`qwen/qwen3.6-plus:free`、`qwen/qwen3.6-plus-preview:free`（1M context，429 频发）、`google/gemma-4-31b-it:free`（262K context，~27 tok/s）
  - ZEN：排行榜前 20 的免费模型
  - 智谱官方：`GLM-4-Flash`（永久免费保底，并发 30）、`GLM-5.1`（付费，排行榜前列）
- 当日志过长导致超出当前模型上下文时，必须清晰打印提示信息并优雅降级到下一个模型/提供商。
- **MiniMax 白名单**：只允许 MiniMax Coding Plan 2.7（非 highspeed 版本），其他 MiniMax 模型（如 m2.5-free、m1.5、abab 系列等）一律屏蔽。
- 所有 secrets 环境变量（包括 BAILIAN_API_KEY、MOONSHOT_API_KEY、ATOMGIT_API_KEY、ZHIPU_API_KEY 等）必须在 AI Fix workflow 中完整暴露。

## opencode 配置
- opencode.json 必须使用合法 schema：`provider` 必须为 record 对象（如 `{"atomgit": {}}`），不能是字符串；`provider`（单数）和 `agent`（单数），不能用复数形式。
- 必须安装 opencode 本体和 oh-my-openagent 插件（npm 包名 `oh-my-openagent`，CLI 命令名仍为 `oh-my-opencode`）。
- oh-my-openagent 的多 agent 协同效果更好，优先使用。
