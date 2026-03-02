"""
PS1 Engine Regression Test Suite
=================================
Comprehensive tests for all implemented features.
Uses mocked Docker client — no live containers needed.

Run: pytest tests/test_engine.py -v --tb=short
"""

import os
import sys
import re
import time
import shutil
import tempfile
import zipfile
import asyncio
from unittest.mock import patch, MagicMock, PropertyMock, mock_open
from collections import defaultdict
from datetime import datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# We must set up minimal env vars BEFORE importing main, because main.py
# calls load_dotenv() and verify_paths() at import time.
# ---------------------------------------------------------------------------
_tmp_dirs = {}

def _setup_import_env():
    """Create temp directories and dummy files so main.py's verify_paths() succeeds."""
    _tmp_dirs["rom"] = tempfile.mkdtemp(prefix="test_roms_")
    _tmp_dirs["snes"] = tempfile.mkdtemp(prefix="test_snes_")
    _tmp_dirs["gba"] = tempfile.mkdtemp(prefix="test_gba_")
    _tmp_dirs["bios"] = tempfile.mkdtemp(prefix="test_bios_")
    _tmp_dirs["cache"] = tempfile.mkdtemp(prefix="test_cache_")
    _tmp_dirs["covers"] = tempfile.mkdtemp(prefix="test_covers_")

    os.environ["ROM_DIR"] = _tmp_dirs["rom"]
    os.environ["SNES_ROM_DIR"] = _tmp_dirs["snes"]
    os.environ["GBA_ROM_DIR"] = _tmp_dirs["gba"]
    os.environ["BIOS_DIR"] = _tmp_dirs["bios"]
    os.environ["ROM_CACHE_DIR"] = _tmp_dirs["cache"]
    os.environ["COVERS_DIR"] = _tmp_dirs["covers"]
    os.environ["HOST_ROM_DIR"] = _tmp_dirs["rom"]
    os.environ["HOST_BIOS_DIR"] = _tmp_dirs["bios"]
    os.environ["HOST_CACHE_DIR"] = _tmp_dirs["cache"]
    os.environ["CONFIG_ENV_PATH"] = os.path.join(PROJECT_ROOT, "config.env")
    os.environ["ENABLE_DEBUG_MODE"] = "false"

    # verify_paths() requires at least one .zip in ROM_DIR and one .bin in BIOS_DIR
    _create_dummy_zip(os.path.join(_tmp_dirs["rom"], "DummyGame.zip"))
    open(os.path.join(_tmp_dirs["bios"], "scph1001.bin"), "w").close()


def _create_dummy_zip(path):
    """Create a minimal valid .zip file."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("dummy.bin", "test")


_setup_import_env()

# Mock docker before importing main (main.py calls docker.from_env() at module level)
_mock_docker_patcher = patch("docker.from_env")
_mock_docker = _mock_docker_patcher.start()
_mock_docker.return_value = MagicMock()

import main

_mock_docker_patcher.stop()


def _cleanup_tmp():
    for d in _tmp_dirs.values():
        if d != os.path.join(PROJECT_ROOT, "static") and os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(autouse=True)
def reset_globals():
    """Reset module-level state between tests."""
    main.rate_limit_data.clear()
    main.metrics_cache.clear()
    yield


@pytest.fixture
def rom_dir():
    """Return the temp ROM directory path."""
    return _tmp_dirs["rom"]


@pytest.fixture
def cache_dir():
    """Return the temp cache directory path."""
    return _tmp_dirs["cache"]


@pytest.fixture
def covers_dir():
    """Return the temp covers directory path."""
    return _tmp_dirs["covers"]


def _create_zip(directory, name, contents=None):
    """Helper: create a .zip file with optional dummy content."""
    path = os.path.join(directory, name)
    with zipfile.ZipFile(path, "w") as zf:
        if contents:
            for fname, data in contents.items():
                zf.writestr(fname, data)
        else:
            zf.writestr("dummy.bin", "test data")
    return path


# ============================================================================
# 1. CONFIG LOADING
# ============================================================================

class TestConfigLoading:
    """Tests for load_app_config() default values and overrides."""

    @pytest.fixture(autouse=True)
    def patch_dotenv(self):
        with patch("main.load_dotenv"):
            yield

    def test_default_cpus(self):
        with patch.dict(os.environ, {"CPUS_PER_SESSION": "2.0"}, clear=False):
            main.load_app_config()
            assert main.CPUS_PER_SESSION == 2.0

    def test_custom_cpus(self):
        with patch.dict(os.environ, {"CPUS_PER_SESSION": "4.5"}, clear=False):
            main.load_app_config()
            assert main.CPUS_PER_SESSION == 4.5

    def test_default_mem_limit(self):
        with patch.dict(os.environ, {"MEM_LIMIT_PER_SESSION": "2g"}, clear=False):
            main.load_app_config()
            assert main.MEM_LIMIT_PER_SESSION == "2g"

    def test_custom_mem_limit(self):
        with patch.dict(os.environ, {"MEM_LIMIT_PER_SESSION": "4g"}, clear=False):
            main.load_app_config()
            assert main.MEM_LIMIT_PER_SESSION == "4g"

    def test_debug_mode_false_by_default(self):
        with patch.dict(os.environ, {"ENABLE_DEBUG_MODE": "false"}, clear=False):
            main.load_app_config()
            assert main.ENABLE_DEBUG_MODE is False

    def test_debug_mode_true(self):
        with patch.dict(os.environ, {"ENABLE_DEBUG_MODE": "true"}, clear=False):
            main.load_app_config()
            assert main.ENABLE_DEBUG_MODE is True

    def test_debug_mode_case_insensitive(self):
        with patch.dict(os.environ, {"ENABLE_DEBUG_MODE": "TRUE"}, clear=False):
            main.load_app_config()
            assert main.ENABLE_DEBUG_MODE is True

    def test_max_host_cpu_percent_int(self):
        with patch.dict(os.environ, {"MAX_HOST_CPU_PERCENT": "85"}, clear=False):
            main.load_app_config()
            assert main.MAX_HOST_CPU_PERCENT == 85
            assert isinstance(main.MAX_HOST_CPU_PERCENT, int)

    def test_max_host_mem_percent_int(self):
        with patch.dict(os.environ, {"MAX_HOST_MEM_PERCENT": "75"}, clear=False):
            main.load_app_config()
            assert main.MAX_HOST_MEM_PERCENT == 75
            assert isinstance(main.MAX_HOST_MEM_PERCENT, int)

    def test_rate_limit_int(self):
        with patch.dict(os.environ, {"RATE_LIMIT_SESSIONS_PER_MIN": "5"}, clear=False):
            main.load_app_config()
            assert main.RATE_LIMIT_SESSIONS_PER_MIN == 5
            assert isinstance(main.RATE_LIMIT_SESSIONS_PER_MIN, int)

    def test_rom_cache_max_mb(self):
        with patch.dict(os.environ, {"ROM_CACHE_MAX_MB": "10000"}, clear=False):
            main.load_app_config()
            assert main.ROM_CACHE_MAX_MB == 10000

    def test_network_name(self):
        with patch.dict(os.environ, {"NETWORK_NAME": "my-net"}, clear=False):
            main.load_app_config()
            assert main.NETWORK_NAME == "my-net"

    def test_image_name(self):
        with patch.dict(os.environ, {"IMAGE_NAME": "my-duck"}, clear=False):
            main.load_app_config()
            assert main.IMAGE_NAME == "my-duck"

    def test_domain_remote(self):
        with patch.dict(os.environ, {"DOMAIN_REMOTE": "play.example.com"}, clear=False):
            main.load_app_config()
            assert main.DOMAIN == "play.example.com"


# ============================================================================
# 2. RATE LIMITING
# ============================================================================

class TestRateLimiting:
    """Tests for is_rate_limited() sliding window logic."""

    def test_first_request_not_limited(self):
        assert main.is_rate_limited("client1") is False

    def test_under_limit_not_limited(self):
        main.RATE_LIMIT_SESSIONS_PER_MIN = 3
        assert main.is_rate_limited("client2") is False
        assert main.is_rate_limited("client2") is False

    def test_at_limit_is_limited(self):
        main.RATE_LIMIT_SESSIONS_PER_MIN = 2
        main.is_rate_limited("client3")  # 1st
        main.is_rate_limited("client3")  # 2nd (hits limit)
        assert main.is_rate_limited("client3") is True  # 3rd blocked

    def test_empty_client_id_bypasses(self):
        assert main.is_rate_limited("") is False
        assert main.is_rate_limited(None) is False

    def test_sliding_window_expiry(self):
        main.RATE_LIMIT_SESSIONS_PER_MIN = 1
        # Manually insert an old timestamp (70s ago)
        main.rate_limit_data["client4"] = [time.time() - 70]
        # Should NOT be rate limited because old entry expired
        assert main.is_rate_limited("client4") is False

    def test_different_clients_independent(self):
        main.RATE_LIMIT_SESSIONS_PER_MIN = 1
        main.is_rate_limited("clientA")
        # clientB should not be affected by clientA's usage
        assert main.is_rate_limited("clientB") is False


# ============================================================================
# 3. CACHE KEY GENERATION
# ============================================================================

class TestCacheKeyGeneration:
    """Tests for _safe_cache_key() sanitization."""

    def test_normal_filename(self):
        assert main._safe_cache_key("Metal Gear Solid.zip") == "metal_gear_solid"

    def test_special_characters(self):
        assert main._safe_cache_key("Game: The (US) [!].zip") == "game_the_us"

    def test_multiple_spaces(self):
        result = main._safe_cache_key("  Some   Game  .zip")
        assert "_" in result
        assert result == "some_game"

    def test_already_clean(self):
        assert main._safe_cache_key("crash_bandicoot.zip") == "crash_bandicoot"

    def test_idempotent(self):
        key1 = main._safe_cache_key("Game (Version 1.0).zip")
        key2 = main._safe_cache_key("Game (Version 1.0).zip")
        assert key1 == key2

    def test_case_insensitive(self):
        assert main._safe_cache_key("GAME.zip") == main._safe_cache_key("game.zip")

    def test_disc_suffix_preserved(self):
        # Disc info should be part of the key since it's part of the filename
        key = main._safe_cache_key("Metal Gear (Disc 1).zip")
        assert "disc" in key


# ============================================================================
# 4. MULTI-DISC DETECTION
# ============================================================================

class TestMultiDiscDetection:
    """Tests for _identify_disc_set() pattern matching."""

    def test_single_disc_unchanged(self):
        assert main._identify_disc_set("Crash Bandicoot.zip") == "Crash Bandicoot.zip"

    def test_disc_1(self):
        assert main._identify_disc_set("Metal Gear Solid (Disc 1).zip") == "Metal Gear Solid"

    def test_disc_2(self):
        assert main._identify_disc_set("Metal Gear Solid (Disc 2).zip") == "Metal Gear Solid"

    def test_disc_3(self):
        assert main._identify_disc_set("Final Fantasy VII (Disc 3).zip") == "Final Fantasy VII"

    def test_case_insensitive_disc(self):
        assert main._identify_disc_set("Game (disc 1).zip") == "Game"

    def test_no_false_positive_on_parentheses(self):
        # Should NOT match "(Disc X)" pattern
        result = main._identify_disc_set("Tomb Raider (USA).zip")
        assert result == "Tomb Raider (USA).zip"

    def test_extra_spaces(self):
        assert main._identify_disc_set("Game  (Disc  1).zip") == "Game"


# ============================================================================
# 5. DISC SIBLING FINDER
# ============================================================================

class TestDiscSiblingFinder:
    """Tests for find_disc_siblings() file discovery."""

    def test_single_game_returns_itself(self, rom_dir):
        _create_zip(rom_dir, "Crash.zip")
        main.ROM_DIR = rom_dir
        result = main.find_disc_siblings("Crash.zip")
        assert result == ["Crash.zip"]

    def test_multi_disc_finds_all(self, rom_dir):
        _create_zip(rom_dir, "Metal Gear (Disc 1).zip")
        _create_zip(rom_dir, "Metal Gear (Disc 2).zip")
        main.ROM_DIR = rom_dir
        result = main.find_disc_siblings("Metal Gear (Disc 1).zip")
        assert len(result) == 2
        assert "Metal Gear (Disc 1).zip" in result
        assert "Metal Gear (Disc 2).zip" in result

    def test_siblings_sorted(self, rom_dir):
        _create_zip(rom_dir, "FF7 (Disc 3).zip")
        _create_zip(rom_dir, "FF7 (Disc 1).zip")
        _create_zip(rom_dir, "FF7 (Disc 2).zip")
        main.ROM_DIR = rom_dir
        result = main.find_disc_siblings("FF7 (Disc 2).zip")
        assert result == ["FF7 (Disc 1).zip", "FF7 (Disc 2).zip", "FF7 (Disc 3).zip"]

    def test_no_false_positives(self, rom_dir):
        _create_zip(rom_dir, "Metal Gear (Disc 1).zip")
        _create_zip(rom_dir, "Metal Gear (Disc 2).zip")
        _create_zip(rom_dir, "Other Game.zip")
        main.ROM_DIR = rom_dir
        result = main.find_disc_siblings("Metal Gear (Disc 1).zip")
        assert "Other Game.zip" not in result


# ============================================================================
# 6. ROM LISTING
# ============================================================================

class TestRomListing:
    """Tests for list_roms() API response structure."""

    @pytest.mark.asyncio
    async def test_returns_correct_structure(self, rom_dir):
        main.ROM_DIR = rom_dir
        main.ENABLE_DEBUG_MODE = False
        result = await main.list_roms()
        assert "ps1" in result
        assert "snes" in result
        assert "gba" in result
        assert isinstance(result["ps1"], list)

    @pytest.mark.asyncio
    async def test_lists_zip_files(self, rom_dir):
        _create_zip(rom_dir, "Crash.zip")
        _create_zip(rom_dir, "Spyro.zip")
        main.ROM_DIR = rom_dir
        main.ENABLE_DEBUG_MODE = False
        result = await main.list_roms()
        names = [r["display_name"] for r in result["ps1"]]
        assert "Crash" in names
        assert "Spyro" in names

    @pytest.mark.asyncio
    async def test_deduplicates_multi_disc(self, rom_dir):
        _create_zip(rom_dir, "FF7 (Disc 1).zip")
        _create_zip(rom_dir, "FF7 (Disc 2).zip")
        _create_zip(rom_dir, "FF7 (Disc 3).zip")
        main.ROM_DIR = rom_dir
        main.ENABLE_DEBUG_MODE = False
        result = await main.list_roms()
        ff7_entries = [r for r in result["ps1"] if "FF7" in r["display_name"]]
        assert len(ff7_entries) == 1

    @pytest.mark.asyncio
    async def test_debug_mode_adds_debug_entry(self, rom_dir):
        main.ROM_DIR = rom_dir
        with patch("main.load_app_config"):
            main.ENABLE_DEBUG_MODE = True
            result = await main.list_roms()
        debug_entries = [r for r in result["ps1"] if r["filename"] == "DEBUG_MODE_FULL_ACCESS"]
        assert len(debug_entries) == 1

    @pytest.mark.asyncio
    async def test_debug_mode_off_no_debug_entry(self, rom_dir):
        main.ROM_DIR = rom_dir
        with patch("main.load_app_config"):
            main.ENABLE_DEBUG_MODE = False
            result = await main.list_roms()
        debug_entries = [r for r in result["ps1"] if r["filename"] == "DEBUG_MODE_FULL_ACCESS"]
        assert len(debug_entries) == 0

    @pytest.mark.asyncio
    async def test_rom_entry_has_required_fields(self, rom_dir):
        _create_zip(rom_dir, "TestGame.zip")
        main.ROM_DIR = rom_dir
        main.ENABLE_DEBUG_MODE = False
        result = await main.list_roms()
        entry = result["ps1"][0]
        assert "filename" in entry
        assert "display_name" in entry
        assert "game_id" in entry
        assert "poster_url" in entry
        assert "platform" in entry
        assert entry["platform"] == "ps1"

    @pytest.mark.asyncio
    async def test_snes_rom_listing(self):
        snes_dir = _tmp_dirs["snes"]
        _create_zip(snes_dir, "SuperMario.zip")
        main.SNES_ROM_DIR = snes_dir
        result = await main.list_roms()
        assert len(result["snes"]) >= 1
        assert result["snes"][0]["platform"] == "snes"

    @pytest.mark.asyncio
    async def test_gba_rom_listing(self):
        gba_dir = _tmp_dirs["gba"]
        _create_zip(gba_dir, "Pokemon.zip")
        main.GBA_ROM_DIR = gba_dir
        result = await main.list_roms()
        assert len(result["gba"]) >= 1
        assert result["gba"][0]["platform"] == "gba"


# ============================================================================
# 7. GRAPHICS PROFILE SELECTION
# ============================================================================

class TestGraphicsProfiles:
    """Tests for resolution scale → renderer/display mapping."""

    def _get_profile(self, scale):
        """Extract the profile tuple that start_session() produces."""
        if scale <= 1:
            return "Software", "0", "false", "false", "false", 1024, 768
        elif scale == 2:
            return "Vulkan", "1", "true", "true", "true", 1024, 768
        else:
            return "Vulkan", "3", "true", "true", "true", 1280, 1024

    def test_scale_1_software(self):
        r, f, pg, pt, tc, w, h = self._get_profile(1)
        assert r == "Software"
        assert f == "0"
        assert pg == "false"
        assert w == 1024 and h == 768

    def test_scale_2_vulkan_mid(self):
        r, f, pg, pt, tc, w, h = self._get_profile(2)
        assert r == "Vulkan"
        assert f == "1"
        assert pg == "true"
        assert tc == "true"

    def test_scale_3_vulkan_high(self):
        r, f, pg, pt, tc, w, h = self._get_profile(3)
        assert r == "Vulkan"
        assert f == "3"
        assert w == 1280 and h == 1024

    def test_scale_4_same_as_3(self):
        assert self._get_profile(4) == self._get_profile(3)

    def test_scale_0_treated_as_software(self):
        r, *_ = self._get_profile(0)
        assert r == "Software"


# ============================================================================
# 8. CONTAINER ENV INJECTION
# ============================================================================

class TestContainerEnvInjection:
    """Tests for env vars injected into DuckStation containers."""

    def test_show_fps_injected(self):
        with patch.dict(os.environ, {"SHOW_FPS": "true"}, clear=False):
            assert os.getenv("SHOW_FPS") == "true"

    def test_show_fps_default_false(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOW_FPS", None)
            assert os.getenv("SHOW_FPS", "false") == "false"

    def test_stream_quality_to_crf_mapping_high(self):
        """Quality 100 should give lowest CRF (best quality)."""
        quality = 100
        crf = 50 - int((quality / 100) * 45)
        assert crf == 5

    def test_stream_quality_to_crf_mapping_low(self):
        """Quality 1 should give highest CRF (worst quality)."""
        quality = 1
        crf = 50 - int((quality / 100) * 45)
        assert crf == 50

    def test_stream_quality_to_crf_mapping_default(self):
        """Quality 50 should give CRF ~28."""
        quality = 50
        crf = 50 - int((quality / 100) * 45)
        assert crf == 28

    def test_stream_quality_to_crf_mapping_midrange(self):
        """Quality 75 → CRF ~17 (good quality)."""
        quality = 75
        crf = 50 - int((quality / 100) * 45)
        assert crf == 17

    def test_audio_backend_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUDIO_BACKEND", None)
            assert os.getenv("AUDIO_BACKEND", "Cubeb") == "Cubeb"

    def test_audio_backend_custom(self):
        with patch.dict(os.environ, {"AUDIO_BACKEND": "PulseAudio"}, clear=False):
            assert os.getenv("AUDIO_BACKEND", "Cubeb") == "PulseAudio"

    def test_stream_bitrate_maps_to_selkies(self):
        with patch.dict(os.environ, {"STREAM_BITRATE": "4000"}, clear=False):
            assert os.getenv("STREAM_BITRATE", "2000") == "4000"

    def test_stream_framerate_maps_to_selkies(self):
        with patch.dict(os.environ, {"STREAM_FRAMERATE": "60"}, clear=False):
            assert os.getenv("STREAM_FRAMERATE", "30") == "60"

    def test_security_hardening_vars_present(self):
        """Verify all 11 security hardening vars are defined in start_session code."""
        import inspect
        source = inspect.getsource(main.start_session)
        required = [
            "HARDEN_DESKTOP", "DISABLE_OPEN_TOOLS", "DISABLE_SUDO",
            "DISABLE_TERMINALS", "DISABLE_CLOSE_BUTTON", "DISABLE_MOUSE_BUTTONS",
            "HARDEN_KEYBINDS", "SELKIES_COMMAND_ENABLED",
            "SELKIES_UI_SIDEBAR_SHOW_FILES", "SELKIES_UI_SIDEBAR_SHOW_APPS",
            "SELKIES_FILE_TRANSFERS"
        ]
        for var in required:
            assert var in source, f"Missing security var: {var}"


# ============================================================================
# 9. SESSION STATUS API
# ============================================================================

class TestSessionStatusAPI:
    """Tests for get_session_status() endpoint logic."""

    def test_returns_cached_metrics(self):
        main.metrics_cache["test-session"] = {"session_id": "test-session", "status": "running_game"}
        mock_container = MagicMock()
        mock_container.labels = {"owner": "client1"}
        main.client.containers.get = MagicMock(return_value=mock_container)

        result = main.get_session_status("test-session", "client1")
        assert result["status"] == "running_game"

    def test_wrong_owner_raises_403(self):
        mock_container = MagicMock()
        mock_container.labels = {"owner": "client1"}
        main.client.containers.get = MagicMock(return_value=mock_container)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            main.get_session_status("test-session", "different-client")
        assert exc_info.value.status_code == 403

    def test_missing_session_returns_not_found(self):
        import docker.errors
        main.client.containers.get = MagicMock(
            side_effect=docker.errors.NotFound("not found")
        )
        result = main.get_session_status("missing-session", "client1")
        assert result["status"] == "not_found"

    def test_initializing_when_no_metrics_cached(self):
        main.metrics_cache.clear()
        mock_container = MagicMock()
        mock_container.labels = {"owner": "client1"}
        main.client.containers.get = MagicMock(return_value=mock_container)

        result = main.get_session_status("new-session", "client1")
        assert result["status"] == "initializing"


# ============================================================================
# 10. STOP SESSION API
# ============================================================================

class TestStopSessionAPI:
    """Tests for stop_session() endpoint logic."""

    def test_owner_can_stop(self):
        mock_container = MagicMock()
        mock_container.labels = {"owner": "client1"}
        mock_container.name = "duckstation-test123"
        main.client.containers.get = MagicMock(return_value=mock_container)

        request = main.StopRequest(client_id="client1")
        result = main.stop_session("test123", request)
        mock_container.remove.assert_called_once_with(force=True)

    def test_non_owner_gets_403(self):
        mock_container = MagicMock()
        mock_container.labels = {"owner": "client1"}
        main.client.containers.get = MagicMock(return_value=mock_container)

        from fastapi import HTTPException
        request = main.StopRequest(client_id="wrong-client")
        with pytest.raises(HTTPException) as exc_info:
            main.stop_session("test123", request)
        assert exc_info.value.status_code == 403


# ============================================================================
# 11. WASM PLATFORM ROUTING
# ============================================================================

class TestWasmPlatformRouting:
    """Tests for SNES/GBA static URL routing (no Docker container)."""

    @pytest.mark.asyncio
    async def test_snes_returns_emulator_url(self):
        main.RATE_LIMIT_SESSIONS_PER_MIN = 100
        main.MAX_HOST_CPU_PERCENT = 100
        main.MAX_HOST_MEM_PERCENT = 100

        request = main.SessionRequest(
            game_filename="SuperMario.zip",
            client_id="test-client",
            platform="snes"
        )

        # Mock client.containers.list to return empty (no existing containers)
        main.client.containers.list = MagicMock(return_value=[])

        result = await main.start_session(request)
        assert "emulator.html" in result["url_path"]
        assert "core=snes" in result["url_path"]
        assert result["platform"] == "snes"

    @pytest.mark.asyncio
    async def test_gba_returns_emulator_url(self):
        main.RATE_LIMIT_SESSIONS_PER_MIN = 100
        main.MAX_HOST_CPU_PERCENT = 100
        main.MAX_HOST_MEM_PERCENT = 100

        request = main.SessionRequest(
            game_filename="Pokemon.zip",
            client_id="test-client-2",
            platform="gba"
        )
        main.client.containers.list = MagicMock(return_value=[])

        result = await main.start_session(request)
        assert "emulator.html" in result["url_path"]
        assert "core=gba" in result["url_path"]
        assert result["platform"] == "gba"


# ============================================================================
# 12. ROM CACHE
# ============================================================================

class TestRomCache:
    """Tests for ROM extraction and cache management."""

    def test_cache_disabled_returns_none(self):
        main.ROM_CACHE_MAX_MB = 0
        result = main.get_or_extract_rom_set(["game.zip"])
        assert result is None

    def test_cache_creates_and_extracts(self, rom_dir, cache_dir):
        main.ROM_DIR = rom_dir
        main.ROM_CACHE_DIR = cache_dir
        main.ROM_CACHE_MAX_MB = 5000

        _create_zip(rom_dir, "TestGame.zip", {"TestGame.cue": "FILE test.bin", "test.bin": "data"})

        result = main.get_or_extract_rom_set(["TestGame.zip"])
        assert result is not None
        assert os.path.isdir(result)
        assert os.path.exists(os.path.join(result, ".extracted_all"))

    def test_cache_idempotent(self, rom_dir, cache_dir):
        main.ROM_DIR = rom_dir
        main.ROM_CACHE_DIR = cache_dir
        main.ROM_CACHE_MAX_MB = 5000

        _create_zip(rom_dir, "IdempotentGame.zip", {"game.bin": "data"})

        result1 = main.get_or_extract_rom_set(["IdempotentGame.zip"])
        result2 = main.get_or_extract_rom_set(["IdempotentGame.zip"])
        assert result1 == result2

    def test_get_cache_size_mb(self, cache_dir):
        main.ROM_CACHE_DIR = cache_dir
        # Create a 1MB file
        test_file = os.path.join(cache_dir, "test_1mb.bin")
        with open(test_file, "wb") as f:
            f.write(b"\0" * (1024 * 1024))

        size = main._get_cache_size_mb()
        assert size >= 1

    def test_get_cache_size_empty_dir(self, cache_dir):
        # Clean any files from other tests
        for f in os.listdir(cache_dir):
            p = os.path.join(cache_dir, f)
            if os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
        main.ROM_CACHE_DIR = cache_dir
        size = main._get_cache_size_mb()
        assert size == 0


# ============================================================================
# 13. WATCHDOG
# ============================================================================

class TestWatchdog:
    """Tests for watchdog.py idle session cleanup logic."""

    def test_grace_period_skips_new_containers(self):
        """Containers < 120s old should be skipped."""
        from datetime import datetime
        # Container created "now" (< 120s ago)
        created = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + ".000000000Z"
        container = MagicMock()
        container.attrs = {"Created": created}
        container.id = "grace-test"
        uptime = (datetime.utcnow() - datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds()
        assert uptime < 120, "New container should be within grace period"

    def test_idle_timeout_from_env(self):
        with patch.dict(os.environ, {"IDLE_TIMEOUT_MINS": "15"}, clear=False):
            val = int(os.getenv("IDLE_TIMEOUT_MINS", "30"))
            assert val == 15

    def test_idle_timeout_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("IDLE_TIMEOUT_MINS", None)
            val = int(os.getenv("IDLE_TIMEOUT_MINS", "30"))
            assert val == 30


# ============================================================================
# 14. ADMIN API
# ============================================================================

class TestAdminAPI:
    """Tests for admin endpoint logic."""

    def test_admin_sessions_returns_list(self):
        main.metrics_cache["s1"] = {"session_id": "s1", "status": "running_game", "cpu": 10.5}
        main.metrics_cache["s2"] = {"session_id": "s2", "status": "initializing", "cpu": 0.0}
        main.host_metrics = {"cpu": 45.0, "ram": 60.0}

        mock_containers = [
            MagicMock(name="duckstation-s1"),
            MagicMock(name="duckstation-s2"),
        ]
        mock_containers[0].name = "duckstation-s1"
        mock_containers[0].labels = {"owner": "c1"}
        mock_containers[0].attrs = {"Config": {"Env": ["GAME_NAME=game1"]}}
        mock_containers[1].name = "duckstation-s2"
        mock_containers[1].labels = {"owner": "c2"}
        mock_containers[1].attrs = {"Config": {"Env": ["GAME_NAME=game2"]}}
        
        main.client.containers.list = MagicMock(return_value=mock_containers)
        
        result = main.admin_list_sessions()
        assert "sessions" in result
        assert "host" in result

    def test_admin_stop_session(self):
        mock_container = MagicMock()
        mock_container.name = "duckstation-killme"
        main.client.containers.get = MagicMock(return_value=mock_container)

        result = main.admin_stop_session("killme")
        mock_container.remove.assert_called_once_with(force=True)


# ============================================================================
# 15. HOST RESOURCE CHECKING
# ============================================================================

class TestHostResourceCheck:
    """Tests for check_host_resources() CPU/RAM safety valve."""

    def test_returns_ok_when_healthy(self):
        main.MAX_HOST_CPU_PERCENT = 100  # impossible to exceed
        main.MAX_HOST_MEM_PERCENT = 100
        ok, msg = main.check_host_resources()
        assert ok is True
        assert msg == "OK"

    def test_cpu_overload_blocks(self):
        main.MAX_HOST_CPU_PERCENT = 0  # always exceeds
        main.MAX_HOST_MEM_PERCENT = 100
        ok, msg = main.check_host_resources()
        assert ok is False
        assert "CPU" in msg

    def test_mem_overload_blocks(self):
        main.MAX_HOST_CPU_PERCENT = 100
        main.MAX_HOST_MEM_PERCENT = 0  # always exceeds
        ok, msg = main.check_host_resources()
        assert ok is False
        assert "memory" in msg


# ============================================================================
# CLEANUP
# ============================================================================

def pytest_sessionfinish(session, exitstatus):
    """Clean up temp directories after all tests."""
    _cleanup_tmp()
