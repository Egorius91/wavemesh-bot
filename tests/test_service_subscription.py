import unittest
from bot.services.service_subscription import renewal_address, service_material, subscription_address

ACCESS = "access-12345678"
URL = "https://service.example.invalid/api/subscriptions/11111111-2222-4333-8444-555555555555/wvs1_" + "A" * 43


def material():
    return {"access_id": ACCESS, "ready": True, "status": "ready", "desired_version": 2,
            "material_version": 2, "kind": "service_subscription", "subscription_url": URL}


class ServiceSubscriptionTests(unittest.TestCase):
    def test_exact_service_material_needs_no_single_entry_credentials(self):
        value = material(); checked = service_material(value, ACCESS)
        self.assertEqual(checked, value); self.assertIsNot(checked, value)
        self.assertEqual(subscription_address(URL), URL)

    def test_wrong_owner_kind_version_and_extra_private_fields_are_refused(self):
        for patch in ({"access_id": "other-access"}, {"ready": False}, {"status": "pending"}, {"desired_version": True},
                      {"desired_version": 0}, {"desired_version": 2147483648}, {"material_version": 2.0},
                      {"material_version": 1}, {"kind": "node_native"}, {"client_uuid": "private_canary"}, {"node_id": "first-entry"}):
            with self.subTest(keys=list(patch)), self.assertRaises(ValueError): service_material(material() | patch, ACCESS)

    def test_service_url_has_strict_purpose_canonical_token_and_no_extra_payload(self):
        for bad in (URL.replace("https:", "http:"), URL.replace("//service", "//u:p@service"), URL + "?extra=1", URL + "#private",
                    URL.replace("/api/subscriptions/", "/native/sub/"), URL.replace("4333", "3333"), URL[:-1] + "B",
                    URL + "=", URL + "\n", URL.replace("service.example.invalid", "service.\texample.invalid"),
                    URL.replace("service.example.invalid", "service.example.invalid:bad"), URL.replace("/wvs1_", "/%77vs1_")):
            with self.subTest(shape=bad.split("/api/")[0]), self.assertRaises(ValueError): subscription_address(bad)

    def test_authenticated_service_origin_is_not_inferred_from_internal_api_hostname(self):
        # APP_URL can differ from the internal API address and use an explicit
        # HTTPS port. The authenticated SaaS owns it; the Bot does no URL fetch.
        alternate = URL.replace("service.example.invalid", "account.example.invalid:8443")
        self.assertEqual(subscription_address(alternate), alternate)

    def test_renewal_link_has_only_the_owned_access_and_existing_pricing_route(self):
        value = "https://service.example.invalid/pricing?accessId=" + ACCESS
        self.assertEqual(renewal_address(value, ACCESS), value)
        for bad in (value.replace(ACCESS, "other-access"), value + "&extra=1", value + "&accessId=" + ACCESS,
                    value.replace("/pricing", "/other"), value.replace("https:", "http:"), value + "#private"):
            with self.assertRaises(ValueError): renewal_address(bad, ACCESS)

    def test_errors_never_echo_sensitive_input(self):
        for value in (None, 123, "https://private_canary@service.example.invalid/private_canary"):
            try: subscription_address(value)
            except ValueError as error: self.assertNotIn("private_canary", str(error))
            else: self.fail("Invalid service value was accepted")


if __name__ == "__main__":
    unittest.main()
