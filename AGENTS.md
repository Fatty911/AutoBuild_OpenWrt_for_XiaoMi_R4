# 全局规则（所有 AI Agent 必须遵守）

## 指令分类
- 收到用户指令时，必须判断这是**单次任务**（解决具体报错、一次性操作）还是**全局提示**（应贯穿所有会话始终遵守的规则）。
- 如果用户提供了工作流日志，日志中同时包含 **OpenWrt 编译报错**（业务本身报错）和 **AI 调用报错**（工作流或 AI 脚本报错）时，必须**同时尽力解决这两种报错**。
- 如果是全局提示，必须立即修改或追加到本文件（`AGENTS.md`）中，确保上下文压缩后仍可恢复。
- **有已知的待完成任务时，禁止询问用户确认，必须一次性全部完成。**

## 语言
- 所有回复使用中文。

## 代码修改与提交
- 调试过程中产生的临时文件（如 `fix_*.py`、`test_*.py`、`patch_*.py`），在验证完成后必须删除，不得留在仓库根目录中。
- 生产代码只放 `custom_scripts/` 目录下，根目录不得出现 `.py` 文件。
- **涉及修改代码的任务，必须在每次完成所有 TODO 后统一进行语法格式校验，然后做一次统一的 commit，绝对不要在中间多次零散提交**。改完代码后必须自动更新 `AGENTS.md` 和 `README.md`，并在最后一次统一 commit 中一并提交推送。
- 本地 commit 可以随时做，但只有用户明确说"推送"或"push"时（或者在单次解决报错的自动修复场景下）才 push 到远端。
- **每次修改完代码后必须进行严格的语法校验**（YAML 用 LSP/`actionlint`，Python 用 `python3 -c "import ast; ast.parse(open(...).read())"` 或 `ruff`，Shell 用 `shellcheck`）。

## 文档同步
- 每次执行完任务后，必须检查 README.md 和 AGENTS.md 是否需要更新（新增/删除/重命名了文件、功能、配置项，或新增了全局规则等）。

## 工作流保护
- **绝对禁止**修改、删除以下关键步骤：`Generate release tag`、`Upload firmware to release`、`Auto fix with AI on failure`、`Delete workflow runs`。
  - 说明：`Delete workflow runs` 步骤必须保留，但其内容可以改为指向集中式清理的说明性消息。
- 必须使用集中式 `AI_Auto_Fix_Monitor.yml` + `custom_scripts/auto_fix_with_AI_LLM.py`，不允许在每个单独编译工作流里重复复制 AI 逻辑。
- 工作流运行记录清理使用集中式 `cleanup-workflow-runs.yml` + `custom_scripts/cleanup_workflow_runs.py`，按工作流分别保留最新2个成功和2个失败的运行记录。

## 仓库同步保护（防误删）
- **绝对禁止** `gh repo sync --force`。本仓库历史上已因该命令导致 28+ 文件被上游模板 `P3TERX/Actions-OpenWrt` 覆盖丢失（2026-05-01 事故）。
- 如需同步上游更新，必须手动选择文件 diff 合并，**绝不**使用 `--force` 全量覆盖。
- AI Fix Monitor 包含文件数量异常检测：当 `.github/workflows/` 或 `custom_scripts/` 目录文件数变化 ≥ 20% 时，自动拒绝修改并报告异常。
- 建议在 GitHub 仓库 Settings 中断开 Template 关联，彻底断绝误操作路径。

## 模型与 API 选择
- opencode 用什么模型必须根据用户提供的 secrets 环境变量读取 key，可选 `_proxy_url` 和 `_model_list`，此要求全局生效。
- opencode Zen 对 mimo-v2-pro 已不再免费，不要优先选择它。
- 动态模型解析逻辑必须实时抓取 Artificial Analysis 排行榜数据，不能长期依赖硬编码列表。
- **只使用当前排行榜前 20 的模型**（如 GLM-5.1、GLM-5、Kimi K2.5、Gemma 4 31B、Qwen3.5-398B、DeepSeek-V3.2 等），绝对不要使用已落榜的旧模型（如 GLM-4、Qwen2、GPT-4o、Claude 3.5 等）。保底模型也必须满足此要求。
- **模型列表不得硬编码**，必须运行时实时从 Artificial Analysis 排行榜抓取。排行榜抓取失败时不过滤（放行所有模型），而不是退回硬编码列表。硬编码的模型列表一两个月就会过时。
- **允许缓存兜底**：实时抓取成功后必须把结果写回缓存文件（如 `.leaderboard_cache.json`），供下次抓取失败时兜底。缓存超过 14 天未更新时必须打印警告但仍可使用。无论是本地还是 GitHub Action 中，只要有自动回退机制，就可以用缓存兜底，但必须保证每一两周至少爬一次排行榜更新缓存，不能长期不更新。
- 优先选择排行榜前 20 且有免费资源的模型。当前已知免费渠道：
  - AtomGit：`zai-org/GLM-5`、`Qwen/Qwen3.5-397B-A17B`（无限量，500次/分，端点 `https://api-ai.gitcode.com/v1`）
  - OpenRouter：`qwen/qwen3.6-plus:free`、`qwen/qwen3.6-plus-preview:free`（1M context，429 频发）、`google/gemma-4-31b-it:free`（262K context，~27 tok/s）、`nvidia/nemotron-3-super-120b-a12b:free`（262K context，120B MoE）
  - ZEN：排行榜前 20 的免费模型
  - NVIDIA NIM：`moonshotai/kimi-k2.5`（免费，262K context，1T MoE 32B active，Intelligence Index 46.8，强推理，端点 `https://integrate.api.nvidia.com/v1`）
  - 七牛云：`nvidia/nemotron-3-super-120b-a12b-free`（免费，1M context，120B MoE 12B active，强推理，端点 `https://api.qnaigc.com/v1`）
  - 智谱官方：`GLM-5.1`（付费，排行榜 #13）
- 当日志过长导致超出当前模型上下文时，必须清晰打印提示信息并优雅降级到下一个模型/提供商。
- **MiniMax 白名单**：只允许 MiniMax Coding Plan 2.7（非 highspeed 版本），其他 MiniMax 模型（如 m2.5-free、m1.5、abab 系列等）一律屏蔽。
- 所有 secrets 环境变量（包括 BAILIAN_API_KEY、MOONSHOT_API_KEY、ATOMGIT_API_KEY、ZHIPU_API_KEY、NVIDIA_NIM_API_KEY、QINIU_API_KEY 等）必须在 AI Fix workflow 中完整暴露。

## opencode 配置
- opencode.json 必须使用合法 schema：`provider` 必须为 record 对象，不能用字符串或复数形式。
- **自定义 provider（atomgit、zhipu、nvidia-nim、qiniu 等）必须包含 `npm`、`options`（含 `baseURL` + `apiKey`）、`models` 三个字段**，否则 opencode 会报 `ProviderModelNotFoundError`。内置 provider（anthropic、openai、openrouter 等）只需 `models` 字段。
- **自定义 provider 的 `apiKey` 必须使用实际环境变量值**（通过 `os.getenv()` 在生成配置时读取并填入），禁止在 JSON 中使用 `{{env:...}}` 模板语法。opencode 不会自动展开该模板，导致 API 认证失败、请求超时或 `Unauthorized/401` 错误。
- `oh-my-opencode run` 必须指定 `--agent build`，否则默认使用不存在的 "Sisyphus - Ultraworker" agent 导致报错。`opencode run` 不需要 `--agent` 参数（使用默认 primary agent）。
- 必须安装 opencode 本体和 oh-my-openagent 插件（npm 包名 `oh-my-openagent`，CLI 命令名仍为 `oh-my-opencode`）。
- oh-my-openagent 的多 agent 协同效果更好，优先使用。

## 近期修复记录
- 2026-05-07: 修复 `diy-part1.sh` bash 双引号导致 `$(COMMITCOUNT)` 被误解析为命令的问题。
- 2026-05-07: 修复 `Build_OpenWrt_Firmware.yml` base-files 版本覆盖逻辑，移除非法 `VERSION:=r1`，改为仅修复 `PKG_RELEASE:=1`，避免 APK `package version is invalid`。
- 2026-05-07: 修复 `Build_Lienol_OpenWrt_1_for_XIAOMI_R4.yml` 内核配置，补充 `CONFIG_CRYPTO_DEV_EIP93_DES=y` 和 `CONFIG_CRYPTO_DEV_EIP93_AEAD=y`，解决 Lienol 6.12 syncconfig 交互失败。
- 2026-05-07: 修复 `auto_fix_with_AI_LLM.py` API URL 拼接逻辑，兼容 Zhipu `/v4` 端点。
- 2026-05-07: 优化 `pick_best_model.py` 新增 `--ranked` 标志，支持输出多提供商优先列表，提升 Track 3 模型 fallback 成功率。
- 2026-05-07: 优化 `AI_Auto_Fix_Monitor.yml` Track 3 配置生成逻辑，避免 `oh-my-opencode install` 无 provider 警告；使用 `--ranked` 构建 fallback 模型列表。
- 2026-05-07: 优化 `AI_Auto_Fix_Monitor.yml` artifact 下载逻辑：增加 `gh run view` 和 `gh run download` 兜底提取，避免 error-log 缺失导致 AI Fix 中断。
- 2026-05-07: 优化 `AI_Auto_Fix_Monitor.yml` Track 3 模型策略：MODEL_TIMEOUT 从 1200s 降至 600s，MAX_MODEL_TRIES 从 3 增至 5。
- 2026-05-07: 优化 Build 工作流：当 `extract_last_error.py` 失败时，自动从 openwrt/*.log 创建兜底 last_error.log。
- 2026-05-07: 修复 `Build_OpenWrt_Firmware.yml` 缓存配置：移除 `build_dir`（体积过大导致 actions/cache post-step 上传失败，造成 job 假失败）。保留 `staging_dir` 和 `ccache` 缓存。
- 2026-05-08: 修复 `pick_best_model.py` 和 `dmxapi_meta_router.py` 中 opencode.json 的 API key 模板语法问题（`{{env:...}}` 替换为实际环境变量值），避免 oh-my-opencode 认证失败或超时。
- 2026-05-08: 优化 `AI_Auto_Fix_Monitor.yml` Track 3：增加生成配置脱敏打印、退出码打印、`TIMEOUT_EXIT` 重置、增强错误关键词匹配（401/Unauthorized），提升调试能力。
- 2026-05-08: 修复 `validate_build_output.py` 在 .bin 文件为损坏符号链接时崩溃的 bug，添加异常捕获避免 Build Quality Gate 假失败。
- 2026-05-08: 优化 `AI_Auto_Fix_Monitor.yml` Track 3：跳过 API key 为空的模型，避免浪费尝试次数；修复 prompt 生成段落的缩进不一致。
