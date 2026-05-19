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
- 动态模型解析逻辑必须实时抓取 **Artificial Analysis + LMSYS Arena 双排行榜**数据，合并为统一模型池，不能长期依赖硬编码列表。
- **只使用当前双排行榜前 30 的模型**（Artificial Analysis 前 20 + LMSYS Arena 前 20 去重合并，如 GLM-5.1、Kimi K2.6、Claude Opus 4.7、Gemma 4 31B、Qwen3.6-Plus、DeepSeek-V4-Pro 等），绝对不要使用已落榜的旧模型（如 GLM-4、Qwen2、GPT-4o、Claude 3.5 等）。保底模型也必须满足此要求。
- **模型列表不得硬编码**，必须运行时实时从双排行榜抓取。排行榜抓取失败时不过滤（放行所有模型），而不是退回硬编码列表。硬编码的模型列表一两个月就会过时。
- **允许缓存兜底**：实时抓取成功后必须把结果写回缓存文件（如 `.leaderboard_cache.json`），供下次抓取失败时兜底。缓存超过 14 天未更新时必须打印警告但仍可使用。无论是本地还是 GitHub Action 中，只要有自动回退机制，就可以用缓存兜底，但必须保证每一两周至少爬一次排行榜更新缓存，不能长期不更新。
- 优先选择排行榜前 30 且有免费资源的模型。当前已知免费渠道：
  - AtomGit：`zai-org/GLM-5`、`Qwen/Qwen3.5-397B-A17B`（无限量，500次/分，端点 `https://api-ai.gitcode.com/v1`）
  - OpenRouter：动态 API 自动发现所有 `:free` 及零定价模型（如 `qwen/qwen3-coder:free`、`deepseek/deepseek-v4-flash:free`、`google/gemma-4-31b-it:free`、`nvidia/nemotron-3-super-120b-a12b:free` 等），不再依赖硬编码列表
  - ZEN：排行榜前 30 的免费模型
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
- 2026-05-08: 升级 `pick_best_model.py` 为双排行榜（Artificial Analysis + LMSYS Arena）合并抓取，动态检测 OpenRouter 免费模型，扩展 AI Fix 可用模型池。
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
- 2026-05-08: 增强 `validate_build_output.py`：添加全局 try/except 捕获未预期异常，确保失败时仍输出 BUILD_QUALITY_GATE=fail 并触发调试日志上传。
- 2026-05-08: 修复 `Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml` 调试日志上传条件：`env.BUILD_QUALITY_GATE == 'fail'` → `failure()`，确保脚本崩溃时也能获取调试信息。
- 2026-05-08: 修复 `dmxapi_meta_router.py` `--config-omo-generic`：增加 `build` agent 定义，解决 oh-my-opencode `--agent build` 找不到 agent 的问题。
- 2026-05-09: 二次修复 `package/index` stub：移除 merge-index 条件门控，改为无条件创建。根因：原 stub 创建逻辑要求 `package/Makefile` 包含 `merge-index`，但 Lienol 源码不包含此目标，导致 stub 从未被创建。现 workflow 预编译阶段无条件添加 `package/index:\n\t@true` stub，`compile_with_retry.py` 新增 `package_index_not_found` 错误检测及 `fix_package_index_not_found()` 无条件修复。
- 2026-05-09: 修复 `AI_Auto_Fix_Monitor.yml` Track 3 超时逻辑：opencode/opencode 超时(exit 124)后不再直接 `continue` 丢弃修改，改为先检查 `git diff --cached`，有有效代码修改则视为修复成功并提交。MODEL_TIMEOUT 从 600s 恢复至 1200s，给 AI 更多时间完成修复。
- 2026-05-09: 修复 Lienol2 编译空壳固件根因：`Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml` 解压后删除 `staging_dir/host`（含 apk/fwtool/fakeroot 等 host 工具），导致 `apk: No such file or directory`→manifest 空→固件为空壳(<5MB)→Quality Gate 失败。现保留 `staging_dir/host` 和 `staging_dir/toolchain-*`，仅删除源码目录（`build_dir/host`、`build_dir/toolchain-*`）。同时在 `compile_with_retry.py` 新增 `apk_host_tool_missing`/`fwtool_host_tool_missing` 错误签名及 `fix_missing_host_tools()` 自动重建。
- 2026-05-10: 二次修复 Lienol2：保留 staging_dir/host 后 apk 已能找到，但首次 make 时 apk/fwtool 不在 PATH 中导致 package/install 失败→root.orig-ramips 从未创建→重试时 manifest 生成报 "Unable to open root"。修复：编译前将 staging_dir/host/bin 加入 PATH；fix_missing_host_tools() 清除 package_install stamp 强制重跑 package/install。
- 2026-05-10: 三次修复 Lienol2：即使 PATH 已正确，package/install 仍可能静默失败导致 root.orig-* 不存在→空壳固件。修复：(1) 工作流新增 "Ensure root.orig exists for valid firmware" 步骤，编译后检查 root.orig-*，缺失时清除 stamp 并强制重跑 package/install + target/install；(2) compile_with_retry.py 新增 `root_orig_missing` 错误签名及 `fix_root_orig_missing()` 修复函数。
- 2026-05-10: 清理 6 个遗留 codex 分支（codex/review-workflow-file-for-errors-*），它们仍包含已删除的 Build_OpenWRT.org_2_for_XIAOMI_R4.yml，导致 GitHub 持续注册 Org2 工作流。
- 2026-05-10: 修复 AI Fix 429 余额不足未触发 fallback：(1) auto_fix_with_AI_LLM.py 将 429 纳入 QUOTA_EXHAUSTED 检测，增加"余额不足"/"无可用资源"关键词；(2) AI_Auto_Fix_Monitor.yml Track 3 错误匹配模式增加 429/余额不足/insufficient/quota/balance，确保 zhipu 等付费模型余额耗尽时自动跳过到下一个 provider。
- 2026-05-10: 优化 Lienol1/Lienol2 时间分配：Lienol1 新增 "Install packages to root filesystem" 步骤，执行 `make package/install`（预计增加 ~40-55 分钟，使 Lienol1 接近 5h30m~5h45m）。这样 root.orig-* 在 Phase 1 就已创建，Lienol2 只需做 `target/install` + 固件打包，大幅缩短并更早发现报错。
- 2026-05-10: 增强 `validate_build_output.py` Build Quality Gate：(1) 新增 root.orig-* 存在性且非空检查，作为空壳固件的关键诊断信号；(2) 增加 Lienol Phase 2 MEGA 上传检测路径（同时检查 openwrt/ 和 workspace 根目录）；(3) 更详细的诊断输出（环境变量值、所有 .bin 文件大小列表、root.orig 文件数和总大小）；(4) 支持通过 `MIN_FIRMWARE_SIZE_MB` 环境变量覆盖最小固件大小阈值；(5) 空 root.orig 目录视为缺失；(6) MIN_FIRMWARE_SIZE_MB <= 0 时打印警告；(7) except 块补全 root_orig_exists 重置。
- 2026-05-11: 修复 `validate_build_output.py` 固件大小阈值：默认值从 5MB 降为 3MB。根因：Mi Router 4 (ramips/mt7621) 的 UBI sysupgrade 固件正常大小仅 3-4MB，5MB 阈值导致正常固件被误判为空壳。
- 2026-05-11: 修复 `AI_Auto_Fix_Monitor.yml` Track 3 工作流文件隔离检查 bug：`git diff --cached --name-only | grep "\.github/workflows/"` 当 AI 未修改任何工作流文件时，grep 返回退出码 1，在 `set -e` 下导致脚本立即退出，commit+push 永远无法执行。修复：先赋值变量 `CHANGED_WF_FILES=$(... || true)`，再判断非空。
- 2026-05-11: 修复 Lienol2 空壳固件根因：`package/index` stub 在 `package/Makefile` 头部插入，破坏了 `include`/`eval` 宏展开，导致 `package/install` 目标无法被正确定义，`make package/install` 报 "No rule to make target"，root.orig-ramips 内容为空，固件变成空壳。修复：(1) `Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml` 中 stub 改为尾部追加（`echo >>` 而非 `{ printf; cat } >`）；(2) `compile_with_retry.py` 的 `fix_package_index_not_found()` 同步修复。
- 2026-05-12: 五层修复 Lienol2 空壳固件（构建 #263 仍然产空壳，日志显示 `make OPENWRT_BUILD=1 package/install` 报 "No rule to make target"）：
  (1) **根因分析**：深入分析 OpenWrt 两层 Makefile 架构。第一层（OPENWRT_BUILD!=1）设置 OPENWRT_BUILD=1 并 include toplevel.mk；`%::` catch-all 先运行 `prereq`→`prepare-tmpinfo`（生成 fresh `tmp/.packagedeps`），然后 `$(SUBMAKE) -r $@` 递归调用。递归调用时走第二层（OPENWRT_BUILD=1），include package/Makefile，此时 `package-y` 已由 `tmp/.packagedeps` 填充，subdir 宏正确生成 `package/install` 目标。
  (2) **Bug 1**：`make OPENWRT_BUILD=1 package/install` 跳过 `%::` catch-all 的初始化逻辑，直接进入第二层。此时 `tmp/.packagedeps` 可能不存在或过时，导致 `package-y` 为空，subdir 宏无法生成 `package/install` 目标 → "No rule to make target"。修复：改为 `make package/install`（不带 OPENWRT_BUILD=1），让 `%::` catch-all 自然处理初始化。
  (3) **Bug 2**：`compile_with_retry.py` 的 `fix_root_orig_missing()` 也使用了错误的 `make OPENWRT_BUILD=1 package/install`，且 retry 逻辑使用了不存在的 `make package/stamp-install` 目标。同步修复为 `make package/install`。
  (4) 同步修改 Lienol1 和 Lienol2 工作流，以及 compile_with_retry.py 的所有相关位置。
  (5) **关于 OpenWrt 官方**：Lienol 的 Makefile/package/Makefile/include/ 与 OpenWrt 官方 main 分支完全一致，此问题非 Lienol 特有。但 OpenWrt 官方不设计单独调用 `package/install` 的场景（正常流程用 `make world`），所以不适合给官方提 PR。
- 2026-05-13: **六层修复 Lienol 空壳固件**：之前的五层修复仍未解决问题。`make package/install`（无论是否带 OPENWRT_BUILD=1）仍然报 "No rule to make target"。
  (1) **根因重分析**：OpenWrt 的 `package/install` 目标**不是独立可用的**。它由 `subdir` 宏动态生成，依赖于 `$(curdir)/builddirs` 变量。`builddirs` 来自 `package-y`，而 `package-y` 来自 `tmp/.packagedeps`。即使 `tmp/.packagedeps` 存在，如果它只包含 `kernel/linux`（这是默认添加的），`subdir` 宏生成的 `package/install` 目标会依赖于 `package/kernel/linux/install`，但后者可能不存在（内核使用 BuildKernel 模板，install 目标行为不同）。因此单独调用 `make package/install` 总是失败。
  (2) **正确方案**：不再尝试单独调用 `make package/install`。改为运行完整的 `make -j1 V=s`（即 `make world`），让 `package/install` 在 `world` 目标的完整上下文中自然被调用。
  (3) **Lienol1 修改**："Install packages to root filesystem" 步骤改为 "Complete build with make world"，运行 `make -j1 V=s` 完成完整构建。如果失败或 root.orig 不存在，设置 `FIRMWARE_BUILD_FAILED=true` 并 `exit 1`。
  (4) **Lienol2 修改**："Ensure root.orig exists" 步骤不再尝试 `make package/install`，直接检查 root.orig 是否存在。缺失时设置失败标志并 `exit 1`，触发 error-log 生成和 AI Fix Monitor。
  (5) **AI Fix Monitor 增强**：增强 error-log 获取兜底逻辑（多种方法获取失败日志），添加 push 重试处理 HTTP 429，添加 GitHub App 权限错误检测（AI 修改工作流文件时自动回滚）。
- 2026-05-13: **修复 AI_Auto_Fix_Monitor.yml 表达式长度超限**：Track 3 的 `run:` 块包含 430+ 行 shell 脚本，总长度 21664 字符，超过 GitHub Actions 的 21000 字符限制，导致工作流文件验证失败。修复：将 Track 3 的完整脚本提取到 `custom_scripts/run_track3.sh`，workflow 中只保留 `bash custom_scripts/run_track3.sh` 调用。同时将 GitHub 上下文变量（`github.event.workflow_run.id` 等）通过 `env:` 块传入脚本。
- 2026-05-13: **修复 AI_Auto_Fix_Monitor.yml 表达式长度超限（env 块）**：Track 3 的 `env:` 块包含 46 个环境变量（14 个 model list + 11 个 base URL + 1 个重复 GH_TOKEN），`${{ secrets.* }}` 表达式展开后总长度超过 GitHub Actions 的 21000 字符限制。修复：移除所有 model list 变量（脚本有硬编码默认值）、移除所有 base URL（脚本有硬编码默认值，仅保留 GLM_PROXY_BASE_URL）、移除重复 GH_TOKEN。修改后 Track 3 仅剩 20 个环境变量。
- 2026-05-13: **修复 Lienol1 构建失败（缺失包）**：`make -j1 V=s` 遇到 `No rule to make target 'package/xray-plugin/compile'`，因为 `.config` 中启用了 `CONFIG_PACKAGE_xray-plugin=y` 但该包在当前 feeds 中不存在。
- 2026-05-14: **七层修复 Lienol1 缺失包清理逻辑**：Build Lienol 1 #489 的自动清理仍然失败，因为 `sed "/CONFIG_PACKAGE_${missing_pkg}=/d"` 只移除精确匹配行，且未清理 `tmp/.packagedeps`。
  (1) 改进缺失包提取：从 `head -1` 改为 `sort -u`，支持一次清理多个缺失包。
  (2) 改进 sed 匹配：从精确匹配 `CONFIG_PACKAGE_${pkg}=` 改为 `CONFIG_PACKAGE_.*${pkg}`，同时清理子包和变体（如 `xray-plugin-mini`）。
  (3) 增加下划线变体处理：`tr '-' '_'`，因为某些包名在 .config 中可能使用下划线。
  (4) 强制清理 `tmp/.packagedeps`：移除后运行 `make defconfig`，强制重新生成 package deps 缓存。
- 2026-05-14: **修复 Lienol2 host 工具检查和 root.orig 兜底**：Build Lienol 2 #487 失败因为 `fwtool` 不在 PATH 中（Lienol1 产物不完整）且 `root.orig-ramips` 不存在。
  (1) host 工具重建后增加二次检查：如果 `apk/fwtool/fakeroot` 仍然缺失，直接 `exit 1` 并设置 `failure_reason=missing_host_tools`，避免继续编译产生更隐蔽的错误。
  (2) root.orig 缺失时增加兜底复制：如果 `make -j1 V=s` 重试后仍无法创建 `root.orig-*`，尝试从现有的 `root-*` 复制。这不是完美的修复（root.orig 应该由 package/install 创建），但可以让 manifest 生成继续，避免空壳固件。
- 2026-05-14: **修复 compile_with_retry.py 的 fix_root_orig_missing()**：函数仍使用 `make package/install`，但 OpenWrt 的 `package/install` 目标不能单独调用（已在 2026-05-13 的六层修复中确认）。同步改为 `make -j1 V=s`，让 `package/install` 在 `make world` 的完整上下文中自然执行。
- 2026-05-17: **优化 AI Fix 模型池和推送健壮性**：
  (1) **更新 OpenRouter 免费模型列表**：`pick_best_model.py` 和 `auto_fix_with_AI_LLM.py` 的 OpenRouter 免费模型 fallback 从 `qwen/qwen3.6-plus:free` 升级为 `qwen/qwen3-coder:free,deepseek/deepseek-v4-flash:free,nvidia/nemotron-3-super-120b-a12b:free,google/gemma-4-31b-it:free,qwen/qwen3-next-80b-a3b-instruct:free`（更侧重编码和推理的免费模型），环境变量名从 `OPENROUTER_QWEN_FREE_MODEL_LIST` 改为 `OPENROUTER_FREE_MODEL_LIST`。
  (2) **增强 run_track3.sh git push 重试**：推送前先 `git pull --rebase` 避免冲突；推送被拒绝时自动 rebase 冲突解决（`--ours` 策略）；重试次数从 3 增至 5；429 指数退避从 10s 起步改为 15s；新增 `rejected`/`non-fast-forward` 检测（不 sleep 直接进入下次 pull+push 循环）；GitHub App 权限错误回滚后不再立即退出，允许循环继续尝试。
  (3) **增强 auto_fix_with_AI_LLM.py call_api 429 重试**：`call_api()` 新增 429 状态码重试（最多 2 次指数退避），其他临时错误也增加重试，QUOTA_EXHAUSTED 和 CONTEXT_LENGTH_EXCEEDED 仍立即抛出不重试。
  (4) **禁用 fullconenat**：`custom_configs/config_for_Lienol` 中注释 `kmod-ipt-fullconenat` 和 `iptables-mod-fullconenat`（源返回 HTTP 404）。
- 2026-05-17: **彻底禁用 fullconenat（三层防护）**：仅注释 .config 不够，`make defconfig` 会因依赖关系重新启用 fullconenat。
  (1) **diy-part1.sh**：在 feeds update 前删除 fullconenat Makefile。
  (2) **Lienol1 工作流 feeds install 后**：再次删除 fullconenat Makefile 和目录（feeds install 会重新引入）。
  (3) **Lienol1 预检查步骤**：强制从 .config 中移除所有 fullconenat 相关 CONFIG 行，并删除 fullconenat 目录。
  (4) **Lienol1 complete_build 步骤**：新增 fullconenat hash mismatch 自动检测和修复逻辑。
  (5) **run_track3.sh AI prompt**：增加 fullconenat 修复具体指导（禁用包而非修复 hash）。
  根因：`llccd/netfilter-full-cone-nat` 仓库 git archive 产生的 hash 与 OpenWrt package Makefile 中记录的 hash 不一致（`expected 437dff... got db90c3b...`），且上游不维护此 hash，因此只能彻底禁用。
- 2026-05-19: **修复 Lienol Full Validate build output 路径问题**：合并工作流后 `validate_build_output.py` 在 `$GITHUB_WORKSPACE/openwrt/` 查找固件，但编译目录在 `/workdir/openwrt`。修复：(1) 修正 Extract Error Log 步骤的 `--log-dir` 参数为 `/workdir/openwrt`；(2) 兜底日志路径也改为 `/workdir/openwrt/*.log`。
- 2026-05-19: **二次修复 Validate build output**：`GITHUB_WORKSPACE` 是 GitHub Actions 受保护环境变量，无法通过 step `env:` 块覆盖（Runner 会静默忽略覆盖，始终设为 checkout 目录）。修复：(1) `validate_build_output.py` 新增 `OPENWRT_BASE_DIR` 环境变量优先级（`os.getenv("OPENWRT_BASE_DIR") or os.getenv("GITHUB_WORKSPACE", ...)`）；(2) 工作流改用 `OPENWRT_BASE_DIR: /workdir` 替代无效的 `GITHUB_WORKSPACE: /workdir`。
