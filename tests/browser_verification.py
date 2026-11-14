"""节能核验页面的真实浏览器交互回归。"""
from pathlib import Path
import importlib
import json
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class BrowserVerification(unittest.TestCase):
    def setUp(self):
        package = json.loads((ROOT / "package.json").read_text())
        module = package["scripts"]["start"].split()[2]
        self.server_module = importlib.import_module(module + ".server")

    def _open(self, page, server):
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:" + str(server.server_port), wait_until="networkidle")
        page.locator("#status").filter(has_text="已更新描述").wait_for()
        page.locator(".tab[data-view='verify']").click()
        page.locator("#view-verify").wait_for(state="visible")
        return errors

    def test_verification_verdict_drilldown_and_blocking(self):
        with tempfile.TemporaryDirectory() as state:
            server = self.server_module.make_server(ROOT, state, port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with sync_playwright() as runtime:
                    browser = runtime.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        errors = self._open(page, server)
                        page.locator("#verify-run").click()
                        page.locator(".verdict.blocked").wait_for()
                        self.assertIn("停止给出整体节能率", page.locator(".verdict").inner_text())
                        # 阻断依据包含未估计调整与外推。
                        blockers = page.locator("#verify-blockers").inner_text()
                        self.assertIn("impact_kwh=null", blockers)
                        self.assertIn("外推", blockers)
                        # 合计卡不给出率值，但保留节省量与区间。
                        totals = page.locator("#verify-totals").inner_text()
                        self.assertIn("不给出", totals)
                        self.assertIn("95%", totals)
                        # 表段钻取：展开总表，看到逐日反事实与计量依据。
                        page.locator("#verify-meters details").first.click()
                        page.locator("#verify-meters details table").first.wait_for()
                        meter_text = page.locator("#verify-meters details").first.inner_text()
                        self.assertIn("留时段验证 CV", meter_text)
                        self.assertIn("AR(1)", meter_text)
                        self.assertIn("reset_excluded", meter_text)
                        self.assertIn("missing_excluded", meter_text)
                        # 调整台账包含托育与停楼，批准控件存在。
                        ledger = page.locator("#verify-adjustments").inner_text()
                        self.assertIn("A-nursery", ledger)
                        self.assertIn("A-closure", ledger)
                        self.assertEqual(page.locator(".approval-toggle").count(), 2)
                        # 留痕 JSON 含完整结构化结果。
                        self.assertIn('"comparable": false', page.locator("#verify-json").inner_text())
                        self.assertEqual(errors, [])
                        # 过窄基准期使模型失败：页面仍渲染表段与原因，合计显示不可计算而非零。
                        page.locator("#base-start").fill("230")
                        page.locator("#base-stop").fill("239")
                        with page.expect_response(lambda r: "/api/verify" in r.url) as response_info:
                            page.locator("#verify-run").click()
                        response_info.value
                        self.assertIn("低于建模下限", page.locator("#verify-meters").inner_text())
                        self.assertIn("不可计算", page.locator("#verify-totals").inner_text())
                        self.assertEqual(page.locator("#verify-meters details").count(), 2)
                        self.assertEqual([e for e in errors if "pageerror" in e or "Error" in e], [])
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                worker.join()
                server.server_close()

    def test_scenario_compare_and_archive(self):
        with tempfile.TemporaryDirectory() as state:
            server = self.server_module.make_server(ROOT, state, port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with sync_playwright() as runtime:
                    browser = runtime.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        errors = self._open(page, server)
                        # 情景一：默认假设。
                        page.locator("#verify-run").click()
                        page.locator(".verdict").wait_for()
                        # 情景二：批准托育新服务。
                        page.locator(".approval-toggle").nth(1).check()
                        page.locator("#scenario-label").fill("含托育情景")
                        page.locator("#verify-run").click()
                        page.locator("#status").filter(has_text="含托育情景").wait_for()
                        page.locator("#compare-toggle").click()
                        page.locator("#compare-panel").wait_for(state="visible")
                        compare = page.locator("#compare-grid").inner_text()
                        self.assertIn("整体节能率", compare)
                        self.assertIn("批准覆盖", compare)
                        # 保存核验存档并重开。
                        page.locator("#verify-title").fill("浏览器核验存档")
                        page.locator("#verify-save").click()
                        page.locator("#status").filter(has_text="已保存核验情景").wait_for()
                        page.locator("#verify-archive button").first.click()
                        page.locator("#verify-assumptions").wait_for()
                        self.assertIn("含托育情景", page.locator("#verify-assumptions").inner_text())
                        self.assertEqual(errors, [])
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                worker.join()
                server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
