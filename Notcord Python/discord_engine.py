"""
Notcord Discord API Engine - v2.2.0
Handles authentication, DM/Guild fetching, message scanning & deletion,
advanced favorite GIF management, account tools, avatar caching, and self-destruct / auto-edit.
Created by Qorelith
"""

import base64
import datetime
import glob
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageOps
import requests

try:
    from discord_protos import FrecencyUserSettings
    HAS_DISCORD_PROTOS = True
except ImportError:
    HAS_DISCORD_PROTOS = False

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

    def _decrypt_dpapi(encrypted_bytes: bytes) -> Optional[bytes]:
        try:
            blob_in = _DATA_BLOB(
                len(encrypted_bytes),
                ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_byte))
            )
            blob_out = _DATA_BLOB()
            if ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
            ):
                cb_data = int(blob_out.cbData)
                pb_data = blob_out.pbData
                buffer = ctypes.string_at(pb_data, cb_data)
                ctypes.windll.kernel32.LocalFree(pb_data)
                return buffer
        except Exception:
            pass
        return None
else:
    def _decrypt_dpapi(encrypted_bytes: bytes) -> Optional[bytes]:
        return None

DISCORD_API_BASE = "https://discord.com/api/v9"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "assets", "cache")
try:
    os.makedirs(CACHE_DIR, exist_ok=True)
except Exception:
    pass


def get_headers(token: str) -> dict:
    """Returns headers for Discord API requests using user token."""
    clean_token = token.strip().strip('"').strip("'")
    return {
        "Authorization": clean_token,
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "*/*"
    }


def verify_token(token: str) -> Tuple[bool, Optional[dict], Optional[str]]:
    """Verifies token and fetches current user info."""
    headers = get_headers(token)
    try:
        url = f"{DISCORD_API_BASE}/users/@me"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return True, res.json(), None
        elif res.status_code == 401:
            return False, None, "Invalid or expired token (401 Unauthorized)"
        else:
            return False, None, f"Discord API returned status {res.status_code}: {res.text}"
    except requests.exceptions.RequestException as e:
        return False, None, f"Network error: {str(e)}"


def _read_file_shared(path: str) -> bytes:
    """Reads a file with shared read/write/delete locks on Windows to bypass active process locks."""
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateFileW(
                path,
                0x80000000,  # GENERIC_READ
                0x00000007,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
                None,
                3,           # OPEN_EXISTING
                0x80,        # FILE_ATTRIBUTE_NORMAL
                None
            )
            if handle != -1 and handle != ctypes.wintypes.HANDLE(-1).value:
                try:
                    size = kernel32.GetFileSize(handle, None)
                    if size > 0:
                        buf = ctypes.create_string_buffer(size)
                        read_bytes = ctypes.wintypes.DWORD()
                        if kernel32.ReadFile(handle, buf, size, ctypes.byref(read_bytes), None):
                            return buf.raw[:read_bytes.value]
                finally:
                    kernel32.CloseHandle(handle)
        except Exception:
            pass
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return b""


def find_local_discord_sessions() -> List[Tuple[str, dict]]:
    """
    Scans local Windows Discord installations, browser sessions (including DuckDuckGo,
    Chrome profiles, Edge, Brave, Opera), and Web sessions for active user tokens.
    Uses shared file reads to handle running Discord/browser locks.
    Returns list of verified (token, user_data) tuples.
    """
    if not HAS_CRYPTO or sys.platform != "win32":
        return []

    tokens: List[str] = []
    appdata = os.getenv("APPDATA")
    localappdata = os.getenv("LOCALAPPDATA")

    candidate_dirs: List[str] = []

    if appdata:
        # Standard Discord desktop clients
        candidate_dirs.extend([
            os.path.join(appdata, "discord"),
            os.path.join(appdata, "discordcanary"),
            os.path.join(appdata, "discordptb"),
            os.path.join(appdata, "discorddevelopment"),
            os.path.join(appdata, "vesktop", "sessionData"),
            os.path.join(appdata, "Opera Software", "Opera Stable"),
            os.path.join(appdata, "Opera Software", "Opera GX Stable"),
        ])

    if localappdata:
        candidate_dirs.extend([
            os.path.join(localappdata, "Discord"),
            os.path.join(localappdata, "discordcanary"),
            os.path.join(localappdata, "discordptb"),
            os.path.join(localappdata, "Programs", "Opera", "profile"),
            os.path.join(localappdata, "Programs", "Opera GX", "profile"),
            os.path.join(localappdata, "Yandex", "YandexBrowser", "User Data", "Default"),
            os.path.join(localappdata, "Arc", "User Data", "Default"),
        ])

        # Microsoft Store Discord packages
        for pkg in glob.glob(os.path.join(localappdata, "Packages", "*Discord*", "LocalCache", "Roaming", "discord")):
            candidate_dirs.append(pkg)

        # Chrome profiles (Default, Profile 1, Profile 2, etc.)
        candidate_dirs.append(os.path.join(localappdata, "Google", "Chrome", "User Data", "Default"))
        for p in glob.glob(os.path.join(localappdata, "Google", "Chrome", "User Data", "Profile *")):
            candidate_dirs.append(p)

        # Edge profiles
        candidate_dirs.append(os.path.join(localappdata, "Microsoft", "Edge", "User Data", "Default"))
        for p in glob.glob(os.path.join(localappdata, "Microsoft", "Edge", "User Data", "Profile *")):
            candidate_dirs.append(p)

        # Brave profiles
        candidate_dirs.append(os.path.join(localappdata, "BraveSoftware", "Brave-Browser", "User Data", "Default"))
        for p in glob.glob(os.path.join(localappdata, "BraveSoftware", "Brave-Browser", "User Data", "Profile *")):
            candidate_dirs.append(p)

        # Vivaldi profiles
        candidate_dirs.append(os.path.join(localappdata, "Vivaldi", "User Data", "Default"))
        for p in glob.glob(os.path.join(localappdata, "Vivaldi", "User Data", "Profile *")):
            candidate_dirs.append(p)

        # DuckDuckGo Windows Browser (find all webview leveldb dirs)
        ddg_base = os.path.join(localappdata, "DuckDuckGo")
        if os.path.exists(ddg_base):
            for ldb_path in glob.glob(os.path.join(ddg_base, "**", "leveldb"), recursive=True):
                prof_dir = os.path.dirname(os.path.dirname(ldb_path))
                if prof_dir and prof_dir not in candidate_dirs:
                    candidate_dirs.append(prof_dir)

    # Deduplicate candidate directories
    seen_dirs = set()
    cleaned_candidate_dirs = []
    for d in candidate_dirs:
        norm = os.path.normpath(d).lower()
        if norm not in seen_dirs and os.path.exists(d):
            seen_dirs.add(norm)
            cleaned_candidate_dirs.append(d)

    for disc_dir in cleaned_candidate_dirs:
        # Search for Local State file to decrypt key
        key = None
        for try_path in [
            os.path.join(disc_dir, "Local State"),
            os.path.join(os.path.dirname(disc_dir), "Local State"),
            os.path.join(os.path.dirname(os.path.dirname(disc_dir)), "Local State")
        ]:
            if os.path.exists(try_path):
                try:
                    with open(try_path, "r", encoding="utf-8") as f:
                        local_state = json.load(f)
                    encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
                    key = _decrypt_dpapi(encrypted_key[5:])
                    if key:
                        break
                except Exception:
                    pass

        leveldb_paths = [
            os.path.join(disc_dir, "Local Storage", "leveldb"),
            os.path.join(disc_dir, "leveldb"),
            os.path.join(disc_dir, "Session Storage")
        ]

        for leveldb_path in leveldb_paths:
            if not os.path.exists(leveldb_path):
                continue

            aesgcm = None
            if key:
                try:
                    aesgcm = AESGCM(key)
                except Exception:
                    aesgcm = None

            files = glob.glob(os.path.join(leveldb_path, "*.ldb")) + glob.glob(os.path.join(leveldb_path, "*.log"))
            for file_path in files:
                try:
                    raw_bytes = _read_file_shared(file_path)
                    if not raw_bytes:
                        continue
                    content = raw_bytes.decode("latin-1", errors="ignore")

                    # 1. Encrypted Discord token pattern (dQw4w9WgXcQ:...)
                    if aesgcm:
                        matches = re.findall(r'dQw4w9WgXcQ:([a-zA-Z0-9+/=]+)', content)
                        for m in matches:
                            try:
                                pad = len(m) % 4
                                if pad:
                                    m += "=" * (4 - pad)
                                raw = base64.b64decode(m)
                                iv = raw[3:15]
                                payload = raw[15:]
                                decrypted = aesgcm.decrypt(iv, payload, None).decode("utf-8", errors="ignore")
                                if decrypted and len(decrypted) > 30 and decrypted not in tokens:
                                    tokens.append(decrypted)
                            except Exception:
                                pass

                    # 2. Unencrypted token pattern (used in browser sessions like DuckDuckGo, Chrome, etc.)
                    unenc_matches = re.findall(r'[\w-]{24,28}\.[\w-]{6}\.[\w-]{27,110}', content)
                    for ut in unenc_matches:
                        if ut not in tokens:
                            tokens.append(ut)

                    # 3. MFA token pattern
                    mfa_matches = re.findall(r'mfa\.[\w-]{84}', content)
                    for mt in mfa_matches:
                        if mt not in tokens:
                            tokens.append(mt)

                except Exception:
                    pass

    valid_sessions: List[Tuple[str, dict]] = []
    for t in tokens:
        ok, udata, _ = verify_token(t)
        if ok and udata:
            if not any(s[1].get("id") == udata.get("id") for s in valid_sessions):
                valid_sessions.append((t, udata))

    return valid_sessions


def get_user_avatar_url(user_data: dict, size: int = 64) -> str:
    """Gets avatar URL for a user, enforcing .png format for safe and consistent rendering."""
    user_id = user_data.get("id")
    avatar = user_data.get("avatar")
    if not avatar:
        discrim = int(user_data.get("discriminator", "0"))
        if discrim == 0:
            index = (int(user_id) >> 22) % 6 if user_id and str(user_id).isdigit() else 0
        else:
            index = discrim % 5
        return f"https://cdn.discordapp.com/embed/avatars/{index}.png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size={size}"


def get_guild_icon_url(guild_data: dict, size: int = 64) -> Optional[str]:
    """Gets icon URL for a guild."""
    guild_id = guild_data.get("id")
    icon = guild_data.get("icon")
    if not icon:
        return None
    return f"https://cdn.discordapp.com/icons/{guild_id}/{icon}.png?size={size}"


# ================= AVATAR & ICON CACHE =================

class AvatarCache:
    """Handles downloading, circular clipping, and caching of user and guild avatars."""
    _memory_cache: Dict[str, Image.Image] = {}
    _pool = ThreadPoolExecutor(max_workers=8)
    _lock = threading.Lock()

    @classmethod
    def clear_disk_cache(cls):
        """Deletes all cached avatar files from disk and clears in-memory cache."""
        with cls._lock:
            cls._memory_cache.clear()
        if os.path.exists(CACHE_DIR):
            for fname in os.listdir(CACHE_DIR):
                if fname.lower().endswith(".png"):
                    try:
                        fpath = os.path.join(CACHE_DIR, fname)
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                    except Exception:
                        pass

    @classmethod
    def get_cached_path(cls, url: str) -> str:
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        return os.path.join(CACHE_DIR, f"{url_hash}.png")

    @classmethod
    def circle_crop(cls, img: Image.Image, size: Tuple[int, int]) -> Image.Image:
        try:
            copy_img = img.copy().convert("RGBA").resize(size, Image.LANCZOS)
            mask = Image.new("L", size, 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, size[0], size[1]), fill=255)
            output = ImageOps.fit(copy_img, mask.size, centering=(0.5, 0.5))
            output.putalpha(mask)
            output.load()
            return output
        except Exception:
            fallback = img.copy().convert("RGBA").resize(size)
            fallback.load()
            return fallback

    @classmethod
    def load_avatar_sync(cls, url: str, size: Tuple[int, int] = (32, 32)) -> Optional[Image.Image]:
        if not url:
            return None
        cache_key = f"{url}_{size[0]}x{size[1]}"
        with cls._lock:
            if cache_key in cls._memory_cache:
                return cls._memory_cache[cache_key]

        disk_path = cls.get_cached_path(url)
        if os.path.exists(disk_path):
            if os.path.getsize(disk_path) > 10:
                try:
                    with Image.open(disk_path) as raw_img:
                        circle = cls.circle_crop(raw_img, size)
                        with cls._lock:
                            cls._memory_cache[cache_key] = circle
                        return circle
                except Exception:
                    try:
                        os.remove(disk_path)
                    except Exception:
                        pass
            else:
                try:
                    os.remove(disk_path)
                except Exception:
                    pass

        # Download from network
        try:
            res = requests.get(url, timeout=8, headers={"User-Agent": DEFAULT_USER_AGENT})
            if res.status_code == 200 and len(res.content) > 10:
                with open(disk_path, "wb") as f:
                    f.write(res.content)
                with Image.open(disk_path) as raw_img:
                    circle = cls.circle_crop(raw_img, size)
                    with cls._lock:
                        cls._memory_cache[cache_key] = circle
                    return circle
        except Exception:
            pass
        return None

    @classmethod
    def load_avatar_async(cls, url: str, size: Tuple[int, int], callback: Callable[[Optional[Image.Image]], None]):
        """Asynchronously loads avatar and invokes callback with PIL Image."""
        if not url:
            callback(None)
            return

        def _worker():
            try:
                img = cls.load_avatar_sync(url, size)
                callback(img)
            except Exception:
                callback(None)

        cls._pool.submit(_worker)


# ================= DATA FETCHING =================

def get_dms(token: str) -> List[dict]:
    """Fetches user direct message and group DM channels."""
    headers = get_headers(token)
    url = f"{DISCORD_API_BASE}/users/@me/channels"
    res = requests.get(url, headers=headers, timeout=15)
    if res.status_code != 200:
        return []

    channels = res.json()
    formatted = []
    for ch in channels:
        ch_type = ch.get("type")
        ch_id = ch.get("id")
        last_msg_id = ch.get("last_message_id") or "0"

        if ch_type == 1:
            recipients = ch.get("recipients", [])
            recipient = recipients[0] if recipients else {}
            name = recipient.get("global_name") or recipient.get("username") or "Unknown Friend"
            handle = recipient.get("username", "")
            avatar_url = get_user_avatar_url(recipient) if recipient else None
            formatted.append({
                "id": ch_id,
                "name": name,
                "handle": handle,
                "type": "dm",
                "type_name": "Direct Message",
                "avatar_url": avatar_url,
                "last_message_id": int(last_msg_id) if last_msg_id.isdigit() else 0
            })
        elif ch_type == 3:
            name = ch.get("name")
            if not name:
                names = [r.get("global_name") or r.get("username") for r in ch.get("recipients", [])[:3]]
                name = ", ".join(filter(None, names)) or "Group Chat"
            icon = ch.get("icon")
            icon_url = f"https://cdn.discordapp.com/channel-icons/{ch_id}/{icon}.png?size=64" if icon else None
            formatted.append({
                "id": ch_id,
                "name": name,
                "handle": f"{len(ch.get('recipients', [])) + 1} members",
                "type": "group",
                "type_name": "Group DM",
                "avatar_url": icon_url,
                "last_message_id": int(last_msg_id) if last_msg_id.isdigit() else 0
            })

    formatted.sort(key=lambda x: x["last_message_id"], reverse=True)
    return formatted


def get_guilds(token: str) -> List[dict]:
    """Fetches user guilds (servers)."""
    headers = get_headers(token)
    url = f"{DISCORD_API_BASE}/users/@me/guilds"
    res = requests.get(url, headers=headers, timeout=15)
    if res.status_code != 200:
        return []
    guilds = res.json()
    result = []
    for g in guilds:
        result.append({
            "id": g.get("id"),
            "name": g.get("name"),
            "icon_url": get_guild_icon_url(g),
            "owner": g.get("owner", False)
        })
    return result


def get_guild_channels(token: str, guild_id: str) -> List[dict]:
    """Fetches text channels in a guild."""
    headers = get_headers(token)
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/channels"
    res = requests.get(url, headers=headers, timeout=15)
    if res.status_code != 200:
        return []
    channels = res.json()
    text_channels = [
        {
            "id": c.get("id"),
            "name": "#" + c.get("name"),
            "type": "channel",
            "type_name": "Server Channel",
            "position": c.get("position", 0),
            "parent_id": c.get("parent_id"),
            "last_message_id": int(c.get("last_message_id") or 0) if str(c.get("last_message_id", "")).isdigit() else 0
        }
        for c in channels if c.get("type") in (0, 5)
    ]
    text_channels.sort(key=lambda x: x["position"])
    return text_channels


def resolve_target_by_id(token: str, raw_id: str) -> Tuple[bool, Optional[dict], Optional[str]]:
    """Resolves a target by ID (User ID or Channel ID)."""
    clean_id = raw_id.strip().strip("<#>@ ")
    if not clean_id or not clean_id.isdigit():
        return False, None, "Invalid ID format. Must be numeric Discord snowflake ID."

    headers = get_headers(token)

    # 1. Try opening DM with user ID
    dm_url = f"{DISCORD_API_BASE}/users/@me/channels"
    try:
        res = requests.post(dm_url, headers=headers, json={"recipient_id": clean_id}, timeout=10)
        if res.status_code in (200, 201):
            ch = res.json()
            recipients = ch.get("recipients", [])
            recipient = recipients[0] if recipients else {}
            name = recipient.get("global_name") or recipient.get("username") or f"User {clean_id}"
            handle = recipient.get("username", clean_id)
            return True, {
                "id": ch.get("id"),
                "name": name,
                "handle": f"@{handle} (User ID: {clean_id})",
                "type": "dm",
                "type_name": "Direct Message",
                "avatar_url": get_user_avatar_url(recipient) if recipient else None,
                "last_message_id": int(ch.get("last_message_id") or 0)
            }, None
    except requests.exceptions.RequestException:
        pass

    # 2. Try fetching channel directly by channel ID
    ch_url = f"{DISCORD_API_BASE}/channels/{clean_id}"
    try:
        ch_res = requests.get(ch_url, headers=headers, timeout=10)
        if ch_res.status_code == 200:
            ch = ch_res.json()
            ch_type = ch.get("type")
            ch_id = ch.get("id")
            if ch_type == 1:
                recipients = ch.get("recipients", [])
                recipient = recipients[0] if recipients else {}
                name = recipient.get("global_name") or recipient.get("username") or f"DM {ch_id}"
                handle = recipient.get("username", "")
                return True, {
                    "id": ch_id,
                    "name": name,
                    "handle": f"@{handle} (Channel ID: {ch_id})",
                    "type": "dm",
                    "type_name": "Direct Message",
                    "avatar_url": get_user_avatar_url(recipient) if recipient else None
                }, None
            elif ch_type == 3:
                name = ch.get("name") or "Group Chat"
                return True, {
                    "id": ch_id,
                    "name": name,
                    "handle": f"Group (ID: {ch_id})",
                    "type": "group",
                    "type_name": "Group DM",
                    "avatar_url": None
                }, None
            else:
                name = "#" + ch.get("name", ch_id)
                return True, {
                    "id": ch_id,
                    "name": name,
                    "handle": f"Server Channel (ID: {ch_id})",
                    "type": "channel",
                    "type_name": "Server Channel",
                    "avatar_url": None
                }, None
        elif ch_res.status_code == 404:
            return False, None, "User or Channel ID not found (404)"
        elif ch_res.status_code == 403:
            return False, None, "Access denied / Cannot message or access this channel (403)"
        else:
            return False, None, f"Discord API HTTP {ch_res.status_code}"
    except requests.exceptions.RequestException as e:
        return False, None, f"Network error: {str(e)}"


# ================= FAVORITE GIFS MANAGEMENT =================

def get_favorite_gifs(token: str) -> Tuple[int, List[dict]]:
    """Fetches favorited GIFs using Discord internal protobuf settings."""
    if not HAS_DISCORD_PROTOS:
        return 0, []

    headers = get_headers(token)
    url = f"{DISCORD_API_BASE}/users/@me/settings-proto/2"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return 0, []
        data = res.json()
        b64_settings = data.get("settings")
        if not b64_settings:
            return 0, []

        proto_bytes = base64.b64decode(b64_settings)
        user_settings = FrecencyUserSettings()
        user_settings.ParseFromString(proto_bytes)

        gifs_dict = user_settings.favorite_gifs.gifs
        gif_list = []
        for url_key, gif_obj in gifs_dict.items():
            gif_list.append({
                "url": url_key,
                "src": gif_obj.src,
                "width": gif_obj.width,
                "height": gif_obj.height,
                "order": gif_obj.order
            })
        return len(gif_list), gif_list
    except Exception:
        return 0, []


def delete_favorite_gifs_advanced(
    token: str,
    keep_mode: str = "all",      # 'all', 'months_3', 'months_1', 'months_6', 'count_10', 'count_25', 'count_50', 'count_100', 'custom_months', 'custom_count'
    custom_val: float = 0
) -> Tuple[bool, int, int, Optional[str]]:
    """
    Clears or filters favorited GIFs from Discord user settings-proto/2 according to retention rules.
    Returns (success, deleted_count, kept_count, error_message).
    """
    if not HAS_DISCORD_PROTOS:
        return False, 0, 0, "discord-protos library not available"

    headers = get_headers(token)
    url = f"{DISCORD_API_BASE}/users/@me/settings-proto/2"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return False, 0, 0, f"Failed to fetch settings: status {res.status_code}"

        data = res.json()
        b64_settings = data.get("settings")
        if not b64_settings:
            return True, 0, 0, None

        proto_bytes = base64.b64decode(b64_settings)
        user_settings = FrecencyUserSettings()
        user_settings.ParseFromString(proto_bytes)

        gifs_dict = user_settings.favorite_gifs.gifs
        total_count = len(gifs_dict)
        if total_count == 0:
            return True, 0, 0, None

        # Sort GIFs by order descending (highest order = most recently added)
        items_sorted = sorted(gifs_dict.items(), key=lambda x: getattr(x[1], "order", 0), reverse=True)

        keys_to_delete = []

        if keep_mode == "all":
            keys_to_delete = [k for k, _ in items_sorted]
        elif keep_mode.startswith("count_"):
            try:
                keep_n = int(keep_mode.split("_")[1])
            except Exception:
                keep_n = 25
            keys_to_delete = [k for k, _ in items_sorted[keep_n:]]
        elif keep_mode == "custom_count":
            keep_n = max(0, int(custom_val))
            keys_to_delete = [k for k, _ in items_sorted[keep_n:]]
        elif keep_mode in ("months_1", "months_3", "months_6", "custom_months"):
            months = 3
            if keep_mode == "months_1":
                months = 1
            elif keep_mode == "months_6":
                months = 6
            elif keep_mode == "custom_months":
                months = max(0.1, float(custom_val))

            # If order is a millisecond timestamp (> 1_000_000_000_000)
            now_ts_ms = time.time() * 1000.0
            cutoff_ms = now_ts_ms - (months * 30.4 * 86400.0 * 1000.0)

            # Check if order appears to be timestamp
            has_timestamp_orders = any(getattr(obj, "order", 0) > 1_000_000_000_000 for _, obj in items_sorted)
            if has_timestamp_orders:
                for k, obj in items_sorted:
                    if getattr(obj, "order", 0) < cutoff_ms:
                        keys_to_delete.append(k)
            else:
                # If sequential, retain top proportion or default count
                keep_ratio = max(0.05, 1.0 - min(1.0, (months / 12.0)))
                keep_n = max(5, int(total_count * keep_ratio))
                keys_to_delete = [k for k, _ in items_sorted[keep_n:]]

        deleted_count = len(keys_to_delete)
        kept_count = total_count - deleted_count

        if deleted_count == 0:
            return True, 0, total_count, None

        # Remove keys from map
        for k in keys_to_delete:
            del gifs_dict[k]

        # Re-encode & patch
        updated_bytes = user_settings.SerializeToString()
        updated_b64 = base64.b64encode(updated_bytes).decode("utf-8")

        patch_res = requests.patch(
            url,
            headers=headers,
            json={"settings": updated_b64},
            timeout=10
        )
        if patch_res.status_code in (200, 204):
            return True, deleted_count, kept_count, None
        else:
            return False, 0, 0, f"Failed to update settings: status {patch_res.status_code}"
    except Exception as e:
        return False, 0, 0, str(e)


def delete_all_favorite_gifs(token: str) -> Tuple[bool, int, Optional[str]]:
    """Backward-compatible helper to clear all favorite GIFs."""
    ok, deleted, _, err = delete_favorite_gifs_advanced(token, keep_mode="all")
    return ok, deleted, err


# ================= MESSAGE PURGER WORKER =================

class MessagePurgerWorker(threading.Thread):
    """Background worker that crawls messages and deletes the user's messages."""
    def __init__(
        self,
        token: str,
        channel_id: str,
        channel_name: str,
        user_id: str,
        filter_type: str = "all",       # 'all', 'photos', 'gifs', 'normal'
        time_limit_seconds: Optional[int] = None,
        delay: float = 0.15,
        random_delay: bool = False,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
        on_log: Optional[Callable[[str, str], None]] = None,
        on_progress: Optional[Callable[[int, int, int, int, int, str], None]] = None,
        on_finished: Optional[Callable[[dict], None]] = None,
        on_stopped: Optional[Callable[[], None]] = None,
        silent_empty: bool = False
    ):
        super().__init__(daemon=True)
        self.token = token
        self.channel_id = str(channel_id)
        self.channel_name = channel_name
        self.user_id = str(user_id)
        self.filter_type = filter_type
        self.time_limit_seconds = time_limit_seconds
        self.delay = max(0.0, float(delay))
        self.random_delay = random_delay
        self.min_delay = max(0.1, float(min_delay))
        self.max_delay = max(self.min_delay, float(max_delay))
        self.silent_empty = silent_empty

        self.on_log = on_log
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.on_stopped = on_stopped

        self.stop_requested = False
        self.headers = get_headers(token)
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        self.scanned_count = 0
        self.deleted_count = 0
        self.skipped_count = 0
        self.error_count = 0
        self.rate_limit_count = 0
        self.start_time = None

    def stop(self):
        self.stop_requested = True

    def log(self, tag: str, message: str):
        if self.on_log:
            self.on_log(tag, message)

    def update_progress(self):
        if self.on_progress:
            elapsed = time.time() - self.start_time if self.start_time else 0
            mins, secs = divmod(int(elapsed), 60)
            elapsed_str = f"{mins:02d}:{secs:02d}"
            self.on_progress(
                self.scanned_count,
                self.deleted_count,
                self.skipped_count,
                self.error_count,
                self.rate_limit_count,
                elapsed_str
            )

    @staticmethod
    def get_snowflake_time(snowflake_id: str) -> datetime.datetime:
        ts_ms = (int(snowflake_id) >> 22) + 1420070400000
        return datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)

    @staticmethod
    def is_photo(msg: dict) -> bool:
        attachments = msg.get("attachments", [])
        if not attachments:
            return False
        photo_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        for att in attachments:
            ct = att.get("content_type", "").lower()
            fn = att.get("filename", "").lower()
            if (ct.startswith("image/") and not ct.endswith("gif")) or any(fn.endswith(ext) for ext in photo_exts):
                return True
        return False

    @staticmethod
    def is_gif(msg: dict) -> bool:
        for att in msg.get("attachments", []):
            ct = att.get("content_type", "").lower()
            fn = att.get("filename", "").lower()
            if "gif" in ct or fn.endswith(".gif"):
                return True
        for emb in msg.get("embeds", []):
            emb_type = emb.get("type", "")
            if emb_type in ("gifv", "image") and "gif" in str(emb.get("video") or emb.get("image") or ""):
                return True
        content = msg.get("content", "").lower()
        if re.search(r"tenor\.com/view|giphy\.com/gifs|\.gif(\?|$)", content):
            return True
        return False

    @staticmethod
    def is_normal_text(msg: dict) -> bool:
        if MessagePurgerWorker.is_photo(msg) or MessagePurgerWorker.is_gif(msg):
            return False
        return True

    def matches_filter(self, msg: dict) -> bool:
        if self.filter_type == "all":
            return True
        elif self.filter_type == "photos":
            return self.is_photo(msg)
        elif self.filter_type == "gifs":
            return self.is_gif(msg)
        elif self.filter_type == "normal":
            return self.is_normal_text(msg)
        return True

    def run(self):
        self.start_time = time.time()
        if not self.silent_empty:
            self.log("info", f"Starting purge operation on {self.channel_name} (ID: {self.channel_id})")
            self.log("info", f"Filter: {self.filter_type} | Time Window: {self.time_limit_seconds or 'All Time'}")

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        time_cutoff = None
        if self.time_limit_seconds and self.time_limit_seconds > 0:
            time_cutoff = now_utc - datetime.timedelta(seconds=self.time_limit_seconds)

        before_id = None
        has_more = True

        while has_more and not self.stop_requested:
            url = f"{DISCORD_API_BASE}/channels/{self.channel_id}/messages?limit=100"
            if before_id:
                url += f"&before={before_id}"

            fetch_attempts = 0
            messages = None
            while fetch_attempts < 5 and not self.stop_requested:
                fetch_attempts += 1
                try:
                    res = self.session.get(url, timeout=15)
                    if res.status_code == 200:
                        messages = res.json()
                        break
                    elif res.status_code == 429:
                        self.rate_limit_count += 1
                        self.update_progress()
                        retry_after = float(res.json().get("retry_after", 1.5))
                        self.log("warn", f"Rate limit reached when fetching messages. Sleeping {retry_after:.1f}s...")
                        time.sleep(retry_after + 0.1)
                    elif res.status_code in (403, 404):
                        if not self.silent_empty:
                            self.log("error", f"Channel access error (HTTP {res.status_code}). Check permissions.")
                        self.stop_requested = True
                        break
                    else:
                        if not self.silent_empty:
                            self.log("error", f"Failed to fetch messages (HTTP {res.status_code}).")
                        time.sleep(1.0)
                except requests.exceptions.RequestException as e:
                    if not self.silent_empty:
                        self.log("error", f"Network error when fetching messages: {e}")
                    time.sleep(1.0)

            if self.stop_requested or not messages:
                break

            if len(messages) == 0:
                if not self.silent_empty:
                    self.log("info", "No more messages found in this channel.")
                break

            reached_cutoff = False
            for msg in messages:
                if self.stop_requested:
                    break

                self.scanned_count += 1
                msg_id = msg.get("id")
                msg_author_id = msg.get("author", {}).get("id")

                msg_time = self.get_snowflake_time(msg_id)
                if time_cutoff and msg_time < time_cutoff:
                    if not self.silent_empty:
                        self.log("info", f"Reached time cutoff at message timestamp {msg_time.strftime('%Y-%m-%d %H:%M:%S UTC')}.")
                    reached_cutoff = True
                    break

                if msg_author_id != self.user_id:
                    self.skipped_count += 1
                    self.update_progress()
                    continue

                if not self.matches_filter(msg):
                    self.skipped_count += 1
                    self.update_progress()
                    continue

                content_preview = msg.get("content", "").replace("\n", " ").strip()
                if not content_preview:
                    if msg.get("attachments"):
                        content_preview = f"[{len(msg['attachments'])} attachment(s)]"
                    elif msg.get("embeds"):
                        content_preview = "[Embed/GIF]"
                    else:
                        content_preview = "[Empty message]"
                if len(content_preview) > 40:
                    content_preview = content_preview[:37] + "..."

                del_url = f"{DISCORD_API_BASE}/channels/{self.channel_id}/messages/{msg_id}"
                del_attempts = 0

                while del_attempts < 4 and not self.stop_requested:
                    del_attempts += 1
                    try:
                        del_res = self.session.delete(del_url, timeout=10)
                        if del_res.status_code in (204, 200):
                            self.deleted_count += 1
                            prefix = f"[{self.channel_name}] " if self.silent_empty else ""
                            self.log("delete", f"{prefix}Deleted message #{msg_id} ({msg_time.strftime('%H:%M:%S')}) -> \"{content_preview}\"")
                            self.update_progress()
                            if self.random_delay:
                                r_wait = random.uniform(min(self.min_delay, self.max_delay), max(self.min_delay, self.max_delay))
                                time.sleep(r_wait)
                            elif self.delay > 0:
                                time.sleep(self.delay)
                            break
                        elif del_res.status_code == 429:
                            self.rate_limit_count += 1
                            self.update_progress()
                            retry_after = float(del_res.json().get("retry_after", 1.5))
                            self.log("warn", f"Rate limit on delete. Waiting {retry_after:.2f}s...")
                            time.sleep(retry_after + 0.05)
                        elif del_res.status_code in (404, 403):
                            self.error_count += 1
                            self.log("warn", f"Message #{msg_id} could not be deleted (HTTP {del_res.status_code}).")
                            self.update_progress()
                            break
                        else:
                            self.error_count += 1
                            self.log("error", f"Delete error HTTP {del_res.status_code} for #{msg_id}")
                            self.update_progress()
                            time.sleep(0.5)
                    except requests.exceptions.RequestException as e:
                        self.error_count += 1
                        self.log("error", f"Network exception on delete: {e}")
                        time.sleep(0.5)

            if reached_cutoff or self.stop_requested:
                break

            before_id = messages[-1]["id"]
            self.update_progress()

        try:
            self.session.close()
        except Exception:
            pass

        elapsed = time.time() - self.start_time
        mins, secs = divmod(int(elapsed), 60)
        elapsed_str = f"{mins:02d}:{secs:02d}"

        summary = {
            "scanned": self.scanned_count,
            "deleted": self.deleted_count,
            "skipped": self.skipped_count,
            "errors": self.error_count,
            "rate_limits": self.rate_limit_count,
            "elapsed": elapsed_str,
            "stopped": self.stop_requested
        }

        if self.stop_requested:
            if not self.silent_empty or self.deleted_count > 0:
                self.log("info", f"[{self.channel_name}] Operation stopped by user. Total deleted: {self.deleted_count} | Elapsed: {elapsed_str}")
            if self.on_stopped:
                self.on_stopped()
        else:
            if not self.silent_empty:
                self.log("success", f"Purge completed! Total deleted: {self.deleted_count} | Scanned: {self.scanned_count} | Elapsed: {elapsed_str}")
            elif self.deleted_count > 0:
                self.log("success", f"[{self.channel_name}] Purge completed! Deleted: {self.deleted_count} | Elapsed: {elapsed_str}")
            if self.on_finished:
                self.on_finished(summary)


# ================= ACCOUNT TOOLS WORKERS =================

class FriendNicknameResetWorker(threading.Thread):
    """Resets all custom nicknames set on friends."""
    def __init__(self, token: str, on_log=None, on_progress=None, on_finished=None):
        super().__init__(daemon=True)
        self.token = token
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def log(self, tag: str, msg: str):
        if self.on_log:
            self.on_log(tag, msg)

    def run(self):
        self.log("info", "Starting friend nickname reset operation...")
        headers = get_headers(self.token)
        url = f"{DISCORD_API_BASE}/users/@me/relationships"
        try:
            res = requests.get(url, headers=headers, timeout=12)
            if res.status_code != 200:
                self.log("error", f"Failed to fetch relationships: HTTP {res.status_code}")
                if self.on_finished:
                    self.on_finished(0)
                return
            relationships = res.json()
        except Exception as e:
            self.log("error", f"Error fetching relationships: {e}")
            if self.on_finished:
                self.on_finished(0)
            return

        with_nicks = [
            r for r in relationships
            if r.get("type") == 1 and r.get("nickname") and str(r.get("nickname")).strip()
        ]
        total = len(with_nicks)
        self.log("info", f"Found {total} friend(s) with custom nicknames.")
        reset_count = 0

        for r in with_nicks:
            if self.stop_requested:
                break
            friend_id = r.get("id")
            old_nick = r.get("nickname")
            user_info = r.get("user", {})
            username = user_info.get("global_name") or user_info.get("username") or friend_id

            patch_url = f"{DISCORD_API_BASE}/users/@me/relationships/{friend_id}"
            attempts = 0
            while attempts < 3 and not self.stop_requested:
                attempts += 1
                try:
                    p_res = requests.patch(patch_url, headers=headers, json={"nickname": ""}, timeout=10)
                    if p_res.status_code in (200, 204):
                        reset_count += 1
                        self.log("success", f"Reset nickname for {username} (was: \"{old_nick}\")")
                        if self.on_progress:
                            self.on_progress(reset_count, total)
                        time.sleep(0.3)
                        break
                    elif p_res.status_code == 429:
                        wait = float(p_res.json().get("retry_after", 1.5))
                        self.log("warn", f"Rate limit. Waiting {wait:.1f}s...")
                        time.sleep(wait + 0.1)
                    else:
                        self.log("error", f"Failed reset for {username}: HTTP {p_res.status_code}")
                        break
                except Exception as e:
                    self.log("error", f"Network error resetting {username}: {e}")
                    time.sleep(0.5)

        self.log("success", f"Nickname reset finished. Reset {reset_count} nickname(s).")
        if self.on_finished:
            self.on_finished(reset_count)


class MassLeaveGuildsWorker(threading.Thread):
    """Leaves all joined servers (safely skips servers owned by user)."""
    def __init__(self, token: str, on_log=None, on_progress=None, on_finished=None):
        super().__init__(daemon=True)
        self.token = token
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def log(self, tag: str, msg: str):
        if self.on_log:
            self.on_log(tag, msg)

    def run(self):
        self.log("info", "Starting mass server leave operation...")
        headers = get_headers(self.token)
        guilds = get_guilds(self.token)
        total = len(guilds)
        self.log("info", f"Found {total} server(s) joined.")

        left_count = 0
        skipped_count = 0

        for g in guilds:
            if self.stop_requested:
                self.log("warn", "Mass server leave operation stopped by user.")
                break
            g_id = g.get("id")
            g_name = g.get("name", "Unknown Server")
            is_owner = g.get("owner", False)

            if is_owner:
                skipped_count += 1
                self.log("warn", f"[SKIPPED] Server '{g_name}' is owned by you. Cannot leave without transferring ownership.")
                continue

            del_url = f"{DISCORD_API_BASE}/users/@me/guilds/{g_id}"
            attempts = 0
            while attempts < 3 and not self.stop_requested:
                attempts += 1
                try:
                    # Discord user client sends {"lurking": False}
                    res = requests.delete(del_url, headers=headers, json={"lurking": False}, timeout=10)
                    if res.status_code in (200, 204):
                        left_count += 1
                        self.log("delete", f"[LEFT] Left server '{g_name}' (ID: {g_id})")
                        if self.on_progress:
                            self.on_progress(left_count, total)
                        time.sleep(0.35)
                        break
                    elif res.status_code == 400:
                        # Fallback attempt without body if client requires empty delete
                        headers_alt = {k: v for k, v in headers.items() if k.lower() != "content-type"}
                        res2 = requests.delete(del_url, headers=headers_alt, timeout=10)
                        if res2.status_code in (200, 204):
                            left_count += 1
                            self.log("delete", f"[LEFT] Left server '{g_name}' (ID: {g_id})")
                            if self.on_progress:
                                self.on_progress(left_count, total)
                            time.sleep(0.35)
                            break
                        err_text = ""
                        try:
                            err_text = f" ({res.json().get('message', '')})"
                        except Exception:
                            pass
                        self.log("error", f"Failed leaving server '{g_name}': HTTP 400{err_text}")
                        break
                    elif res.status_code == 429:
                        wait = float(res.json().get("retry_after", 1.5))
                        self.log("warn", f"Rate limit leaving server. Waiting {wait:.1f}s...")
                        time.sleep(wait + 0.1)
                    else:
                        err_text = ""
                        try:
                            err_text = f" ({res.json().get('message', '')})"
                        except Exception:
                            pass
                        self.log("error", f"Failed leaving server '{g_name}': HTTP {res.status_code}{err_text}")
                        break
                except Exception as e:
                    self.log("error", f"Network error leaving server '{g_name}': {e}")
                    time.sleep(0.5)

        self.log("success", f"Mass server leave complete! Left: {left_count} | Skipped: {skipped_count}")
        if self.on_finished:
            self.on_finished(left_count, skipped_count)


class MassRemoveFriendsWorker(threading.Thread):
    """Removes all friends from user account."""
    def __init__(self, token: str, on_log=None, on_progress=None, on_finished=None):
        super().__init__(daemon=True)
        self.token = token
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def log(self, tag: str, msg: str):
        if self.on_log:
            self.on_log(tag, msg)

    def run(self):
        self.log("info", "Starting mass friend removal operation...")
        headers = get_headers(self.token)
        url = f"{DISCORD_API_BASE}/users/@me/relationships"
        try:
            res = requests.get(url, headers=headers, timeout=12)
            if res.status_code != 200:
                self.log("error", f"Failed to fetch relationships: HTTP {res.status_code}")
                if self.on_finished:
                    self.on_finished(0)
                return
            relationships = res.json()
        except Exception as e:
            self.log("error", f"Error fetching relationships: {e}")
            if self.on_finished:
                self.on_finished(0)
            return

        friends = [r for r in relationships if r.get("type") == 1]
        total = len(friends)
        self.log("info", f"Found {total} friend(s) to remove.")
        removed_count = 0

        for f in friends:
            if self.stop_requested:
                break
            friend_id = f.get("id")
            user_info = f.get("user", {})
            name = user_info.get("global_name") or user_info.get("username") or friend_id

            del_url = f"{DISCORD_API_BASE}/users/@me/relationships/{friend_id}"
            attempts = 0
            while attempts < 3 and not self.stop_requested:
                attempts += 1
                try:
                    del_res = requests.delete(del_url, headers=headers, timeout=10)
                    if del_res.status_code in (200, 204):
                        removed_count += 1
                        self.log("delete", f"[REMOVED] Removed friend {name} (ID: {friend_id})")
                        if self.on_progress:
                            self.on_progress(removed_count, total)
                        time.sleep(0.35)
                        break
                    elif del_res.status_code == 429:
                        wait = float(del_res.json().get("retry_after", 1.5))
                        self.log("warn", f"Rate limit removing friend. Waiting {wait:.1f}s...")
                        time.sleep(wait + 0.1)
                    else:
                        self.log("error", f"Failed removing friend {name}: HTTP {del_res.status_code}")
                        break
                except Exception as e:
                    self.log("error", f"Network error removing friend {name}: {e}")
                    time.sleep(0.5)

        self.log("success", f"Mass friend removal complete! Removed: {removed_count}")
        if self.on_finished:
            self.on_finished(removed_count)


# ================= AUTO-EDIT / AUTO-DELETE WORKER =================

class AutoEditWorker(threading.Thread):
    """
    Crawls messages across target scope, finds messages containing a specific keyword,
    and either edits/replaces the keyword or deletes the message.
    """
    def __init__(
        self,
        token: str,
        user_id: str,
        search_keyword: str,
        action_mode: str = "replace",  # 'replace' or 'delete'
        match_type: str = "contains",  # 'contains' or 'exact'
        replacement_text: str = "",
        scope: str = "selected",       # 'selected', 'all_dms', 'all_servers'
        target_channel_id: Optional[str] = None,
        target_channel_name: str = "Selected Chat",
        delay: float = 0.20,
        on_log=None,
        on_progress=None,
        on_finished=None
    ):
        super().__init__(daemon=True)
        self.token = token
        self.user_id = str(user_id)
        self.search_keyword = search_keyword.strip()
        self.action_mode = action_mode
        self.match_type = match_type.lower()
        self.replacement_text = replacement_text
        self.scope = scope
        self.target_channel_id = str(target_channel_id) if target_channel_id else None
        self.target_channel_name = target_channel_name
        self.delay = max(0.05, float(delay))

        self.on_log = on_log
        self.on_progress = on_progress
        self.on_finished = on_finished

        self.stop_requested = False
        self.headers = get_headers(token)
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        self.scanned_count = 0
        self.modified_count = 0
        self.start_time = None

    def stop(self):
        self.stop_requested = True

    def log(self, tag: str, msg: str):
        if self.on_log:
            self.on_log(tag, msg)

    def run(self):
        self.start_time = time.time()
        self.log("info", f"Starting Auto-Edit operation | Keyword: \"{self.search_keyword}\" | Mode: {self.action_mode} | Scope: {self.scope}")

        channels_to_scan: List[Tuple[str, str]] = []

        if self.scope == "selected" and self.target_channel_id:
            channels_to_scan.append((self.target_channel_id, self.target_channel_name))
        elif self.scope == "all_dms":
            self.log("info", "Fetching all DM channels...")
            dms = get_dms(self.token)
            for d in dms:
                channels_to_scan.append((d["id"], d["name"]))
        elif self.scope == "all_servers":
            self.log("info", "Fetching all server text channels...")
            guilds = get_guilds(self.token)
            for g in guilds:
                chs = get_guild_channels(self.token, g["id"])
                for c in chs:
                    channels_to_scan.append((c["id"], f"{g['name']} / {c['name']}"))
        elif self.scope == "everywhere":
            dms = get_dms(self.token)
            for d in dms:
                channels_to_scan.append((d["id"], d["name"]))
            guilds = get_guilds(self.token)
            for g in guilds:
                chs = get_guild_channels(self.token, g["id"])
                for c in chs:
                    channels_to_scan.append((c["id"], f"{g['name']} / {c['name']}"))

        self.log("info", f"Total channels queued for Auto-Edit scan: {len(channels_to_scan)}")

        pattern = re.compile(re.escape(self.search_keyword), re.IGNORECASE)

        for ch_id, ch_name in channels_to_scan:
            if self.stop_requested:
                break
            self.log("info", f"Scanning channel: {ch_name} (ID: {ch_id})")
            before_id = None

            while not self.stop_requested:
                url = f"{DISCORD_API_BASE}/channels/{ch_id}/messages?limit=100"
                if before_id:
                    url += f"&before={before_id}"

                try:
                    res = self.session.get(url, timeout=12)
                    if res.status_code == 200:
                        messages = res.json()
                        if not messages:
                            break
                    elif res.status_code == 429:
                        wait = float(res.json().get("retry_after", 1.5))
                        self.log("warn", f"Rate limit on fetch. Waiting {wait:.1f}s...")
                        time.sleep(wait + 0.1)
                        continue
                    else:
                        break
                except Exception:
                    break

                for msg in messages:
                    if self.stop_requested:
                        break
                    self.scanned_count += 1
                    msg_id = msg.get("id")
                    author_id = msg.get("author", {}).get("id")
                    content = msg.get("content", "")

                    if author_id != self.user_id:
                        continue

                    is_match = False
                    if self.match_type == "exact":
                        is_match = (content.strip().lower() == self.search_keyword.lower())
                    else:
                        is_match = bool(pattern.search(content))

                    if is_match:
                        if self.action_mode == "replace":
                            if self.match_type == "exact":
                                new_content = self.replacement_text
                            else:
                                new_content = pattern.sub(self.replacement_text, content)
                            patch_url = f"{DISCORD_API_BASE}/channels/{ch_id}/messages/{msg_id}"
                            try:
                                p_res = self.session.patch(patch_url, json={"content": new_content}, timeout=10)
                                if p_res.status_code in (200, 204):
                                    self.modified_count += 1
                                    self.log("success", f"[EDITED] #{msg_id} in {ch_name} -> \"{new_content[:35]}...\"")
                                    if self.on_progress:
                                        self.on_progress(self.scanned_count, self.modified_count)
                                    time.sleep(self.delay)
                                elif p_res.status_code == 429:
                                    wait = float(p_res.json().get("retry_after", 1.5))
                                    time.sleep(wait + 0.1)
                            except Exception:
                                pass
                        elif self.action_mode == "delete":
                            del_url = f"{DISCORD_API_BASE}/channels/{ch_id}/messages/{msg_id}"
                            try:
                                d_res = self.session.delete(del_url, timeout=10)
                                if d_res.status_code in (200, 204):
                                    self.modified_count += 1
                                    self.log("delete", f"[DELETED] #{msg_id} matching keyword in {ch_name}")
                                    if self.on_progress:
                                        self.on_progress(self.scanned_count, self.modified_count)
                                    time.sleep(self.delay)
                                elif d_res.status_code == 429:
                                    wait = float(d_res.json().get("retry_after", 1.5))
                                    time.sleep(wait + 0.1)
                            except Exception:
                                pass

                before_id = messages[-1]["id"]
                if len(messages) < 100:
                    break

        try:
            self.session.close()
        except Exception:
            pass

        elapsed = time.time() - self.start_time
        mins, secs = divmod(int(elapsed), 60)
        elapsed_str = f"{mins:02d}:{secs:02d}"

        self.log("success", f"Auto-Edit completed! Scanned: {self.scanned_count} | Modified/Deleted: {self.modified_count} | Elapsed: {elapsed_str}")
        if self.on_finished:
            self.on_finished({
                "scanned": self.scanned_count,
                "modified": self.modified_count,
                "elapsed": elapsed_str
            })


# ================= SELF-DESTRUCT MANAGER =================

class SelfDestructManager:
    """Manages active self-destruct countdown timer and triggers timed message purge."""
    def __init__(
        self,
        token: str,
        user_id: str,
        on_log=None,
        on_tick=None,
        on_complete=None,
        on_purge_start=None,
        on_purge_stop=None
    ):
        self.token = token
        self.user_id = str(user_id)
        self.on_log = on_log
        self.on_tick = on_tick
        self.on_complete = on_complete
        self.on_purge_start = on_purge_start
        self.on_purge_stop = on_purge_stop

        self.is_armed = False
        self.is_purging = False
        self.arm_timestamp = 0
        self.duration_seconds = 0
        self.target_scope = "selected"  # 'selected', 'all_dms', 'all_servers', 'everywhere'
        self.target_channel_id = None
        self.target_channel_name = ""
        self.purge_mode = "since_armed" # 'since_armed', 'last_1h', 'last_24h', 'all'
        self._timer_thread: Optional[threading.Thread] = None
        self._purge_thread: Optional[threading.Thread] = None
        self._cancel_flag = False
        self._stop_requested = False
        self._current_worker: Optional[MessagePurgerWorker] = None

    def arm(
        self,
        duration_seconds: int,
        scope: str,
        channel_id: Optional[str] = None,
        channel_name: str = "",
        purge_mode: str = "since_armed"
    ):
        self.duration_seconds = max(1, duration_seconds)
        self.target_scope = scope
        self.target_channel_id = channel_id
        self.target_channel_name = channel_name
        self.purge_mode = purge_mode
        self.arm_timestamp = time.time()
        self.is_armed = True
        self.is_purging = False
        self._cancel_flag = False
        self._stop_requested = False

        if self.on_log:
            self.on_log("warn", f"🚀 Self-Destruct ARMED! Timer: {self.duration_seconds}s | Scope: {self.target_scope} | Window: {self.purge_mode}")

        self._timer_thread = threading.Thread(target=self._countdown_loop, daemon=True)
        self._timer_thread.start()

    def cancel(self):
        """Cancels countdown or halts an ongoing purge."""
        self._cancel_flag = True
        self._stop_requested = True

        if self.is_armed:
            self.is_armed = False
            if self.on_log:
                self.on_log("info", "❌ Self-Destruct CANCELLED by user.")
            if self.on_tick:
                self.on_tick(0, "cancelled")

        if self.is_purging:
            if self._current_worker:
                self._current_worker.stop()
            if self.on_log:
                self.on_log("warn", "⏹ Stopping Self-Destruct purge...")

    def detonate_now(self):
        """Immediately triggers the self-destruct purge without waiting."""
        if self.is_armed:
            self._cancel_flag = True
            self.is_armed = False
            if self.on_log:
                self.on_log("delete", "💥 Self-Destruct TRIGGERED IMMEDIATELY!")
            self._start_purge()

    def _countdown_loop(self):
        end_time = self.arm_timestamp + self.duration_seconds
        while not self._cancel_flag:
            now = time.time()
            remaining = int(end_time - now)
            if remaining <= 0:
                break
            mins, secs = divmod(remaining, 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
            else:
                time_str = f"{mins:02d}:{secs:02d}"

            if self.on_tick:
                self.on_tick(remaining, time_str)
            time.sleep(1.0)

        if not self._cancel_flag:
            self.is_armed = False
            if self.on_log:
                self.on_log("delete", "⏱ Self-Destruct timer expired! Detonating...")
            self._start_purge()

    def _start_purge(self):
        self.is_purging = True
        self._stop_requested = False
        if self.on_purge_start:
            self.on_purge_start()
        self._purge_thread = threading.Thread(target=self._execute_purge, daemon=True)
        self._purge_thread.start()

    def _execute_purge(self):
        total_deleted = 0
        was_stopped = False
        try:
            # 1. Determine time cutoff and min_snowflake
            if self.purge_mode == "last_1h":
                time_limit_seconds = 3600
            elif self.purge_mode == "last_24h":
                time_limit_seconds = 86400
            elif self.purge_mode == "all":
                time_limit_seconds = None
            else: # "since_armed"
                time_limit_seconds = max(10, int(time.time() - self.arm_timestamp) + 15)

            min_snowflake = 0
            if time_limit_seconds:
                cutoff_ts = (time.time() - time_limit_seconds) - 5
                min_snowflake = (int(cutoff_ts * 1000) - 1420070400000) << 22

            channels_to_scan: List[Tuple[str, str]] = []

            # 2. Gather candidate channels with smart activity filtering
            if self.target_scope == "selected" and self.target_channel_id:
                channels_to_scan.append((self.target_channel_id, self.target_channel_name or "Selected Chat"))

            elif self.target_scope in ("all_dms", "everywhere"):
                dms = get_dms(self.token)
                for d in dms:
                    if self._stop_requested:
                        break
                    last_id = d.get("last_message_id", 0)
                    if min_snowflake > 0 and last_id < min_snowflake:
                        continue
                    channels_to_scan.append((d["id"], d["name"]))

            if self.target_scope in ("all_servers", "everywhere"):
                guilds = get_guilds(self.token)
                for g in guilds:
                    if self._stop_requested:
                        break
                    chs = get_guild_channels(self.token, g["id"])
                    for c in chs:
                        last_id = c.get("last_message_id", 0)
                        if min_snowflake > 0 and last_id < min_snowflake:
                            continue
                        channels_to_scan.append((c["id"], f"{g['name']} / {c['name']}"))

            if self._stop_requested:
                was_stopped = True
                return

            if not channels_to_scan:
                if self.on_log:
                    self.on_log("info", "No messages found in the selected time window to purge.")
                if self.on_complete:
                    self.on_complete(0, stopped=False)
                return

            if self.on_log:
                self.on_log("warn", f"💥 Self-Destruct purge active across {len(channels_to_scan)} relevant channel(s)...")

            # 3. Purge matching channels
            for ch_id, ch_name in channels_to_scan:
                if self._stop_requested:
                    was_stopped = True
                    break

                worker = MessagePurgerWorker(
                    token=self.token,
                    channel_id=ch_id,
                    channel_name=ch_name,
                    user_id=self.user_id,
                    filter_type="all",
                    time_limit_seconds=time_limit_seconds,
                    delay=0.15,
                    on_log=self.on_log,
                    silent_empty=True
                )
                self._current_worker = worker
                worker.run()
                total_deleted += worker.deleted_count
                self._current_worker = None

                if self._stop_requested or worker.stop_requested:
                    was_stopped = True
                    break

            if was_stopped:
                if self.on_log:
                    self.on_log("warn", f"⏹ Self-Destruct purge stopped by user! Total messages deleted: {total_deleted}")
                if self.on_purge_stop:
                    self.on_purge_stop(total_deleted)
                elif self.on_complete:
                    self.on_complete(total_deleted, stopped=True)
            else:
                if self.on_log:
                    self.on_log("success", f"💥 Self-Destruct purge finished! Total messages deleted: {total_deleted}")
                if self.on_complete:
                    self.on_complete(total_deleted, stopped=False)

        except Exception as e:
            if self.on_log:
                self.on_log("error", f"Self-Destruct execution error: {e}")
            if self.on_complete:
                self.on_complete(total_deleted, stopped=False)
        finally:
            self.is_purging = False
            self._current_worker = None
