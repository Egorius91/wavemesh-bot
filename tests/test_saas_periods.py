from unittest import TestCase

from bot.handlers.user.saas_periods import scheduled_periods_text, utc_date


def period(**overrides):
    return {"subscription_id":"sub-1", "starts_at":"2026-10-20T03:00:00+03:00",
            "expires_at":"2026-11-20T00:00:00Z", "tariff_name":"Monthly", **overrides}


class ScheduledPeriodTests(TestCase):
    def test_absent_and_empty_are_backward_compatible(self):
        self.assertEqual(scheduled_periods_text(None),"")
        self.assertEqual(scheduled_periods_text([]),"")

    def test_dates_have_explicit_utc_and_duplicate_ids_are_not_repeated(self):
        text = scheduled_periods_text([period(),period()])
        self.assertIn("20.10.2026 00:00:00",text)
        self.assertIn("UTC",text)
        self.assertEqual(text.count("Monthly"),1)

    def test_invalid_dates_and_types_do_not_claim_paid_periods(self):
        bad = [None,{},period(starts_at="2026-10-20"),period(expires_at="2025-01-01T00:00:00Z"),
               period(starts_at="<script>"),period(subscription_id=[])]
        for item in bad:
            text = scheduled_periods_text([item])
            self.assertIn("не удалось",text)
            self.assertNotIn("Оплачено заранее",text)
            self.assertNotIn("<script>",text)
        for value in (42,False,"bad",{}):
            self.assertIn("не удалось",scheduled_periods_text(value))

    def test_huge_fields_and_collections_are_bounded_and_html_safe(self):
        value = [period(subscription_id=f"sub-{i}",tariff_name="<&>😀"*10000) for i in range(101)]
        text = scheduled_periods_text(value)
        self.assertLess(len(text.encode("utf-16-le"))//2,4096)
        self.assertEqual(text.count("\n•"),3)
        self.assertNotIn("<&>",text)
        self.assertIn("Показаны только первые",text)
        self.assertIn("не удалось отобразить полностью",text)

    def test_valid_period_survives_malformed_sibling_and_missing_tariff(self):
        text = scheduled_periods_text([{},period(tariff_name=None)])
        self.assertIn("• Тариф:",text)
        self.assertIn("20.10.2026",text)
        self.assertIn("не удалось",text)

    def test_datetime_parser_rejects_overflow_and_unbounded_input(self):
        for value in ("0001-01-01T00:00:00+23:00", "9"*100000, {}, None):
            self.assertIsNone(utc_date(value))
