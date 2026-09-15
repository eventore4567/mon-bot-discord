from web import dashboard_product_v19


def test_v19_config_detection_is_value_aware():
    settings = {
        "verification_role": 123,
        "verification_channel": 456,
        "logs_channel": 0,
    }
    assert dashboard_product_v19._truthy_config(settings, "verification", "role")
    assert dashboard_product_v19._truthy_config(settings, "verification", "channel")
    assert not dashboard_product_v19._truthy_config(settings, "logs", "channel")


def test_v19_bulk_limit_and_build_contract_are_stable():
    assert dashboard_product_v19.MAX_BULK_TARGETS == 25
    assert dashboard_product_v19.BUILD == "v19-final-polish"
