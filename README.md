# 小米路由器 4 OpenWrt 自动构建

本仓库只从 [OpenWrt 官方源码](https://github.com/openwrt/openwrt) 的 `main` 分支构建 Xiaomi Mi Router 4（`ramips/mt7621`）固件。

Lienol 源、Phase 1/2 分阶段构建、MEGA 中转和 AI 自动合并 PR 均已移除。它们曾用于缩短长时间构建的排错周期，不属于最终构建架构。

## 使用方法

1. 打开仓库的 Actions 页面。
2. 选择 `Build OpenWrt Firmware for Xiaomi Mi Router 4`。
3. 点击 `Run workflow`。
4. 构建通过后，从本次运行的 Artifact 或对应 GitHub Release 下载文件名同时包含 `mi-router-4` 和 `sysupgrade` 的 `.bin` 固件。

官方源码更新检查每 10 小时运行一次；检测到新提交后会触发同一个构建工作流。修改构建配置、DIY 脚本、自动更新插件或工作流本身并推送到主分支时，也会触发构建。

## 相比 OpenWrt 上游，最终固件有哪些变化

| 项目 | 本仓库固件中的体现 |
|---|---|
| 目标设备 | 固定为 Xiaomi Mi Router 4，目标为 `ramips/mt7621` |
| 管理地址 | LAN 默认地址改为 `192.168.88.1` |
| Web 管理 | 启用 LuCI、Bootstrap 主题和简体中文 |
| 拨号 | 显式启用 PPP、PPPoE、内核 PPP/PPPoE/PPPoX 模块和 `luci-proto-ppp` |
| DNS | 使用 `dnsmasq-full` 的 nftables 支持，并加入 SmartDNS |
| 去广告 | 加入 `adblock-fast` 及中文 LuCI 界面 |
| 代理 | 加入精简的 SSR Plus：nftables 透明代理、Shadowsocks/SSR libev 客户端、simple-obfs 和 dns2socks；不打包 V2Ray、Xray、Trojan 或 sing-box |
| 网络管理 | 加入 LuCI QoS、usteer、ttyd 和 attended sysupgrade |
| 自动更新 | 加入本仓库的 `luci-app-autoupdate`，只识别 `OpenWRT.org_` Release 和 Mi Router 4 的 sysupgrade 固件 |
| 根文件系统 | SquashFS，分区大小配置为 100 MiB；同时生成 initramfs 供调试使用 |
| 附加 feed | 加入 `fw876/helloworld`，用于提供 SSR Plus 相关包 |
| 兼容修复 | 构建前修复 `base-files` 的 APK 版本字段，并运行 DTS `nvmem-layout` 兼容修复 |

为控制闪存占用和依赖复杂度，配置明确禁用了重复或较重的功能，包括 PassWall/OpenClash 类全家桶依赖、V2Ray/Xray/Trojan/sing-box、AdGuard Home、mwan3、PBR、keepalived、aria2、EasyMesh、AirConnect、socat、inotify-tools 和 collectd/rrd 组件。

最终生效内容以 [`custom_configs/config_for_OpenWrt_org`](custom_configs/config_for_OpenWrt_org) 为准；OpenWrt `make defconfig` 仍可能根据上游依赖关系补充必要的底层包。

## 构建可靠性

- 所有第三方 GitHub Actions 固定到完整 commit SHA。
- `staging_dir` 缓存键同时包含 OpenWrt 源码提交、各 feed 提交和本仓库配置哈希，避免旧工具链污染新源码。
- 先并行编译，失败后以单线程日志重试，并将真正的失败日志上传为 `error-log` Artifact。
- 构建质量门只接受 `ramips/mt7621` 下、名称匹配 `mi-router-4`、包含 `sysupgrade` 且至少 8 MiB 的固件。
- 质量门还要求 `root.orig-*` 存在且非空，防止空壳固件进入 Release。
- Release 只保留同一标签前缀最近 3 个版本；工作流运行记录由集中清理任务维护。

## 自动更新安全边界

路由器上的自动更新脚本会：

- 只读取标签以 `OpenWRT.org_` 开头的 Release；
- 只选择名称同时匹配 `mi-router-4` 和 `sysupgrade` 的 `.bin`；
- 拒绝小于 8 MiB 的文件；
- 下载后及刷写前各执行一次 `sysupgrade -T`；
- 默认只下载、不自动刷写；只有启用 `auto_install` 或手动执行 `autoupdate.sh install` 才会刷写；
- 支持每 6 小时、每天或每周检查，cron 每小时唤醒一次后由脚本判断是否到期。

## AI 自动修复

`AI Auto Fix Monitor` 只监听官方 OpenWrt 构建失败。它下载真实失败日志，依次尝试 OpenCode 模型，并且仅在以下条件同时满足时才提交：

1. OpenCode 命令正常退出；
2. 产生了非缓存、非临时文件的真实源码差异；
3. 没有修改受保护的 AI 配置；
4. YAML、Python 和 Shell 基础语法检查通过；
5. 两个与修复模型不同家族的评审模型均明确返回 `VERDICT: PASS`。

评审模型不足、输出格式异常、日志缺失、推送冲突或任何评审失败都会关闭本次自动修复，不会“跳过评审直接通过”。

## 工作流

- `Build_OpenWrt_Firmware.yml`：唯一固件构建、质量验证和 Release 发布流程。
- `update_checker_for_OpenWrt_org.yml`：检测 OpenWrt 官方源码更新并触发构建。
- `AI_Auto_Fix_Monitor.yml`：失败后执行单一 OpenCode 修复路径。
- `cleanup-workflow-runs.yml`：集中清理历史工作流运行记录。

## 维护约束

严禁执行 `gh repo sync --force`。本仓库虽起源于 Actions-OpenWrt 模板，但已包含设备配置、固件插件和构建安全检查；同步上游模板时只能逐文件比较和合并。

## 致谢与许可

构建框架源自 [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt)，固件源码来自 [OpenWrt](https://github.com/openwrt/openwrt)，SSR Plus feed 来自 [fw876/helloworld](https://github.com/fw876/helloworld)。

本仓库沿用 [MIT License](LICENSE)。
