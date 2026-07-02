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

    def test_autoupdate_requires_target_sysupgrade_and_validation(self):
        script = (
            REPOSITORY_ROOT
            / "package/luci-app-autoupdate/root/usr/bin/autoupdate.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('*"$DEVICE_PATTERN"*sysupgrade*.bin)', script)
        self.assertGreaterEqual(script.count('sysupgrade -T "$FIRMWARE_FILE"'), 1)
        self.assertIn('sysupgrade -T "$output"', script)
        self.assertIn('release_tag_prefix "OpenWRT.org_"', script)
        self.assertNotIn("*sysupgrade*.bin|*factory*.bin|*kernel*.bin", script)

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
