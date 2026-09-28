from backend.services.merchant_normalizer import normalize_merchant, strip_descriptor_noise


def test_strips_reference_ids_prefixes_and_store_numbers():
    assert strip_descriptor_noise("DUKEENERGY PAYMENT PPD ID: 4760039224") == "DUKEENERGY PAYMENT"
    assert strip_descriptor_noise("TST* JOES CAFE 0686") == "JOES CAFE"
    assert strip_descriptor_noise("  CITY TRASH 8812 ") == "CITY TRASH"


def test_keeps_raw_wording_instead_of_display_mapping():
    # The display name "Amazon" is not a substring of the raw text, so a rule
    # built from it would never match the next charge.
    assert strip_descriptor_noise("AMZN MKTP US*BJ1O92ZW1") == "AMZN MKTP US"
    assert strip_descriptor_noise("Netflix") == "Netflix"


def test_empty_input_is_empty():
    assert strip_descriptor_noise(None) == ""
    assert strip_descriptor_noise("   ") == ""


def test_normalize_merchant_behavior_unchanged():
    cases = {
        None: "Unknown",
        "": "Unknown",
        "AMZN MKTP US*BJ1O92ZW1": "Amazon",
        "DUKEENERGY PAYMENT PPD ID: 4760039224": "Duke Energy",
        "MICHAELS STORES 9951": "Michaels Stores",
        "TST* JOES CAFE 0686": "Joes Cafe",
        "mercyroad.cc": "mercyroad.cc",
        "AB 123456": "AB 123456",
        "SQ *CORNER BAKERY 12/03": "Corner Bakery",
    }
    for raw, want in cases.items():
        assert normalize_merchant(raw) == want, raw
