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
- **AI 优化**：
  - `pick_best_model.py --ranked` 输出多提供商优先列表，Track 3 fallback 更健壮
  - `AI_Auto_Fix_Monitor.yml` Track 3 安装步骤避免无 provider 警告
  - AI Fix artifact 下载增加 `gh run view` / `gh run download` 兜底，避免 error-log 缺失中断修复
  - Track 3 模型超时从 20min 降至 10min，最大尝试数从 3 增至 5
  - Build 工作流增加 `last_error.log` 兜底生成逻辑
  - 修复 `Build_OpenWrt_Firmware.yml` 缓存配置：移除 `build_dir`，避免 actions/cache post-step 上传失败导致 job 假失败
  - 修复 `pick_best_model.py` / `dmxapi_meta_router.py` opencode.json API key 模板语法（`{{env:...}}` → 实际值），避免 Track 3 认证失败/超时
  - Track 3 增加配置脱敏打印、退出码输出、`TIMEOUT_EXIT` 重置、错误关键词匹配（401/Unauthorized）

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
