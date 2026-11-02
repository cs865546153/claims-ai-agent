"""Offline checks: no model credentials or provider requests required."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import yaml

import demo


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for folder in ("configs", "data", "skills"):
            shutil.copytree(demo.ROOT / folder, self.root / folder)
        self.local = self.root / "configs/test.local.yaml"
        for name, value in (
            ("ROOT", self.root),
            ("TEMPLATE", self.root / "configs/product_qa.yaml"),
            ("LOCAL_CONFIG", self.local),
        ):
            patcher = patch.object(demo, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        before = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, before)

    def test_checked_in_data_loads_without_model_calls(self):
        with patch("skillopt.model.chat_target", side_effect=AssertionError("network forbidden")), \
             patch("skillopt.model.chat_optimizer", side_effect=AssertionError("network forbidden")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            demo.check()
        self.assertIn("没有调用模型", output.getvalue())

    def test_duplicate_ids_across_splits_are_rejected(self):
        import json
        path = self.root / "data/product_qa/val/items.json"
        rows = demo.read_json(path)
        rows[0]["id"] = "train_a_01"
        path.write_text(json.dumps(rows), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "重复"):
            demo.check()

    def test_configure_does_not_save_key_or_overwrite_edits(self):
        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_MODEL": "offline-model", "OPENAI_COMPATIBLE_API_KEY": "test-secret"}), \
             contextlib.redirect_stdout(io.StringIO()):
            demo.configure()
            demo.configure()  # Same settings are safe to run twice.
            text = self.local.read_text(encoding="utf-8")
            self.assertNotIn("test-secret", text)
            self.assertEqual(yaml.safe_load(text)["model"]["target"], "offline-model")
            self.assertEqual(demo.config()["target_model"], "offline-model")
            self.local.write_text(text + "# manual adjustment\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "--replace"):
                demo.configure()
            self.assertIn("manual adjustment", self.local.read_text(encoding="utf-8"))
            demo.configure(replace=True)
            self.assertNotIn("manual adjustment", self.local.read_text(encoding="utf-8"))

    def test_configure_uses_role_specific_models_when_set(self):
        env = {
            "OPENAI_COMPATIBLE_MODEL": "shared-fallback",
            "TARGET_OPENAI_COMPATIBLE_MODEL": "target-model",
            "OPTIMIZER_OPENAI_COMPATIBLE_MODEL": "optimizer-model",
        }
        with patch.dict(os.environ, env), \
             contextlib.redirect_stdout(io.StringIO()):
            demo.configure()
            text = self.local.read_text(encoding="utf-8")
            cfg = yaml.safe_load(text)
            self.assertEqual(cfg["model"]["target"], "target-model")
            self.assertEqual(cfg["model"]["optimizer"], "optimizer-model")
            self.assertEqual(demo.config()["target_model"], "target-model")
            self.assertEqual(demo.config()["optimizer_model"], "optimizer-model")

    def test_configure_falls_back_to_generic_model(self):
        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_MODEL": "shared-model"}, clear=False), \
             contextlib.redirect_stdout(io.StringIO()):
            demo.configure()
            text = self.local.read_text(encoding="utf-8")
            cfg = yaml.safe_load(text)
            self.assertEqual(cfg["model"]["target"], "shared-model")
            self.assertEqual(cfg["model"]["optimizer"], "shared-model")

    def test_unconfigured_model_fails_before_provider_call(self):
        with self.assertRaisesRegex(ValueError, "configure"):
            demo.target()

    def test_missing_run_is_reported(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "DEMO_RUN"):
            demo.run_path(None)


if __name__ == "__main__":
    unittest.main()
