import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from turnup_gui import (
    build_autostart_entry,
    build_light_message,
    color_to_rgb,
    discover_app_targets,
    discover_desktop_apps,
    discover_audio_streams,
    get_stream_ids,
    normalize_color,
    normalize_button_action,
    parse_packets,
    rgb_to_hex,
    is_autostart_enabled,
    load_config,
    set_autostart_enabled,
    set_channel_leds,
    set_media_play_pause,
    set_muted,
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
    def test_play_pause_media_sends_play_pause_to_playerctl(self, run):
        run.return_value = Mock(returncode=0, stderr="")

        success, error = set_media_play_pause()

        self.assertTrue(success)
        self.assertEqual(error, "")
        run.assert_called_once_with(
            ["playerctl", "play-pause"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

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


if __name__ == "__main__":
    unittest.main()
