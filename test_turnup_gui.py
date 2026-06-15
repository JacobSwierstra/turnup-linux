import unittest
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from turnup_gui import (
    actionable_controller_events,
    build_autostart_entry,
    build_light_message,
    check_for_release_update,
    color_to_rgb,
    discover_app_targets,
    discover_desktop_apps,
    discover_audio_streams,
    get_new_stream_volume_updates,
    get_stream_ids,
    normalize_color,
    normalize_button_action,
    package_update_asset,
    parse_packets,
    rgb_to_hex,
    is_autostart_enabled,
    load_config,
    set_autostart_enabled,
    set_channel_leds,
    set_media_play_pause,
    set_muted,
    TurnUpApp,
)


class GetStreamIdsTests(unittest.TestCase):
    def test_resolves_ids_prefixed_by_wpctl_tree_characters(self):
        status = """Audio
 ├─ Streams:
 │  * 52. Firefox                         [vol: 0.50]
 │    67. Spotify                         [vol: 0.75]
 ├─ Video
"""

        resolved = get_stream_ids({"Firefox", "Spotify"}, status)

        self.assertEqual(resolved["Firefox"], ["52"])
        self.assertEqual(resolved["Spotify"], ["67"])

    def test_matches_spotify_aliases(self):
        status = """Audio
 ├─ Streams:
 │    91. librespot                        [vol: 0.75]
 ├─ Video
"""

        resolved = get_stream_ids({"Spotify"}, status)

        self.assertEqual(resolved["Spotify"], ["91"])

    def test_keeps_direct_audio_targets(self):
        resolved = get_stream_ids({"Master Volume", "Line In / Capture"}, "")

        self.assertEqual(resolved["Master Volume"], ["@DEFAULT_AUDIO_SINK@"])
        self.assertEqual(resolved["Line In / Capture"], ["70"])

    def test_parses_knob_packets(self):
        packet = bytes((0xFF, 0xFE, 0x03, 0x02, 0x00, 0x66))

        events, remainder = parse_packets(packet)

        self.assertEqual(events, [("knob", 2, 102)])
        self.assertEqual(remainder, b"")

    def test_startup_sync_ignores_buffered_button_packets(self):
        events = [("button", 2, None), ("knob", 2, 512)]

        self.assertEqual(
            actionable_controller_events(events, syncing=True),
            [("knob", 2, 512)],
        )
        self.assertEqual(actionable_controller_events(events, syncing=False), events)

    def test_discovers_current_audio_streams(self):
        status = """Audio
 ├─ Streams:
 │    42. A Game                         [vol: 0.50]
 ├─ Video
"""

        self.assertEqual(discover_audio_streams(status), {"A Game": ("A Game",)})

    def test_combines_builtin_installed_and_running_apps(self):
        status = """Audio
 ├─ Streams:
 │    42. Custom Player                  [vol: 0.50]
 ├─ Video
"""

        targets = discover_app_targets(status=status, directories=[])

        self.assertIn("Master Volume", targets)
        self.assertEqual(targets["Custom Player"], ("Custom Player",))

    def test_new_stream_uses_current_controller_position_once(self):
        config = {"channel_0": ["Firefox"]}
        status = """Audio
 ├─ Streams:
 │    52. Firefox                         [vol: 0.50]
 ├─ Video
"""

        current, updates = get_new_stream_volume_updates(
            config, {"channel_0": 73}, {"Firefox": set()}, status
        )
        _, repeated_updates = get_new_stream_volume_updates(
            config, {"channel_0": 73}, current, status
        )

        self.assertEqual(current, {"Firefox": {"52"}})
        self.assertEqual(updates, [("52", 73)])
        self.assertEqual(repeated_updates, [])

    def test_reappearing_stream_is_treated_as_new(self):
        config = {"channel_1": ["Firefox"]}

        absent, _ = get_new_stream_volume_updates(
            config, {"channel_1": 41}, {"Firefox": {"52"}}, ""
        )
        _, updates = get_new_stream_volume_updates(
            config,
            {"channel_1": 41},
            absent,
            "Audio\n ├─ Streams:\n │    52. Firefox [vol: 0.50]\n ├─ Video\n",
        )

        self.assertEqual(updates, [("52", 41)])


class DesktopDiscoveryTests(unittest.TestCase):
    def test_keeps_audio_apps_and_filters_system_apps(self):
        with TemporaryDirectory() as directory:
            app_dir = Path(directory)
            (app_dir / "browser.desktop").write_text(
                """[Desktop Entry]
Type=Application
Name=Example Browser
Exec=example-browser %U
Categories=Network;WebBrowser;
""",
                encoding="utf-8",
            )
            (app_dir / "settings.desktop").write_text(
                """[Desktop Entry]
Type=Application
Name=System Settings
Exec=system-settings
Categories=Settings;System;
""",
                encoding="utf-8",
            )
            (app_dir / "mixer.desktop").write_text(
                """[Desktop Entry]
Type=Application
Name=Audio Mixer
Exec=audio-mixer
Categories=AudioVideo;Utility;
""",
                encoding="utf-8",
            )

            discovered = discover_desktop_apps([app_dir])

        self.assertIn("Example Browser", discovered)
        self.assertNotIn("System Settings", discovered)
        self.assertNotIn("Audio Mixer", discovered)


class ConfigTests(unittest.TestCase):
    def test_keeps_saved_dynamic_app_mappings(self):
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "turnup_config.json"
            config_path.write_text(
                '{"channel_0": ["A Newly Discovered Game"], '
                '"_program_names": {"A Newly Discovered Game": "My Game"}}',
                encoding="utf-8",
            )
            with patch("turnup_gui.CONFIG_FILE", config_path):
                config = load_config()

        self.assertEqual(config["channel_0"], ["A Newly Discovered Game"])
        self.assertEqual(config["_program_names"]["A Newly Discovered Game"], "My Game")

    def test_restores_last_controller_positions(self):
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "turnup_config.json"
            config_path.write_text(
                '{"_controller_positions": {"channel_3": 37, "invalid": 80}}',
                encoding="utf-8",
            )
            with patch("turnup_gui.CONFIG_FILE", config_path):
                config = load_config()

        self.assertEqual(config["_controller_positions"], {"channel_3": 37})

class MuteControlTests(unittest.TestCase):
    @patch("turnup_gui.subprocess.run")
    def test_unmute_sends_zero_to_wpctl(self, run):
        run.return_value = Mock(returncode=0, stderr="")

        success, error = set_muted("52", False)

        self.assertTrue(success)
        self.assertEqual(error, "")
        run.assert_called_once_with(
            ["wpctl", "set-mute", "52", "0"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

    @patch("turnup_gui.subprocess.run")
    def test_pactl_stream_can_be_muted_and_unmuted(self, run):
        run.return_value = Mock(returncode=0, stderr="")

        self.assertEqual(set_muted("pactl:17", True), (True, ""))
        self.assertEqual(set_muted("pactl:17", False), (True, ""))

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["pactl", "set-sink-input-mute", "17", "1"],
                ["pactl", "set-sink-input-mute", "17", "0"],
            ],
        )

    @patch("turnup_gui.subprocess.run")
    def test_play_pause_targets_most_recent_player_via_playerctld(self, run):
        run.side_effect = [
            Mock(returncode=0, stderr=""),
            Mock(returncode=0, stderr=""),
        ]

        success, error = set_media_play_pause()

        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["playerctld", "daemon"],
                ["playerctl", "--player=playerctld", "play-pause"],
            ],
        )

    @patch("turnup_gui.subprocess.run")
    def test_play_pause_reports_playerctld_start_failure(self, run):
        run.return_value = Mock(returncode=1, stderr="D-Bus unavailable")

        success, error = set_media_play_pause()

        self.assertFalse(success)
        self.assertEqual(error, "D-Bus unavailable")
        run.assert_called_once()

    def test_unmuted_channel_led_is_on(self):
        controller = Mock()

        set_channel_leds(
            controller,
            [(0, 0, 0), (0, 0, 0), (18, 52, 86), (0, 0, 0), (0, 0, 0)],
        )

        expected = bytearray(48)
        expected[0:2] = bytes((0xFE, 0x05))
        expected[20:29] = bytes((18, 52, 86)) * 3
        expected[-1] = 0xFF
        controller.write.assert_called_once_with(bytes(expected))
        controller.flush.assert_called_once_with()

    def test_muted_channel_led_is_off(self):
        message = build_light_message(
            [(255, 0, 0), (0, 255, 0), (0, 0, 0), (0, 0, 255), (255, 255, 255)]
        )

        self.assertEqual(message[20:29], bytes(9))
        self.assertEqual(message[0:2], bytes((0xFE, 0x05)))
        self.assertEqual(message[-1], 0xFF)

    def test_color_helpers_validate_and_convert_hex(self):
        self.assertEqual(normalize_color("#12abEF"), "#12ABEF")
        self.assertEqual(normalize_color("invalid"), "#FFFFFF")
        self.assertEqual(color_to_rgb("#123456"), (18, 52, 86))
        self.assertEqual(rgb_to_hex(18, 52, 86), "#123456")
        self.assertEqual(normalize_button_action("none"), "none")
        self.assertEqual(normalize_button_action("mute"), "mute")
        self.assertEqual(normalize_button_action("pause"), "play_pause")
        self.assertEqual(normalize_button_action("play_pause"), "play_pause")
        self.assertEqual(normalize_button_action("unknown"), "mute")

    @patch("turnup_gui.set_channel_leds")
    def test_two_mute_presses_mute_then_unmute(self, set_leds):
        app = TurnUpApp.__new__(TurnUpApp)
        app.config_lock = threading.Lock()
        app.config = {"_button_actions": {"channel_0": "mute"}}
        app.last_button_press = {}
        app.channel_muted = {"channel_0": False}
        app.apply_mute_update = Mock(return_value=(True, ""))
        app.led_colors_snapshot = Mock(return_value=[])
        app.update_controller_preview = Mock()
        app.set_status = Mock()
        app.root = Mock()
        controller = Mock()

        app.handle_button_press("channel_0", 0, controller, now=1.0)
        app.handle_button_press("channel_0", 0, controller, now=2.0)

        self.assertEqual(
            app.apply_mute_update.call_args_list,
            [
                unittest.mock.call("channel_0", True),
                unittest.mock.call("channel_0", False),
            ],
        )
        self.assertFalse(app.channel_muted["channel_0"])
        self.assertEqual(set_leds.call_count, 2)

    @patch("turnup_gui.set_media_play_pause", return_value=(True, ""))
    def test_play_pause_press_never_runs_mute(self, play_pause):
        app = TurnUpApp.__new__(TurnUpApp)
        app.config_lock = threading.Lock()
        app.config = {"_button_actions": {"channel_3": "play_pause"}}
        app.last_button_press = {}
        app.channel_muted = {"channel_3": False}
        app.apply_mute_update = Mock()
        app.set_status = Mock()

        app.handle_button_press("channel_3", 3, Mock(), now=1.0)

        play_pause.assert_called_once_with()
        app.apply_mute_update.assert_not_called()
        self.assertFalse(app.channel_muted["channel_3"])

    @patch("turnup_gui.set_media_play_pause", return_value=(True, ""))
    def test_duplicate_play_pause_packet_is_debounced(self, play_pause):
        app = TurnUpApp.__new__(TurnUpApp)
        app.config_lock = threading.Lock()
        app.config = {"_button_actions": {"channel_3": "play_pause"}}
        app.last_button_press = {}
        app.channel_muted = {"channel_3": False}
        app.set_status = Mock()

        app.handle_button_press("channel_3", 3, Mock(), now=1.0)
        app.handle_button_press("channel_3", 3, Mock(), now=1.1)

        play_pause.assert_called_once_with()


class AutostartTests(unittest.TestCase):
    def test_autostart_entry_quotes_python_and_script_paths(self):
        entry = build_autostart_entry("/opt/Python 3/python", "/home/user/Turn Up/app.py")

        self.assertIn(
            'Exec="/opt/Python 3/python" "/home/user/Turn Up/app.py" --minimized',
            entry,
        )
        self.assertIn("Terminal=false", entry)

    def test_autostart_can_be_enabled_and_disabled(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "autostart" / "turnup-linux.desktop"

            set_autostart_enabled(True, path)
            self.assertTrue(is_autostart_enabled(path))
            self.assertIn("Name=Turn Up", path.read_text(encoding="utf-8"))

            set_autostart_enabled(False, path)
            self.assertFalse(is_autostart_enabled(path))


class UpdateTests(unittest.TestCase):
    @patch("turnup_gui.fetch_latest_release")
    def test_current_release_does_not_offer_an_update(self, fetch_release):
        fetch_release.return_value = ({"tag": "v1.0.0", "url": ""}, "")

        result = check_for_release_update("1.0.0")

        self.assertEqual(result["status"], "current")

    @patch("turnup_gui.fetch_latest_release")
    def test_different_release_tag_offers_an_update(self, fetch_release):
        fetch_release.return_value = ({"tag": "v1.1.0", "url": ""}, "")

        result = check_for_release_update("1.0.0")

        self.assertEqual(result["status"], "update_available")
        self.assertEqual(result["release"]["tag"], "v1.1.0")

    @patch("turnup_gui.shutil.which")
    def test_fedora_update_ignores_source_rpm(self, which):
        which.side_effect = lambda command: "/usr/bin/dnf" if command == "dnf" else None
        release = {
            "assets": [
                {"name": "turnup-1.1.0.src.rpm", "url": "source"},
                {"name": "turnup-1.1.0.noarch.rpm", "url": "binary"},
            ]
        }

        asset, command_builder = package_update_asset(release)

        self.assertEqual(asset["url"], "binary")
        self.assertEqual(
            command_builder("/tmp/turnup.rpm"),
            ["pkexec", "dnf", "install", "-y", "/tmp/turnup.rpm"],
        )


class TrayTests(unittest.TestCase):
    def test_close_hides_window_when_tray_is_available(self):
        app = TurnUpApp.__new__(TurnUpApp)
        app._ensure_tray_icon = Mock(return_value=True)
        app.save_config = Mock()
        app.root = Mock()
        app.status_var = Mock()
        app.exit_app = Mock()

        app.close()

        app.root.withdraw.assert_called_once_with()
        app.exit_app.assert_not_called()


if __name__ == "__main__":
    unittest.main()
