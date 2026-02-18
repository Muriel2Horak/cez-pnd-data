from addon.src.cookie_utils import playwright_cookies_to_header


def test_single_cookie_conversion():
    """Test single cookie conversion"""
    cookies = [{"name": "JSESSIONID", "value": "abc123"}]
    result = playwright_cookies_to_header(cookies)
    assert result == "JSESSIONID=abc123"


def test_multiple_cookies():
    """Test multiple cookies conversion"""
    cookies = [{"name": "A", "value": "1"}, {"name": "B", "value": "2"}]
    result = playwright_cookies_to_header(cookies)
    assert result == "A=1; B=2"


def test_empty_list():
    """Test empty list returns empty string"""
    cookies = []
    result = playwright_cookies_to_header(cookies)
    assert result == ""


def test_cookie_with_extra_fields():
    """Test that only name and value are used, ignoring extra fields"""
    cookies = [
        {
            "name": "SESSION",
            "value": "xyz789",
            "expires": 1704067200,
            "domain": "example.com",
            "path": "/",
        }
    ]
    result = playwright_cookies_to_header(cookies)
    assert result == "SESSION=xyz789"


def test_special_characters_in_values():
    """Test special characters in values are handled correctly"""
    cookies = [
        {"name": "test", "value": "value with spaces"},
        {"name": "unicode", "value": "nějaký český text"},
    ]
    result = playwright_cookies_to_header(cookies)
    assert result == "test=value with spaces; unicode=nějaký český text"


def test_order_preservation():
    """Test that cookies maintain original order"""
    cookies = [
        {"name": "first", "value": "1"},
        {"name": "second", "value": "2"},
        {"name": "third", "value": "3"},
    ]
    result = playwright_cookies_to_header(cookies)
    assert result == "first=1; second=2; third=3"
