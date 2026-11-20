import logging
import time
from unittest import mock

import pytest

from octoprint.plugins.discovery import DiscoveryPlugin

# how long a (mocked) zeroconf registration blocks, the real thing takes about 0.8s due to
# mDNS name probing
REGISTER_DELAY = 0.5


def _slow_register(*args, **kwargs):
    time.sleep(REGISTER_DELAY)


@pytest.fixture()
def plugin():
    plugin = DiscoveryPlugin()
    plugin._logger = logging.getLogger("octoprint.plugins.discovery.DiscoveryPlugin")
    plugin.port = 5000

    plugin._settings = mock.MagicMock()
    plugin._settings.get.return_value = []

    plugin._zeroconf = mock.MagicMock()
    plugin._zeroconf.register_service.side_effect = _slow_register

    plugin.get_instance_name = mock.MagicMock(return_value="test")
    plugin.get_interface_addresses = mock.MagicMock(return_value=["127.0.0.1"])
    plugin._create_http_txt_record_dict = mock.MagicMock(return_value={"path": "/"})
    plugin._create_octoprint_txt_record_dict = mock.MagicMock(return_value={"path": "/"})
    plugin._ssdp_register = mock.MagicMock()
    plugin._ssdp_unregister = mock.MagicMock()

    yield plugin

    # don't leak the background thread into other tests if one of them failed halfway
    plugin._zeroconf_startup_cancelled.set()
    if plugin._zeroconf_startup_thread is not None:
        plugin._zeroconf_startup_thread.join(timeout=5)


def test_on_startup_does_not_wait_for_registration(plugin):
    start = time.monotonic()
    plugin.on_startup("127.0.0.1", 5000)
    elapsed = time.monotonic() - start

    # two registrations at REGISTER_DELAY each, we must be back long before even the first
    # one has completed
    assert elapsed < REGISTER_DELAY / 2

    plugin._zeroconf_startup_thread.join(timeout=10)
    assert not plugin._zeroconf_startup_thread.is_alive()

    assert plugin._zeroconf.register_service.call_count == 2
    registered_types = {reg_type for reg_type, _ in plugin._zeroconf_registrations.keys()}
    assert registered_types == {"_http._tcp.local.", "_octoprint._tcp.local."}
    plugin._ssdp_register.assert_called_once()


def test_on_startup_registers_custom_services(plugin):
    custom = {
        "service": "_custom._tcp",
        "name": "custom name",
        "port": 1234,
        "txtRecord": {"foo": "bar"},
    }
    plugin._settings.get.side_effect = (
        lambda path: [custom] if path == ["zeroConf"] else None
    )

    plugin.on_startup("127.0.0.1", 5000)
    plugin._zeroconf_startup_thread.join(timeout=10)

    assert plugin._zeroconf.register_service.call_count == 3
    assert ("_custom._tcp.local.", 1234) in plugin._zeroconf_registrations

    info = plugin._zeroconf_registrations[("_custom._tcp.local.", 1234)][0]
    assert info.port == 1234
    assert info.name == "custom name._custom._tcp.local."
    assert info.properties == {b"foo": b"bar"}


def test_on_shutdown_unregisters_registration_in_flight(plugin):
    plugin.on_startup("127.0.0.1", 5000)

    # shutting down right away, while the first registration is still being processed
    plugin.on_shutdown()

    assert not plugin._zeroconf_startup_thread.is_alive()

    # everything that did get registered is unregistered again, nothing is left behind...
    registered = plugin._zeroconf.register_service.call_count
    assert plugin._zeroconf.unregister_service.call_count == registered
    assert not plugin._zeroconf_registrations

    # ... and we didn't carry on registering the remaining services after being cancelled
    assert registered < 2
    plugin._ssdp_unregister.assert_called_once()
