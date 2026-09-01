# Explicitly load the pytest-homeassistant-custom-component plugin so all of
# its fixtures (hass, MockConfigEntry, etc.) are available in every test file.
# Requires Python 3.12 — see requirements_test.txt.
try:
    import pytest_homeassistant_custom_component  # noqa: F401

    pytest_plugins = ["pytest_homeassistant_custom_component"]
except ImportError:
    pass
