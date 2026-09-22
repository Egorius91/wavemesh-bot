"""Cheap CI-source guards, collected by the existing quality test discovery."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ('python-check', 'quality', 'payment-return-check', 'access-shadow-check')


class CICachePolicyTests(unittest.TestCase):
    def test_only_pip_download_cache_is_requested(self):
        for name in WORKFLOWS:
            with self.subTest(workflow=name):
                text = (ROOT / f'.github/workflows/{name}.yml').read_text()
                self.assertIn("python-version: '3.12'\n          cache: pip\n          cache-dependency-path: requirements.txt", text)
                self.assertNotIn('actions/cache@', text)
                self.assertNotIn('cache-hit', text)
                self.assertNotIn('continue-on-error', text)
                self.assertIn('-r requirements.txt', text)

    def test_pr_cancellation_is_workflow_and_event_scoped(self):
        groups = set()
        for name in WORKFLOWS:
            text = (ROOT / f'.github/workflows/{name}.yml').read_text()
            group = 'group: bot-' + name + '-${{ github.event_name }}-${{ github.event.pull_request.number || github.ref }}'
            self.assertIn(group, text)
            self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", text)
            groups.add(group)
        self.assertEqual(len(groups), len(WORKFLOWS))

    def test_quality_audit_and_isolated_payment_mode_remain(self):
        quality = (ROOT / '.github/workflows/quality.yml').read_text()
        payment = (ROOT / '.github/workflows/payment-return-check.yml').read_text()
        self.assertIn('python -m unittest discover -s tests -v', quality)
        self.assertIn('pip-audit -r requirements.txt', quality)
        self.assertIn('ruff check bot database tests main.py --select E9,F63,F7,F82', quality)
        self.assertEqual(payment.count("WAVEMESH_SAAS_CLIENT_MODE: 'true'"), 3)
        self.assertIn('python tests/test_internal_api_payment_return.py', payment)
        self.assertIn('python tests/test_payment_return_handler.py', payment)


if __name__ == '__main__':
    unittest.main()
