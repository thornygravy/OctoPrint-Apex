import logging
import os
from unittest import mock

import pytest

import octoprint.plugins.softwareupdate
from octoprint.plugins.softwareupdate import SoftwareUpdatePlugin

BASEFOLDER = os.path.dirname(octoprint.plugins.softwareupdate.__file__)

# What upstream's overlay at plugins.octoprint.org does to the core check: it fixes up the
# repository owner. For the Apex check that would mean looking for releases of
# OctoPrint/OctoPrint-Apex, which doesn't exist.
OVERLAY = {
    "octoprint": {"user": "OctoPrint", "repo": "OctoPrint"},
    "file_check": {"pip": "https://example.com/file_check.zip"},
}


@pytest.fixture()
def plugin():
    plugin = SoftwareUpdatePlugin()
    plugin._basefolder = BASEFOLDER
    plugin._logger = logging.getLogger("octoprint.plugins.softwareupdate")
    plugin._connectivity_checker = mock.MagicMock(online=True)
    plugin._settings = mock.MagicMock()
    plugin._settings.get.return_value = "https://example.com/overlay.json"
    return plugin


def _applied_overlay(plugin):
    (args, kwargs), *_ = plugin._settings.add_overlay.call_args_list
    return args[0]["checks"]


def test_core_check_points_at_the_fork(plugin):
    check = plugin.get_settings_defaults()["checks"]["octoprint"]

    assert (check["user"], check["repo"]) == ("thornygravy", "OctoPrint-Apex")
    assert "thornygravy/OctoPrint-Apex" in check["pip"]


def test_overlay_does_not_touch_core_check(plugin):
    with mock.patch.object(plugin, "_get_check_overlay", return_value=dict(OVERLAY)):
        overlays = plugin._get_check_overlays()

    assert "octoprint" not in overlays


def test_overlay_is_not_applied_to_core_check_settings(plugin):
    defaults = plugin.get_settings_defaults()
    defaults["checks"]["file_check"] = {}  # something for the other overlay to apply to

    with (
        mock.patch.object(plugin, "_get_check_overlay", return_value=dict(OVERLAY)),
        mock.patch.object(plugin, "get_settings_defaults", return_value=defaults),
    ):
        plugin._get_check_overlays()

    assert _applied_overlay(plugin) == {"file_check": OVERLAY["file_check"]}


def test_other_overlays_are_kept(plugin):
    with mock.patch.object(plugin, "_get_check_overlay", return_value=dict(OVERLAY)):
        overlays = plugin._get_check_overlays()

    assert overlays == {"file_check": OVERLAY["file_check"]}


@pytest.mark.parametrize("broken", [{}, [], None])
def test_broken_overlay_is_survivable(plugin, broken):
    with mock.patch.object(plugin, "_get_check_overlay", return_value=broken):
        assert plugin._get_check_overlays() == {}
