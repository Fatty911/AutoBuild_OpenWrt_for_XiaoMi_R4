# 仓库级 Agent 规则

本文件只记录此仓库的项目特有约束；全局 Agent 规则仍需同时遵守。

## 当前架构

- 只维护 OpenWrt 官方 `openwrt/openwrt` 的 `main` 分支构建。
- 目标设备固定为 Xiaomi Mi Router 4：`ramips/mt7621`、`xiaomi_mi-router-4`。
- 唯一固件工作流是 `.github/workflows/Build_OpenWrt_Firmware.yml`。
- Lienol、Phase 1/2、MEGA 中转、Track 1/2 和 AI 自动合并 PR 已退出架构，禁止恢复其运行逻辑或缓存文件。
- 构建失败后的自动修复只允许走 `.github/workflows/AI_Auto_Fix_Monitor.yml` 调用 `custom_scripts/run_track3.sh` 这一条 OpenCode 路径。

## 固件必须满足的行为

- LAN 默认地址保持 `192.168.88.1`。
- PPP/PPPoE、LuCI 简体中文、SmartDNS、adblock-fast、QoS、usteer、ttyd、attendedsysupgrade、SSR Plus 精简客户端和 `luci-app-autoupdate` 必须保留。
- SSR Plus 保持 nftables + Shadowsocks/SSR libev 精简组合；除非用户明确要求，不得重新加入 V2Ray、Xray、Trojan、sing-box 或大型代理全家桶。
- `dnsmasq-full` 使用 nftables 支持，不恢复 ipset 变体。
- 不得恢复 inotify-tools；它曾导致干净构建依赖主机 patchelf 而失败。
- 所有功能增删必须同步更新 `custom_configs/config_for_OpenWrt_org` 和 README 的“最终固件变化”表。

## 构建与发布保护

- 不得删除或绕过 `Generate release tag`、`Upload firmware to release`、失败日志上传和 `Delete workflow runs`。
- 构建质量门必须同时验证：
  - 路径为 `ramips/mt7621`；
  - 文件名含 `mi-router-4` 和 `sysupgrade`；
  - 文件至少 8 MiB；
  - `root.orig-*` 存在且非空。
- Release 可以包含调试镜像，但路由器自动更新只能选择目标设备的 sysupgrade 镜像。
- 第三方 Action 必须固定到完整 commit SHA，禁止使用 `@main`、`@master` 或浮动大版本。
- `staging_dir` 缓存必须包含源码提交、feed 提交和配置哈希，不得使用可跨源码提交命中的宽泛 restore key。
- 严禁 `gh repo sync --force`；模板更新只能逐文件合并。

## 自动更新保护

- Release 标签前缀保持 `OpenWRT.org_`。
- 固件资产必须同时匹配 `mi-router-4`、`sysupgrade` 和 `.bin`。
- 下载文件必须至少 8 MiB，并在下载后和刷写前执行 `sysupgrade -T`。
- 默认不自动刷写；`install` 子命令可以显式覆盖该设置。
- 定时任务每小时唤醒，实际检查间隔由 UCI 的 6 小时、每天或每周设置控制。

## AI 自动修复保护

- 必须有真实失败日志；占位日志不得触发盲修。
- OpenCode 命令退出非零、超时、认证失败或限额错误时，不得把工作区差异当作成功。
- 只允许提交真实源码差异；排行榜缓存、模型列表、日志、prompt 和 review 输出不得进入提交。
- `AGENTS.md`、根目录 OMO 配置及 `ai_tools/opencode/` 配置为受保护文件，AI 修复不得修改。
- 评审默认 N=2、M=2；必须排除修复模型同家族，并保证两票来自不同家族。
- 评审模型不足、输出不是精确 `VERDICT: PASS`、无 diff 或任一评审异常时必须失败退出。
- 推送发生冲突时停止并保留证据，禁止用 `ours` 或强推送静默覆盖远端。

## 修改与验证

- 已有文件只能做定向修改，修改前先读取。
- 修改后至少执行与文件类型匹配的检查：
  - GitHub Actions YAML：PyYAML 解析和 `actionlint`；
  - Python：`py_compile`，有测试时再运行测试；
  - Shell：`bash -n`/`sh -n` 和 `shellcheck`；
  - OpenWrt 配置：检查重复键、目标设备、关键包和相互冲突的 `y/n` 条目。
- 修改代码或文档前后均执行多模型共识评审；通过后再提交。
- 推送后监控对应 GitHub Actions。构建时间较长时，至少确认工作流已由新提交正常启动，并持续跟踪到可判断结果。
- 所有回复使用中文。
