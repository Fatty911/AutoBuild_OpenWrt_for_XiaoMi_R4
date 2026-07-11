import importlib.util
import inspect
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    path = REPOSITORY_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_build_output = load_module(
    "validate_build_output",
    "custom_scripts/validate_build_output.py",
)
multi_agent_review = load_module(
    "multi_agent_review",
    "custom_scripts/multi_agent_review.py",
)


class BuildOutputValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.target_dir = (
            self.workspace / "openwrt" / "bin" / "targets" / "ramips" / "mt7621"
        )
        self.target_dir.mkdir(parents=True)
        self.root_orig = (
            self.workspace
            / "openwrt"
            / "build_dir"
            / "target-mipsel_24kc_musl"
            / "root.orig-ramips"
        )
        self.root_orig.mkdir(parents=True)
        (self.root_orig / "etc").mkdir()
        (self.root_orig / "etc" / "openwrt_release").write_text(
            "DISTRIB_ID='OpenWrt'\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_image(self, name: str, size_mb: int = 9) -> Path:
        image = self.target_dir / name
        with image.open("wb") as handle:
            handle.truncate(size_mb * 1024 * 1024)
        return image

    def test_accepts_only_target_sysupgrade_with_nonempty_root(self):
        expected = self.create_image(
            "openwrt-ramips-mt7621-xiaomi_mi-router-4-squashfs-sysupgrade.bin"
        )
        self.create_image(
            "openwrt-ramips-mt7621-xiaomi_mi-router-4-initramfs-kernel.bin"
        )

        with redirect_stdout(io.StringIO()):
            valid = validate_build_output.find_valid_sysupgrade_images(
                self.workspace,
                "ramips/mt7621",
                "mi-router-4",
                8,
            )
            root_orig_valid = validate_build_output.check_root_orig_exists(
                self.workspace
            )

        self.assertEqual(valid, [expected])
        self.assertTrue(root_orig_valid)

    def test_rejects_wrong_device_and_small_image(self):
        self.create_image(
            "openwrt-ramips-mt7621-other-device-squashfs-sysupgrade.bin"
        )
        self.create_image(
            "openwrt-ramips-mt7621-xiaomi_mi-router-4-squashfs-sysupgrade.bin",
            size_mb=4,
        )

        with redirect_stdout(io.StringIO()):
            valid = validate_build_output.find_valid_sysupgrade_images(
                self.workspace,
                "ramips/mt7621",
                "mi-router-4",
                8,
            )

        self.assertEqual(valid, [])

    def test_rejects_oversized_image_when_maximum_is_set(self):
        self.create_image(
            "openwrt-ramips-mt7621-xiaomi_mi-router-4-squashfs-sysupgrade.bin",
            size_mb=10,
        )

        with redirect_stdout(io.StringIO()):
            valid = validate_build_output.find_valid_sysupgrade_images(
                self.workspace,
                "ramips/mt7621",
                "mi-router-4",
                8,
                9,
            )

        self.assertEqual(valid, [])


class AutomationContractTests(unittest.TestCase):
    def test_ssr_plus_configuration_matches_current_helloworld_options(self):
        config = (
            REPOSITORY_ROOT / "custom_configs/config_for_OpenWrt_org"
        ).read_text(encoding="utf-8")
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(
            "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Shadowsocks_Rust_Client=y",
            config,
        )
        self.assertIn(
            "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_ShadowsocksR_Libev_Client=y",
            config,
        )
        self.assertIn(
            "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Shadowsocks_Simple_Obfs=y",
            config,
        )
        self.assertIn(
            "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_NONE_V2RAY=y",
            config,
        )
        self.assertIn(
            "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Xray=n",
            config,
        )
        self.assertIn("CONFIG_PACKAGE_xray-core=n", config)
        self.assertNotIn(
            "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Shadowsocks_Libev_Client",
            config,
        )
        self.assertNotIn(
            "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_DNS2SOCKS",
            config,
        )
        self.assertIn("CONFIG_PACKAGE_dns2socks=n", config)
        self.assertIn("CONFIG_PACKAGE_dns2tcp=y", config)
        self.assertIn("CONFIG_PACKAGE_microsocks=y", config)
        self.assertNotIn("Shadowsocks/SSR libev", readme)
        self.assertNotIn("simple-obfs 和 dns2socks", readme)
        self.assertIn("ENABLE_XRAY=1", readme)
        self.assertIn("OpenClash 支持更多协议", readme)

    def test_autoupdate_requires_target_sysupgrade_and_validation(self):
        script = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/root/usr/bin/autoupdate.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('*"$DEVICE_PATTERN"*sysupgrade*.bin)', script)
        self.assertGreaterEqual(script.count('sysupgrade -T "$FIRMWARE_FILE"'), 1)
        self.assertIn('sysupgrade -T "$output"', script)
        self.assertIn('release_tag_prefix "OpenWRT.org_Kernel_"', script)
        self.assertIn('config_get UPDATE_BASE_URL config update_base_url ""', script)
        self.assertIn("curl_download direct", script)
        self.assertIn("curl_download proxy", script)
        self.assertIn("curl_api direct", script)
        self.assertIn("curl_api proxy", script)
        self.assertIn("[ -s /etc/autoupdate-version ]", script)
        self.assertIn('sysupgrade "$FIRMWARE_FILE"', script)
        self.assertNotIn("sysupgrade -n", script)
        self.assertNotIn("subscription_url", script)
        self.assertNotIn("workflow_name", script)
        self.assertNotIn("*sysupgrade*.bin|*factory*.bin|*kernel*.bin", script)

    def test_autoupdate_defaults_to_download_only_across_all_layers(self):
        workflow = (
            REPOSITORY_ROOT / ".github/workflows/Build_OpenWrt_Firmware.yml"
        ).read_text(encoding="utf-8")
        diy = (REPOSITORY_ROOT / "custom_scripts/diy-part2.sh").read_text(
            encoding="utf-8"
        )
        config = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/root/etc/config/autoupdate"
        ).read_text(encoding="utf-8")
        luci = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/luasrc/model/cbi/autoupdate.lua"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "AUTOPDATE_AUTO_INSTALL: ${{ vars.AUTOPDATE_AUTO_INSTALL || '0' }}",
            workflow,
        )
        self.assertIn('AUTOPDATE_AUTO_INSTALL="${AUTOPDATE_AUTO_INSTALL:-0}"', diy)
        self.assertIn("option auto_install '0'", config)
        self.assertIn('o.default = "0"', luci)

    def test_scheduled_updates_use_hourly_wakeup_and_uci_interval(self):
        workflow = (
            REPOSITORY_ROOT / ".github/workflows/Build_OpenWrt_Firmware.yml"
        ).read_text(encoding="utf-8")
        diy = (REPOSITORY_ROOT / "custom_scripts/diy-part2.sh").read_text(
            encoding="utf-8"
        )
        script = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/root/usr/bin/autoupdate.sh"
        ).read_text(encoding="utf-8")
        config = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/root/etc/config/autoupdate"
        ).read_text(encoding="utf-8")
        cron = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/root/etc/crontabs/root"
        ).read_text(encoding="utf-8")
        obsolete_cron = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/root/etc/cron.d/autoupdate"
        )
        luci = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/luasrc/model/cbi/autoupdate.lua"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "AUTOPDATE_CHECK_INTERVAL: ${{ vars.AUTOPDATE_CHECK_INTERVAL || 'daily' }}",
            workflow,
        )
        self.assertIn(
            'AUTOPDATE_CHECK_INTERVAL="${AUTOPDATE_CHECK_INTERVAL:-daily}"', diy
        )
        self.assertIn("option check_interval 'daily'", config)
        self.assertIn("option last_check '0'", config)
        self.assertIn('config_get CHECK_INTERVAL config check_interval "daily"', script)
        self.assertIn("scheduled_check_due()", script)
        self.assertIn("if scheduled_check_due; then", script)
        self.assertIn('o:value("6hours", _("Every 6 Hours"))', luci)
        self.assertIn('o:value("daily", _("Daily"))', luci)
        self.assertIn('o:value("weekly", _("Weekly"))', luci)
        self.assertIn("17 * * * * /usr/bin/autoupdate.sh scheduled", cron)
        self.assertFalse(obsolete_cron.exists())

    def test_download_only_keeps_firmware_and_install_can_override_seen_release(self):
        script = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/root/usr/bin/autoupdate.sh"
        ).read_text(encoding="utf-8")
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('TEMP_DIR="/tmp/autoupdate-work"', script)
        self.assertIn('DOWNLOAD_DIR="/tmp/autoupdate"', script)
        self.assertIn('local output="$DOWNLOAD_DIR/$FIRMWARE_NAME"', script)
        self.assertNotIn('rm -rf "$DOWNLOAD_DIR"', script)
        self.assertIn(
            'if [ "$FORCE_AUTO_INSTALL" != "1" ] && [ "$LATEST_VERSION" = "$LAST_SEEN_VERSION" ]; then',
            script,
        )

        install_start = script.index("install_firmware()")
        download_only = script.index('if [ "$AUTO_INSTALL" != "1" ]; then', install_start)
        download_mark = script.index(
            'uci set autoupdate.config.last_seen_version="$LATEST_VERSION"',
            download_only,
        )
        download_return = script.index("\t\treturn 0", download_mark)
        validate_before_flash = script.index(
            'if ! sysupgrade -T "$FIRMWARE_FILE"',
            download_return,
        )
        install_mark = script.index(
            'uci set autoupdate.config.last_seen_version="$LATEST_VERSION"',
            validate_before_flash,
        )
        flash = script.index('sysupgrade "$FIRMWARE_FILE"', install_mark)
        self.assertLess(download_only, download_mark)
        self.assertLess(download_mark, download_return)
        self.assertLess(validate_before_flash, install_mark)
        self.assertLess(install_mark, flash)
        self.assertIn("校验后的固件保留在 `/tmp/autoupdate/`", readme)
        self.assertIn("忽略“已处理”标记并强制刷写", readme)

    def test_build_workflow_exposes_resource_and_autoupdate_variables(self):
        workflow = (
            REPOSITORY_ROOT / ".github/workflows/Build_OpenWrt_Firmware.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("ROOTFS_PARTSIZE_MB: ${{ vars.ROOTFS_PARTSIZE_MB || '100' }}", workflow)
        self.assertIn("MIN_FIRMWARE_SIZE_MB: ${{ vars.MIN_FIRMWARE_SIZE_MB || '8' }}", workflow)
        self.assertIn("MAX_FIRMWARE_SIZE_MB: ${{ vars.MAX_FIRMWARE_SIZE_MB || '96' }}", workflow)
        self.assertIn("RELEASE_KEEP_COUNT: ${{ vars.RELEASE_KEEP_COUNT || '3' }}", workflow)
        self.assertIn("ENABLE_XRAY: ${{ vars.ENABLE_XRAY || '0' }}", workflow)
        self.assertIn("AUTOPDATE_UPDATE_BASE_URL: ${{ vars.AUTOPDATE_UPDATE_BASE_URL }}", workflow)
        self.assertIn("AUTOPDATE_CHECK_INTERVAL: ${{ vars.AUTOPDATE_CHECK_INTERVAL || 'daily' }}", workflow)
        self.assertIn("AUTOPDATE_RELEASE_TAG_PREFIX: OpenWRT.org_Kernel_", workflow)
        self.assertIn("make defconfig 后 CONFIG_TARGET_ROOTFS_PARTSIZE=", workflow)
        self.assertIn("重新写入 $ROOTFS_PARTSIZE_MB", workflow)
        self.assertIn('CONFIG_TARGET_BOARD', workflow)
        self.assertIn('target/linux/generic/kernel-$KERNEL_PATCHVER', workflow)
        self.assertIn('LINUX_VERSION-$KERNEL_PATCHVER', workflow)
        self.assertIn("linux-([0-9]+([.][0-9]+)+)", workflow)
        self.assertIn("内核版本格式无效", workflow)
        self.assertNotIn("OpenWRT.org__Kernel", workflow)
        self.assertNotIn("OpenWrt.org__Kernel", workflow)
        self.assertNotIn("find build_dir -maxdepth 4 -type d -name 'linux-*'", workflow)

    def test_readme_documents_numeric_sources_and_repo_variable_overrides(self):
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

        for text in [
            "192.168.88.1`；由 `custom_scripts/diy-part2.sh` 写入，工作流不读取 Repository Variables 覆盖",
            "100 MiB；由 `ROOTFS_PARTSIZE_MB` 控制，工作流读取 Repository Variables 覆盖",
            "8 MiB、上限 96 MiB；由 `MIN_FIRMWARE_SIZE_MB`/`MAX_FIRMWARE_SIZE_MB` 控制，工作流读取 Repository Variables 覆盖",
            "最近 3 个 Release；由 `RELEASE_KEEP_COUNT` 控制，工作流读取 Repository Variables 覆盖",
            "每小时第 `17` 分钟唤醒；实际间隔由 `AUTOPDATE_CHECK_INTERVAL` 控制，工作流读取 Repository Variables 覆盖",
        ]:
            self.assertIn(text, readme)

    def test_active_actions_are_pinned(self):
        workflows = REPOSITORY_ROOT / ".github" / "workflows"
        for workflow in workflows.glob("*.yml"):
            for line in workflow.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped.startswith("uses:"):
                    continue
                action = stripped.split("uses:", 1)[1].strip()
                self.assertRegex(
                    action,
                    r"^[^@\s]+@[0-9a-f]{40}$",
                    f"{workflow.name} contains a floating action: {action}",
                )

    def test_review_fails_closed_without_two_families(self):
        key_names = [
            "QIANFAN_CODING_API_KEY",
            "VOLCANO_CODINGPLAN_API_KEY",
            "ALIYUN_TOKENPLAN_API_KEY",
            "MIMO_TOKENPLAN_API_KEY",
            "ZHIPU_API_KEY",
            "DEEPSEEK_API_KEY",
        ]
        with mock.patch.dict(os.environ, {name: "" for name in key_names}, clear=False):
            with redirect_stdout(io.StringIO()):
                passed, results = multi_agent_review.run_review("diff --git a/a b/a")

        self.assertFalse(passed)
        self.assertEqual(results, [])

    def test_review_selection_excludes_fixer_and_duplicate_families(self):
        models = [
            {"name": "ZHIPU-GLM", "model": "glm-5.1"},
            {"name": "QIANFAN-GLM", "model": "glm-5"},
            {"name": "DEEPSEEK", "model": "deepseek-v4-pro"},
            {"name": "MIMO", "model": "mimo-v2.5-pro"},
        ]
        with mock.patch.dict(os.environ, {"FIXER_MODEL": "deepseek/v4-pro"}):
            with redirect_stdout(io.StringIO()):
                selected = multi_agent_review.select_review_models(models, 2)

        self.assertEqual([model["name"] for model in selected], ["ZHIPU-GLM", "MIMO"])

    def test_review_endpoint_preserves_coding_plan_path(self):
        source = inspect.getsource(multi_agent_review.call_review_model)
        self.assertIn(r"/v\d+(?:/[^/]+)*/?$", source)


if __name__ == "__main__":
    unittest.main()
