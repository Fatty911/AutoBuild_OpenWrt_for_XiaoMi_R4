**English** | [中文](https://p3terx.com/archives/build-openwrt-with-github-actions.html)

# Actions-OpenWrt

[![LICENSE](https://img.shields.io/github/license/mashape/apistatus.svg?style=flat-square&label=LICENSE)](https://github.com/P3TERX/Actions-OpenWrt/blob/master/LICENSE)
![GitHub Stars](https://img.shields.io/github/stars/P3TERX/Actions-OpenWrt.svg?style=flat-square&label=Stars&logo=github)
![GitHub Forks](https://img.shields.io/github/forks/P3TERX/Actions-OpenWrt.svg?style=flat-square&label=Forks&logo=github)

A template for building OpenWrt with GitHub Actions

## Usage

- Click the [Use this template](https://github.com/P3TERX/Actions-OpenWrt/generate) button to create a new repository.
- Generate `.config` files using [Lean's OpenWrt](https://github.com/coolsnowwolf/lede) source code. ( You can change it through environment variables in the workflow file. )
- Push `.config` file to the GitHub repository.
- Select `Build OpenWrt` on the Actions page.
- Click the `Run workflow` button.
- When the build is complete, click the `Artifacts` button in the upper right corner of the Actions page to download the binaries.

## Tips

- It may take a long time to create a `.config` file and build the OpenWrt firmware. Thus, before create repository to build your own firmware, you may check out if others have already built it which meet your needs by simply [search `Actions-Openwrt` in GitHub](https://github.com/search?q=Actions-openwrt).
- Add some meta info of your built firmware (such as firmware architecture and installed packages) to your repository introduction, this will save others' time.

## 本项目自定义

- **AI 自动修复**：构建失败时 `AI_Auto_Fix_Monitor.yml` 自动触发多模型 AI 修复并推送
- **多源编译**：支持 Lienol、OpenWrt.org（通过 `Build_OpenWrt_Firmware.yml`）
- **自动清理**：`cleanup-workflow-runs.yml` 每日清理构建历史
- **已知修复**：
  - base-files APK 版本兼容（`diy-part1.sh` 与 workflow 双重修复，避免 `package version is invalid`）
  - Lienol 内核 6.12 `CRYPTO_DEV_EIP93_AES/DES/AEAD` syncconfig 交互失败自动注入配置
  - Track 2 Zhipu API URL 拼接兼容 `/v4` 端点
  - `make package/index` 目标不存在（OpenWrt 主分支迁移 APK 后改为 `package/merge-index`，workflow 预编译阶段无条件添加 `@true` stub，`compile_with_retry.py` `fix_package_index_not_found()` 无条件修复）
  - Lienol 2 `staging_dir/host` 被误删导致 `apk: No such file or directory`→固件空壳（现保留 `staging_dir/host` 和 `staging_dir/toolchain-*`，仅删源码目录；`compile_with_retry.py` `fix_missing_host_tools()` 兜底重建）
  - Lienol 2 `package/install` 静默失败导致 `root.orig-*` 不存在→空壳固件（工作流编译后检查 root.orig，缺失时强制重跑 package/install；`compile_with_retry.py` `root_orig_missing` 签名 + `fix_root_orig_missing()` 自动修复）
  - Lienol 1 新增 `make package/install` 步骤（预计增加 ~40-55 分钟，使 Lienol1 接近 5h30m~5h45m），提前创建 root.orig-*，Lienol2 只需做 target/install + 固件打包
  - 清理 6 个遗留 codex 分支，它们仍包含已删除的 Org2 .yml，导致 GitHub 持续注册 Org2 工作流
  - `validate_build_output.py` Build Quality Gate 增强：root.orig-* 非空检查（空壳固件诊断）、Lienol Phase 2 MEGA 检测路径、详细诊断输出、`MIN_FIRMWARE_SIZE_MB` 环境变量覆盖、默认阈值从 5MB 降为 3MB（Mi Router 4 UBI 固件正常仅 3-4MB）
  - 修复 `AI_Auto_Fix_Monitor.yml` Track 3 隔离检查 bug：grep 无匹配时 `set -e` 导致 commit+push 永远无法执行
- **AI 优化**：
  - `pick_best_model.py` 支持双排行榜（Artificial Analysis + LMSYS Arena）合并抓取，并动态发现 OpenRouter 免费模型，显著扩展 Track 3 fallback 模型池
  - `pick_best_model.py --ranked` 输出多提供商优先列表，Track 3 fallback 更健壮
  - `AI_Auto_Fix_Monitor.yml` Track 3 安装步骤避免无 provider 警告
  - AI Fix artifact 下载增加 `gh run view` / `gh run download` 兜底，避免 error-log 缺失中断修复
  - Track 3 模型超时恢复至 20min，最大尝试数 5；超时(exit 124)后检查 `git diff --cached` 保留有效修改，避免 AI 成果被丢弃
  - Build 工作流增加 `last_error.log` 兜底生成逻辑
  - 修复 `Build_OpenWrt_Firmware.yml` 缓存配置：移除 `build_dir`，避免 actions/cache post-step 上传失败导致 job 假失败
  - 修复 `pick_best_model.py` / `dmxapi_meta_router.py` opencode.json API key 模板语法（`{{env:...}}` → 实际值），避免 Track 3 认证失败/超时
  - Track 3 增加配置脱敏打印、退出码输出、`TIMEOUT_EXIT` 重置、错误关键词匹配（401/Unauthorized/429/余额不足/quota/balance）
  - 修复 `validate_build_output.py` 在 .bin 文件为损坏符号链接时崩溃的 bug，避免 Build Quality Gate 假失败
  - 增强 `validate_build_output.py`：全局 try/except 捕获未预期异常，确保失败时仍输出 BUILD_QUALITY_GATE=fail
  - 修复 Lienol 2 调试日志上传条件：`failure()` 确保脚本崩溃时也能获取调试信息
  - 修复 `dmxapi_meta_router.py` `--config-omo-generic` 增加 `build` agent，解决 oh-my-opencode `--agent build` 找不到 agent 的问题
  - Track 3 跳过 API key 为空的模型，避免浪费尝试次数
  - 修复 AI Fix 429/余额不足未触发 fallback：`auto_fix_with_AI_LLM.py` 将 429 纳入 QUOTA_EXHAUSTED 检测；Track 3 错误匹配增加 429/insufficient/quota/balance 关键词
  - Lienol1 缺失包自动清理增强：从精确匹配 `CONFIG_PACKAGE_${pkg}=` 改为 `CONFIG_PACKAGE_.*${pkg}`，支持子包/变体清理，增加下划线变体处理（`tr '-' '_'`），强制清理 `tmp/.packagedeps` 后重跑 `make defconfig`
  - Lienol2 host 工具检查强化：重建后二次检查 `apk/fwtool/fakeroot`，仍缺失时直接 `exit 1` 并设置 `failure_reason=missing_host_tools`，避免继续编译产生隐蔽错误
  - Lienol2 root.orig 兜底复制：重试 `make -j1 V=s` 后仍无法创建 `root.orig-*` 时，从现有的 `root-*` 复制作为兜底，避免 manifest 生成失败导致空壳固件
  - 修复 `compile_with_retry.py` `fix_root_orig_missing()`：同步弃用独立的 `make package/install`（OpenWrt 目标不能单独调用），改为 `make -j1 V=s` 让 `package/install` 在 `make world` 上下文中自然执行
  - 优化 AI Fix 模型池：OpenRouter 免费模型从 `qwen3.6-plus:free` 升级为 `qwen3-coder:free`、`deepseek-v4-flash:free` 等编码/推理优先模型；环境变量 `OPENROUTER_QWEN_FREE_MODEL_LIST` → `OPENROUTER_FREE_MODEL_LIST`
  - 增强 `run_track3.sh` git push 重试：推送前 `git pull --rebase`；rebase 冲突自动解决（`--ours` 策略）；重试 3→5 次；429 退避 10s→15s；新增 `rejected`/`non-fast-forward` 检测
  - 增强 `auto_fix_with_AI_LLM.py` `call_api()` 429 重试：最多 2 次指数退避，`QUOTA_EXHAUSTED` 和 `CONTEXT_LENGTH_EXCEEDED` 仍立即抛出
  - 禁用 fullconenat：`config_for_Lienol` 中注释 `kmod-ipt-fullconenat` 和 `iptables-mod-fullconenat`（源返回 HTTP 404）

> ⚠️ **严禁执行 `gh repo sync --force`！** 本仓库虽基于 P3TERX/Actions-OpenWrt 模板创建，但已高度定制。执行该命令会导致 28+ 个自定义文件被上游模板覆盖丢失。如需同步上游更新，必须手动 diff 合并单个文件。

### 断开模板关联（推荐）
在 GitHub 仓库 Settings → 页面底部找到 "Template repository" → 删除模板来源。断开后 `gh repo sync` 将不再可用，从根本上杜绝误操作。

## Credits

- [Microsoft Azure](https://azure.microsoft.com)
- [GitHub Actions](https://github.com/features/actions)
- [OpenWrt](https://github.com/openwrt/openwrt)
- [coolsnowwolf/lede](https://github.com/coolsnowwolf/lede)
- [Mikubill/transfer](https://github.com/Mikubill/transfer)
- [softprops/action-gh-release](https://github.com/softprops/action-gh-release)
- [GitHub CLI](https://cli.github.com/) (used for workflow cleanup automation)
- [dev-drprasad/delete-older-releases](https://github.com/dev-drprasad/delete-older-releases)
- [peter-evans/repository-dispatch](https://github.com/peter-evans/repository-dispatch)

## License

[MIT](https://github.com/P3TERX/Actions-OpenWrt/blob/main/LICENSE) © [**P3TERX**](https://p3terx.com)
