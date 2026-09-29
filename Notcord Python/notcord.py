"""
Notcord - Discord Message, Media & Account Manager
Created by Qorelith - v2.2.0
A modern, Discord-inspired desktop application built with CustomTkinter.
"""

import datetime
import json
import os
import sys
import threading
import time
import webbrowser
from typing import Dict, List, Optional
from PIL import Image, ImageTk

import customtkinter as ctk

from discord_engine import (
    AvatarCache,
    AutoEditWorker,
    FriendNicknameResetWorker,
    MassLeaveGuildsWorker,
    MassRemoveFriendsWorker,
    MessagePurgerWorker,
    SelfDestructManager,
    delete_favorite_gifs_advanced,
    find_local_discord_sessions,
    get_dms,
    get_favorite_gifs,
    get_guild_channels,
    get_guilds,
    get_user_avatar_url,
    resolve_target_by_id,
    verify_token,
)
from i18n import i18n

CONFIG_FILE = "config.json"

# UI Color Palette (Discord Dark & Notcord Red Theme)
BG_MAIN = "#1E1F22"         # Discord app background
BG_RAIL = "#141517"         # Leftmost rail
BG_SIDEBAR = "#2B2D31"      # Channel / DM sidebar
BG_CARD = "#232428"         # Card / Container background
BG_CARD_HOVER = "#2D2F34"
BG_CARD_ACTIVE = "#35373C"
BG_CONSOLE = "#111214"      # Monospace terminal dark
RED_ACCENT = "#ED4245"      # Discord red / Notcord brand red
RED_HOVER = "#DA373C"       # Darker red for button hover
RED_SUBTLE = "#3C1E20"      # Subtle red tint
BLURPLE = "#5865F2"         # Discord blurple
BLURPLE_HOVER = "#4752C4"
TEXT_LIGHT = "#F2F3F5"      # High contrast off-white
TEXT_MUTED = "#949BA4"      # Muted secondary text
BORDER_COLOR = "#383A40"    # Subtle border line
GREEN_ACCENT = "#57F287"    # Discord green
YELLOW_ACCENT = "#FEE75C"   # Discord yellow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class NotcordApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"Notcord {i18n.t('version_badge')} - {i18n.t('credit')}")
        self.geometry("1140x720")
        self.minsize(980, 620)
        self.configure(fg_color=BG_MAIN)

        # App state
        self.token = ""
        self.user_data: Optional[dict] = None
        self.current_tab = "dms"  # 'dms', 'servers'
        self.current_category = "purge"  # 'purge', 'self_destruct', 'auto_edit', 'account', 'gifs'
        self.dms_list: List[dict] = []
        self.guilds_list: List[dict] = []
        self.selected_target: Optional[dict] = None
        self.active_worker: Optional[threading.Thread] = None
        self.self_destruct_mgr: Optional[SelfDestructManager] = None

        # Persistent Image References to prevent Tkinter / CustomTkinter GC destruction
        self._avatar_refs: Dict[any, ctk.CTkImage] = {}
        self._user_avatar_ctk: Optional[ctk.CTkImage] = None
        self._target_avatar_ctk: Optional[ctk.CTkImage] = None
        self.instagram_icon_img: Optional[ctk.CTkImage] = None
        self.discord_icon_img: Optional[ctk.CTkImage] = None
        self.youtube_icon_img: Optional[ctk.CTkImage] = None
        self.tiktok_icon_img: Optional[ctk.CTkImage] = None
        self.github_icon_img: Optional[ctk.CTkImage] = None

        # Clean session avatar cache on launch
        AvatarCache.clear_disk_cache()

        # Load configuration
        self.config_data = self.load_config()
        saved_lang = self.config_data.get("language", "en")
        i18n.set_language(saved_lang)
        i18n.add_listener(self.on_language_changed)

        # Assets & Window Icon
        self.logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
        self.icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.ico")
        self._icon_photo: Optional[ImageTk.PhotoImage] = None
        self._init_app_icon()

        self.logo_img_32 = None
        self.logo_img_80 = None
        self.load_images()

        # Build Interface
        self.setup_layout()

        # Register close handler for instant token wipe & cache deletion
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _init_app_icon(self):
        if os.path.exists(self.logo_path):
            try:
                pil_icon = Image.open(self.logo_path)
                self._icon_photo = ImageTk.PhotoImage(pil_icon.resize((64, 64), Image.LANCZOS))
            except Exception:
                self._icon_photo = None
        self._apply_window_icon(self)

    def _apply_window_icon(self, window):
        if os.path.exists(self.icon_path):
            try:
                window.iconbitmap(self.icon_path)
            except Exception:
                pass
        if hasattr(self, "_icon_photo") and self._icon_photo:
            try:
                window.wm_iconphoto(True, self._icon_photo)
            except Exception:
                pass

    def load_config(self) -> dict:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    cfg.pop("token", None)  # Ensure no persistent token
                    return cfg
            except Exception:
                pass
        return {"language": "en", "delay": 0.15, "sidebar_width": 240, "random_delay": False, "min_delay": 0.5, "max_delay": 2.0}

    def save_config(self):
        try:
            to_save = dict(self.config_data)
            to_save.pop("token", None)  # Strictly never write token to disk
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=2)
        except Exception:
            pass

    def on_closing(self):
        """Immediately resets token in RAM, wipes disk cache, and terminates."""
        try:
            if self.active_worker and hasattr(self.active_worker, "stop"):
                self.active_worker.stop()
            if self.self_destruct_mgr:
                self.self_destruct_mgr.cancel()
        except Exception:
            pass
        self.token = ""
        self.user_data = None
        AvatarCache.clear_disk_cache()
        self.destroy()

    def load_images(self):
        if os.path.exists(self.logo_path):
            try:
                pil_logo = Image.open(self.logo_path)
                self.logo_img_32 = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(28, 28))
                self.logo_img_80 = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(80, 80))
            except Exception as e:
                print(f"Error loading logo: {e}")

        # Load social / branding icons
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        ig_path = os.path.join(assets_dir, "instagram.png")
        dc_path = os.path.join(assets_dir, "discord.png")
        yt_path = os.path.join(assets_dir, "youtube.png")
        tt_path = os.path.join(assets_dir, "tiktok.png")
        gh_path = os.path.join(assets_dir, "github.png")

        if os.path.exists(ig_path):
            try:
                self.instagram_icon_img = ctk.CTkImage(light_image=Image.open(ig_path), dark_image=Image.open(ig_path), size=(26, 26))
            except Exception:
                pass
        if os.path.exists(dc_path):
            try:
                self.discord_icon_img = ctk.CTkImage(light_image=Image.open(dc_path), dark_image=Image.open(dc_path), size=(26, 26))
            except Exception:
                pass
        if os.path.exists(yt_path):
            try:
                self.youtube_icon_img = ctk.CTkImage(light_image=Image.open(yt_path), dark_image=Image.open(yt_path), size=(26, 26))
            except Exception:
                pass
        if os.path.exists(tt_path):
            try:
                self.tiktok_icon_img = ctk.CTkImage(light_image=Image.open(tt_path), dark_image=Image.open(tt_path), size=(26, 26))
            except Exception:
                pass
        if os.path.exists(gh_path):
            try:
                self.github_icon_img = ctk.CTkImage(light_image=Image.open(gh_path), dark_image=Image.open(gh_path), size=(26, 26))
            except Exception:
                pass

    def safe_ui(self, func, *args, **kwargs):
        """Dispatches GUI calls thread-safely."""
        self.after(0, lambda: func(*args, **kwargs))

    # ================= UI SETUP =================

    def setup_layout(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. Top Header Bar
        self.setup_header()

        # 2. Main Body (Rail, Sub-Sidebar, Workspace)
        self.body_frame = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        self.body_frame.grid(row=1, column=0, sticky="nsew")
        self.body_frame.grid_rowconfigure(0, weight=1)
        self.body_frame.grid_columnconfigure(2, weight=1)

        # Left Rail
        self.setup_left_rail()

        # Sub-Sidebar (DMs / Servers)
        self.setup_sub_sidebar()

        # Workspace
        self.setup_workspace()

    def setup_header(self):
        self.header_frame = ctk.CTkFrame(self, fg_color=BG_RAIL, height=52, corner_radius=0)
        self.header_frame.grid(row=0, column=0, sticky="ew")
        self.header_frame.grid_columnconfigure(2, weight=1)

        # Left: App Logo, Title & v2.2 Badge
        title_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_box.grid(row=0, column=0, padx=(14, 8), pady=8, sticky="w")

        if self.logo_img_32:
            self.logo_label = ctk.CTkLabel(title_box, text="", image=self.logo_img_32)
            self.logo_label.pack(side="left", padx=(0, 8))

        self.lbl_app_title = ctk.CTkLabel(
            title_box,
            text="Notcord",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=TEXT_LIGHT
        )
        self.lbl_app_title.pack(side="left")

        self.badge_version = ctk.CTkLabel(
            title_box,
            text=i18n.t("version_badge"),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=RED_ACCENT,
            fg_color=RED_SUBTLE,
            corner_radius=6,
            padx=7,
            pady=2
        )
        self.badge_version.pack(side="left", padx=(8, 0))

        # Center Left: Creator Badge & Links Button
        credit_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        credit_box.grid(row=0, column=1, padx=12, sticky="w")

        self.credit_badge = ctk.CTkLabel(
            credit_box,
            text=f"★ {i18n.t('credit')} ★",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#FF6B6B",
            fg_color="#2B1416",
            corner_radius=12,
            padx=12,
            pady=4
        )
        self.credit_badge.pack(side="left", padx=(0, 8))

        # Links Button
        self.btn_links = ctk.CTkButton(
            credit_box,
            text=i18n.t("links_btn"),
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=BLURPLE,
            hover_color=BLURPLE_HOVER,
            corner_radius=8,
            height=30,
            command=self.open_links_modal
        )
        self.btn_links.pack(side="left")

        # Right Controls: Sidebar Width Selector, Language Switcher, Status Dot
        ctrl_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        ctrl_box.grid(row=0, column=3, padx=14, pady=8, sticky="e")

        # 5-Language Selector Dropdown
        current_display = i18n.get_display_name(i18n.current_lang)
        self.lang_menu = ctk.CTkOptionMenu(
            ctrl_box,
            values=i18n.get_supported_languages(),
            command=self.on_lang_menu_selected,
            fg_color=BG_SIDEBAR,
            button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER,
            corner_radius=6,
            width=135,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.lang_menu.set(current_display)
        self.lang_menu.pack(side="right", padx=(8, 0))

        self.lbl_lang = ctk.CTkLabel(
            ctrl_box,
            text=i18n.t("language") + ":",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED
        )
        self.lbl_lang.pack(side="right", padx=(0, 4))

        # Sidebar Width Selector Dropdown
        self.width_menu = ctk.CTkOptionMenu(
            ctrl_box,
            values=[i18n.t("width_compact"), i18n.t("width_normal"), i18n.t("width_wide")],
            command=self.on_sidebar_width_changed,
            fg_color=BG_SIDEBAR,
            button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER,
            corner_radius=6,
            width=125,
            height=28,
            font=ctk.CTkFont(size=11)
        )
        saved_width = self.config_data.get("sidebar_width", 240)
        if saved_width <= 220:
            self.width_menu.set(i18n.t("width_compact"))
        elif saved_width >= 260:
            self.width_menu.set(i18n.t("width_wide"))
        else:
            self.width_menu.set(i18n.t("width_normal"))
        self.width_menu.pack(side="right", padx=(14, 10))

        self.lbl_width = ctk.CTkLabel(
            ctrl_box,
            text=i18n.t("sidebar_width") + ":",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED
        )
        self.lbl_width.pack(side="right", padx=(0, 4))

        # Status Dot & Text
        self.status_dot = ctk.CTkLabel(
            ctrl_box,
            text="●",
            font=ctk.CTkFont(size=14),
            text_color=TEXT_MUTED
        )
        self.status_dot.pack(side="right", padx=(14, 4))

        self.status_text = ctk.CTkLabel(
            ctrl_box,
            text=i18n.t("status_ready"),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED
        )
        self.status_text.pack(side="right", padx=(0, 8))

    def setup_left_rail(self):
        """The Discord vertical left rail."""
        self.rail_frame = ctk.CTkFrame(self.body_frame, fg_color=BG_RAIL, width=60, corner_radius=0)
        self.rail_frame.grid(row=0, column=0, sticky="nsew")
        self.rail_frame.grid_propagate(False)

        # DMs Nav Tab
        self.btn_rail_dms = ctk.CTkButton(
            self.rail_frame,
            text="💬",
            width=44,
            height=44,
            corner_radius=22,
            fg_color=RED_ACCENT,
            hover_color=RED_HOVER,
            font=ctk.CTkFont(size=19),
            command=lambda: self.switch_nav_tab("dms")
        )
        self.btn_rail_dms.pack(pady=(12, 6), padx=8)

        # Separator line
        sep = ctk.CTkFrame(self.rail_frame, height=2, fg_color=BORDER_COLOR)
        sep.pack(fill="x", padx=14, pady=6)

        # Servers Nav Tab
        self.btn_rail_servers = ctk.CTkButton(
            self.rail_frame,
            text="🏰",
            width=44,
            height=44,
            corner_radius=22,
            fg_color=BG_CARD,
            hover_color=RED_HOVER,
            font=ctk.CTkFont(size=19),
            command=lambda: self.switch_nav_tab("servers")
        )
        self.btn_rail_servers.pack(pady=6, padx=8)

    def setup_sub_sidebar(self):
        """Channel / DM list panel with resizable width."""
        initial_width = self.config_data.get("sidebar_width", 240)
        self.sidebar_frame = ctk.CTkFrame(self.body_frame, fg_color=BG_SIDEBAR, width=initial_width, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=1, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        self.sidebar_frame.grid_rowconfigure(2, weight=1)
        self.sidebar_frame.grid_columnconfigure(0, weight=1)

        # Header of sidebar
        self.sidebar_header = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent", height=40)
        self.sidebar_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        self.sidebar_header.grid_columnconfigure(0, weight=1)

        self.lbl_sidebar_title = ctk.CTkLabel(
            self.sidebar_header,
            text=i18n.t("tab_dms"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_LIGHT
        )
        self.lbl_sidebar_title.grid(row=0, column=0, sticky="w")

        self.btn_add_id = ctk.CTkButton(
            self.sidebar_header,
            text=i18n.t("btn_add_by_id"),
            width=80,
            height=26,
            corner_radius=6,
            fg_color=RED_SUBTLE,
            text_color=RED_ACCENT,
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.open_id_target_modal
        )
        self.btn_add_id.grid(row=0, column=1, sticky="e", padx=(0, 4))

        self.btn_refresh = ctk.CTkButton(
            self.sidebar_header,
            text="↻",
            width=26,
            height=26,
            corner_radius=6,
            fg_color=BG_CARD,
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.refresh_current_list
        )
        self.btn_refresh.grid(row=0, column=2, sticky="e")

        # Search box
        self.search_entry = ctk.CTkEntry(
            self.sidebar_frame,
            placeholder_text=i18n.t("search_dms_placeholder"),
            height=30,
            corner_radius=6,
            fg_color=BG_RAIL,
            border_color=BORDER_COLOR,
            text_color=TEXT_LIGHT,
            font=ctk.CTkFont(size=12)
        )
        self.search_entry.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 6))
        self.search_entry.bind("<KeyRelease>", lambda e: self.filter_sidebar_items())

        # Scrollable list of items
        self.items_scroll = ctk.CTkScrollableFrame(
            self.sidebar_frame,
            fg_color="transparent",
            corner_radius=0
        )
        self.items_scroll.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)

        # User Profile Footer Card
        self.user_footer = ctk.CTkFrame(self.sidebar_frame, fg_color=BG_RAIL, height=54, corner_radius=0)
        self.user_footer.grid(row=3, column=0, sticky="ew")
        self.user_footer.grid_columnconfigure(1, weight=1)

        self.lbl_user_avatar = ctk.CTkLabel(
            self.user_footer,
            text="👤",
            width=36,
            height=36,
            corner_radius=18,
            fg_color=BG_CARD,
            font=ctk.CTkFont(size=15)
        )
        self.lbl_user_avatar.grid(row=0, column=0, padx=(8, 6), pady=8)

        user_meta_box = ctk.CTkFrame(self.user_footer, fg_color="transparent")
        user_meta_box.grid(row=0, column=1, sticky="w", pady=6)

        self.lbl_user_name = ctk.CTkLabel(
            user_meta_box,
            text=i18n.t("connecting"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_LIGHT,
            anchor="w"
        )
        self.lbl_user_name.pack(anchor="w")

        self.lbl_user_handle = ctk.CTkLabel(
            user_meta_box,
            text="Not logged in",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
            anchor="w"
        )
        self.lbl_user_handle.pack(anchor="w")

        self.btn_logout = ctk.CTkButton(
            self.user_footer,
            text="✕",
            width=26,
            height=26,
            corner_radius=6,
            fg_color="transparent",
            hover_color=RED_SUBTLE,
            text_color=RED_ACCENT,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.do_logout
        )
        self.btn_logout.grid(row=0, column=2, padx=(0, 8))

    def setup_workspace(self):
        """Right workspace containing login screen or categorized tools & console."""
        self.workspace_frame = ctk.CTkFrame(self.body_frame, fg_color=BG_MAIN, corner_radius=0)
        self.workspace_frame.grid(row=0, column=2, sticky="nsew")
        self.workspace_frame.grid_rowconfigure(0, weight=1)
        self.workspace_frame.grid_columnconfigure(0, weight=1)

        # Login View
        self.login_view = ctk.CTkFrame(self.workspace_frame, fg_color=BG_MAIN)
        self.setup_login_view()

        # Main View
        self.main_view = ctk.CTkFrame(self.workspace_frame, fg_color=BG_MAIN)
        self.setup_main_view()

        self.show_view("login")

    def show_view(self, view_name: str):
        if view_name == "login":
            self.main_view.grid_forget()
            self.login_view.grid(row=0, column=0, sticky="nsew")
        else:
            self.login_view.grid_forget()
            self.main_view.grid(row=0, column=0, sticky="nsew")

    # ================= LOGIN VIEW =================

    def setup_login_view(self):
        self.login_view.grid_rowconfigure(0, weight=1)
        self.login_view.grid_columnconfigure(0, weight=1)

        center_card = ctk.CTkFrame(
            self.login_view,
            fg_color=BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=BORDER_COLOR
        )
        center_card.grid(row=0, column=0, padx=40, pady=40)

        if self.logo_img_80:
            lbl_logo = ctk.CTkLabel(center_card, text="", image=self.logo_img_80)
            lbl_logo.pack(pady=(28, 8))

        self.lbl_login_title = ctk.CTkLabel(
            center_card,
            text=i18n.t("login_title"),
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=TEXT_LIGHT
        )
        self.lbl_login_title.pack(pady=(0, 4), padx=32)

        self.lbl_login_desc = ctk.CTkLabel(
            center_card,
            text=i18n.t("login_desc"),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            wraplength=460,
            justify="center"
        )
        self.lbl_login_desc.pack(pady=(0, 24), padx=32)

        self.btn_connect_discord = ctk.CTkButton(
            center_card,
            text=i18n.t("btn_connect_discord"),
            height=46,
            corner_radius=8,
            fg_color=BLURPLE,
            hover_color=BLURPLE_HOVER,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.do_auto_detect_discord
        )
        self.btn_connect_discord.pack(fill="x", padx=32, pady=(0, 14))

        self.lbl_login_status = ctk.CTkLabel(
            center_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=RED_ACCENT,
            wraplength=460,
            justify="center"
        )
        self.lbl_login_status.pack(pady=(0, 12), padx=32)

        sec_box = ctk.CTkFrame(center_card, fg_color=BG_RAIL, corner_radius=8)
        sec_box.pack(fill="x", padx=32, pady=(0, 24))

        self.lbl_token_warning = ctk.CTkLabel(
            sec_box,
            text=i18n.t("token_security_note"),
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
            wraplength=440,
            justify="center"
        )
        self.lbl_token_warning.pack(padx=14, pady=10)

    # ================= MAIN VIEW & CATEGORIES =================

    def setup_main_view(self):
        self.main_view.grid_rowconfigure(3, weight=1)
        self.main_view.grid_columnconfigure(0, weight=1)

        # 1. Selected Chat Header (with Target Avatar)
        self.chat_header = ctk.CTkFrame(self.main_view, fg_color=BG_CARD, height=60, corner_radius=0)
        self.chat_header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        self.chat_header.grid_columnconfigure(1, weight=1)

        self.lbl_target_avatar = ctk.CTkLabel(
            self.chat_header,
            text="#",
            width=40,
            height=40,
            corner_radius=20,
            fg_color=BG_SIDEBAR,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT_LIGHT
        )
        self.lbl_target_avatar.grid(row=0, column=0, padx=10, pady=10)

        target_info = ctk.CTkFrame(self.chat_header, fg_color="transparent")
        target_info.grid(row=0, column=1, sticky="w", pady=8)

        self.lbl_target_name = ctk.CTkLabel(
            target_info,
            text=i18n.t("none_selected"),
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=TEXT_LIGHT,
            anchor="w"
        )
        self.lbl_target_name.pack(anchor="w")

        self.lbl_target_details = ctk.CTkLabel(
            target_info,
            text=i18n.t("select_chat_first"),
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w"
        )
        self.lbl_target_details.pack(anchor="w")

        # 2. Category Navigation Tabs (Professional Top Bar)
        self.CATEGORIES = ["purge", "self_destruct", "auto_edit", "account", "gifs"]
        cat_values = [self.get_category_label(k) for k in self.CATEGORIES]
        self.category_bar = ctk.CTkSegmentedButton(
            self.main_view,
            values=cat_values,
            command=self.on_category_tab_changed,
            selected_color=RED_ACCENT,
            selected_hover_color=RED_HOVER,
            unselected_color=BG_CARD,
            unselected_hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34
        )
        self.category_bar.set(self.get_category_label("purge"))
        self.category_bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 6))

        # 3. Category Panels Container
        self.panel_container = ctk.CTkFrame(self.main_view, fg_color="transparent")
        self.panel_container.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 4))
        self.panel_container.grid_columnconfigure(0, weight=1)

        # Panel 1: Message Purger
        self.panel_purge = ctk.CTkFrame(self.panel_container, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_COLOR)
        self.setup_panel_purge(self.panel_purge)

        # Panel 2: Self-Destruct
        self.panel_self_destruct = ctk.CTkFrame(self.panel_container, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_COLOR)
        self.setup_panel_self_destruct(self.panel_self_destruct)

        # Panel 3: Auto-Edit
        self.panel_auto_edit = ctk.CTkFrame(self.panel_container, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_COLOR)
        self.setup_panel_auto_edit(self.panel_auto_edit)

        # Panel 4: Account Tools
        self.panel_account = ctk.CTkFrame(self.panel_container, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_COLOR)
        self.setup_panel_account(self.panel_account)

        # Panel 5: Favorite GIFs
        self.panel_gifs = ctk.CTkFrame(self.panel_container, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_COLOR)
        self.setup_panel_gifs(self.panel_gifs)

        # Show initial category
        self.show_category("purge")

        # 4. Live Activity Console Box
        self.setup_console(self.main_view)

    def get_category_label(self, cat_key: str) -> str:
        key_map = {
            "purge": "category_purge",
            "self_destruct": "category_self_destruct",
            "auto_edit": "category_auto_edit",
            "account": "category_account",
            "gifs": "category_gifs"
        }
        return i18n.t(key_map.get(cat_key, "category_purge"))

    def get_category_from_label(self, label: str) -> str:
        for k in self.CATEGORIES:
            if self.get_category_label(k) == label:
                return k
        return "purge"

    def on_category_tab_changed(self, value):
        cat_key = self.get_category_from_label(value)
        self.show_category(cat_key)

    def show_category(self, cat_name: str):
        self.current_category = cat_name
        self.panel_purge.grid_forget()
        self.panel_self_destruct.grid_forget()
        self.panel_auto_edit.grid_forget()
        self.panel_account.grid_forget()
        self.panel_gifs.grid_forget()

        if cat_name == "purge":
            self.panel_purge.grid(row=0, column=0, sticky="nsew")
        elif cat_name == "self_destruct":
            self.panel_self_destruct.grid(row=0, column=0, sticky="nsew")
        elif cat_name == "auto_edit":
            self.panel_auto_edit.grid(row=0, column=0, sticky="nsew")
        elif cat_name == "account":
            self.panel_account.grid(row=0, column=0, sticky="nsew")
        elif cat_name == "gifs":
            self.panel_gifs.grid(row=0, column=0, sticky="nsew")

    # ================= 1. PURGE PANEL =================

    def setup_panel_purge(self, card):
        filter_grid = ctk.CTkFrame(card, fg_color="transparent")
        filter_grid.pack(fill="x", padx=14, pady=(10, 4))
        filter_grid.grid_columnconfigure(0, weight=1)
        filter_grid.grid_columnconfigure(1, weight=1)

        # Type Filter
        self.lbl_type_filter = ctk.CTkLabel(filter_grid, text=i18n.t("filter_type_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MUTED)
        self.lbl_type_filter.grid(row=0, column=0, sticky="w", pady=(0, 3))

        self.type_options = [i18n.t("filter_all"), i18n.t("filter_photos"), i18n.t("filter_gifs"), i18n.t("filter_normal")]
        self.menu_type_filter = ctk.CTkOptionMenu(filter_grid, values=self.type_options, fg_color=BG_RAIL, button_color=BG_SIDEBAR, corner_radius=6)
        self.menu_type_filter.set(self.type_options[0])
        self.menu_type_filter.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 6))

        # Time Filter
        self.lbl_time_filter = ctk.CTkLabel(filter_grid, text=i18n.t("filter_time_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MUTED)
        self.lbl_time_filter.grid(row=0, column=1, sticky="w", pady=(0, 3))

        self.time_options = [i18n.t("time_all"), i18n.t("time_1h"), i18n.t("time_6h"), i18n.t("time_24h"), i18n.t("time_7d"), i18n.t("time_30d"), i18n.t("time_custom")]
        self.menu_time_filter = ctk.CTkOptionMenu(filter_grid, values=self.time_options, command=self.on_time_option_changed, fg_color=BG_RAIL, button_color=BG_SIDEBAR, corner_radius=6)
        self.menu_time_filter.set(self.time_options[0])
        self.menu_time_filter.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, 6))

        # Custom Time Row
        self.custom_time_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.lbl_custom_time = ctk.CTkLabel(self.custom_time_frame, text=i18n.t("custom_time_val"), font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.lbl_custom_time.pack(side="left", padx=(0, 6))

        self.custom_time_entry = ctk.CTkEntry(self.custom_time_frame, width=65, height=28, fg_color=BG_RAIL, border_color=BORDER_COLOR)
        self.custom_time_entry.insert(0, "2")
        self.custom_time_entry.pack(side="left", padx=(0, 6))

        self.custom_time_unit = ctk.CTkOptionMenu(self.custom_time_frame, values=[i18n.t("unit_hours"), i18n.t("unit_days")], width=80, height=28, fg_color=BG_RAIL, button_color=BG_SIDEBAR)
        self.custom_time_unit.pack(side="left")

        # Speed Presets
        speed_row = ctk.CTkFrame(card, fg_color="transparent")
        speed_row.pack(fill="x", padx=14, pady=(2, 4))

        self.lbl_speed_preset = ctk.CTkLabel(speed_row, text=i18n.t("speed_mode"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MUTED)
        self.lbl_speed_preset.pack(side="left")

        self.speed_segmented = ctk.CTkSegmentedButton(
            speed_row,
            values=[i18n.t("speed_turbo"), i18n.t("speed_fast"), i18n.t("speed_normal"), i18n.t("speed_safe")],
            command=self.on_speed_preset_selected,
            selected_color=RED_ACCENT,
            selected_hover_color=RED_HOVER,
            unselected_color=BG_RAIL,
            font=ctk.CTkFont(size=10, weight="bold")
        )
        self.speed_segmented.pack(side="right")

        # Delay Slider
        delay_row = ctk.CTkFrame(card, fg_color="transparent")
        delay_row.pack(fill="x", padx=14, pady=(2, 2))

        self.lbl_delay = ctk.CTkLabel(delay_row, text=f"{i18n.t('delay_label')} 0.15s (~6.7 msg/s - ⚡ TURBO)", font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT)
        self.lbl_delay.pack(side="left")

        self.delay_slider = ctk.CTkSlider(card, from_=0.05, to=3.5, number_of_steps=69, progress_color=RED_ACCENT, button_color=RED_ACCENT, button_hover_color=RED_HOVER, command=self.on_delay_slider_changed)
        saved_delay = float(self.config_data.get("delay", 0.15))
        self.delay_slider.set(saved_delay)
        self.delay_slider.pack(fill="x", padx=14, pady=(0, 6))
        self.update_delay_label(saved_delay)

        # Random Cooldown Controls
        rand_box = ctk.CTkFrame(card, fg_color=BG_RAIL, corner_radius=6)
        rand_box.pack(fill="x", padx=14, pady=(2, 8))

        top_rand = ctk.CTkFrame(rand_box, fg_color="transparent")
        top_rand.pack(fill="x", padx=8, pady=(4, 2))

        self.random_delay_switch = ctk.CTkSwitch(
            top_rand,
            text=i18n.t("random_cooldown_label"),
            font=ctk.CTkFont(size=11, weight="bold"),
            progress_color=RED_ACCENT,
            command=self.on_random_delay_toggled
        )
        if self.config_data.get("random_delay", False):
            self.random_delay_switch.select()
        else:
            self.random_delay_switch.deselect()
        self.random_delay_switch.pack(side="left")

        rand_inputs = ctk.CTkFrame(rand_box, fg_color="transparent")
        rand_inputs.pack(fill="x", padx=8, pady=(0, 6))

        ctk.CTkLabel(rand_inputs, text=i18n.t("min_delay_label"), font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.min_delay_entry = ctk.CTkEntry(rand_inputs, width=54, height=26, fg_color=BG_CARD, border_color=BORDER_COLOR)
        self.min_delay_entry.insert(0, str(self.config_data.get("min_delay", 0.5)))
        self.min_delay_entry.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(rand_inputs, text=i18n.t("max_delay_label"), font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.max_delay_entry = ctk.CTkEntry(rand_inputs, width=54, height=26, fg_color=BG_CARD, border_color=BORDER_COLOR)
        self.max_delay_entry.insert(0, str(self.config_data.get("max_delay", 2.0)))
        self.max_delay_entry.pack(side="left")

        # Action Buttons
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 10))

        self.btn_delete_messages = ctk.CTkButton(
            btn_row,
            text=f"🗑 {i18n.t('btn_delete_messages')}",
            height=38,
            corner_radius=6,
            fg_color=RED_ACCENT,
            hover_color=RED_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.start_message_deletion
        )
        self.btn_delete_messages.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_stop = ctk.CTkButton(
            btn_row,
            text=f"⏹ {i18n.t('btn_stop')}",
            height=38,
            width=90,
            corner_radius=6,
            fg_color=BG_RAIL,
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            state="disabled",
            command=self.stop_active_operation
        )
        self.btn_stop.pack(side="right", padx=(6, 0))

    # ================= 2. SELF-DESTRUCT PANEL =================

    def setup_panel_self_destruct(self, card):
        # Description
        lbl_desc = ctk.CTkLabel(
            card,
            text=i18n.t("self_destruct_desc"),
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            wraplength=650,
            justify="left"
        )
        lbl_desc.pack(anchor="w", padx=14, pady=(10, 8))

        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=4)
        row1.grid_columnconfigure(0, weight=1)
        row1.grid_columnconfigure(1, weight=1)

        # Timer input
        col_timer = ctk.CTkFrame(row1, fg_color="transparent")
        col_timer.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkLabel(col_timer, text=i18n.t("sd_timer_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT).pack(anchor="w", pady=(0, 4))
        timer_box = ctk.CTkFrame(col_timer, fg_color="transparent")
        timer_box.pack(fill="x")

        self.sd_val_entry = ctk.CTkEntry(timer_box, width=80, height=32, fg_color=BG_RAIL, border_color=BORDER_COLOR)
        self.sd_val_entry.insert(0, "60")
        self.sd_val_entry.pack(side="left", padx=(0, 6))

        self.sd_unit_menu = ctk.CTkOptionMenu(
            timer_box,
            values=[i18n.t("unit_seconds"), i18n.t("unit_minutes"), i18n.t("unit_hours"), i18n.t("unit_days")],
            fg_color=BG_RAIL,
            button_color=BG_SIDEBAR,
            height=32
        )
        self.sd_unit_menu.set(i18n.t("unit_minutes"))
        self.sd_unit_menu.pack(side="left")

        # Scope selector
        col_scope = ctk.CTkFrame(row1, fg_color="transparent")
        col_scope.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ctk.CTkLabel(col_scope, text=i18n.t("sd_target_scope"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT).pack(anchor="w", pady=(0, 4))
        self.sd_scope_menu = ctk.CTkOptionMenu(
            col_scope,
            values=[
                i18n.t("sd_scope_selected"),
                i18n.t("sd_scope_all_dms"),
                i18n.t("sd_scope_all_servers"),
                i18n.t("sd_scope_everywhere")
            ],
            fg_color=BG_RAIL,
            button_color=BG_SIDEBAR,
            height=32
        )
        self.sd_scope_menu.set(i18n.t("sd_scope_selected"))
        self.sd_scope_menu.pack(fill="x")

        # Row 2: Purge Window selector
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(2, 6))

        ctk.CTkLabel(row2, text=i18n.t("sd_purge_window_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT).pack(anchor="w", pady=(0, 4))
        self.sd_window_menu = ctk.CTkOptionMenu(
            row2,
            values=[
                i18n.t("sd_window_since_armed"),
                i18n.t("sd_window_1h"),
                i18n.t("sd_window_24h"),
                i18n.t("sd_window_all")
            ],
            fg_color=BG_RAIL,
            button_color=BG_SIDEBAR,
            height=32
        )
        self.sd_window_menu.set(i18n.t("sd_window_since_armed"))
        self.sd_window_menu.pack(fill="x")

        # Live Countdown Display Box
        self.sd_status_box = ctk.CTkFrame(card, fg_color=BG_RAIL, corner_radius=8, height=44)
        self.sd_status_box.pack(fill="x", padx=14, pady=8)

        self.lbl_sd_countdown = ctk.CTkLabel(
            self.sd_status_box,
            text=f"⏱ {i18n.t('sd_status_idle')}",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color=TEXT_MUTED
        )
        self.lbl_sd_countdown.pack(pady=10)

        # Action Buttons for Self-Destruct
        sd_btn_row = ctk.CTkFrame(card, fg_color="transparent")
        sd_btn_row.pack(fill="x", padx=14, pady=(0, 12))

        self.btn_sd_arm = ctk.CTkButton(
            sd_btn_row,
            text=i18n.t("sd_btn_arm"),
            height=38,
            corner_radius=6,
            fg_color=RED_ACCENT,
            hover_color=RED_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.prompt_arm_self_destruct
        )
        self.btn_sd_arm.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_sd_detonate = ctk.CTkButton(
            sd_btn_row,
            text=i18n.t("sd_btn_detonate_now"),
            height=38,
            corner_radius=6,
            fg_color="#8B0000",
            hover_color="#A52A2A",
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self.trigger_detonate_now
        )
        self.btn_sd_detonate.pack(side="left", padx=4)

        self.btn_sd_cancel = ctk.CTkButton(
            sd_btn_row,
            text=i18n.t("sd_btn_cancel"),
            height=38,
            corner_radius=6,
            fg_color=BG_SIDEBAR,
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=12),
            state="disabled",
            command=self.cancel_self_destruct
        )
        self.btn_sd_cancel.pack(side="right", padx=(6, 0))

    # ================= 3. AUTO-EDIT PANEL =================

    def setup_panel_auto_edit(self, card):
        lbl_desc = ctk.CTkLabel(
            card,
            text=i18n.t("auto_edit_desc"),
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            wraplength=650,
            justify="left"
        )
        lbl_desc.pack(anchor="w", padx=14, pady=(10, 6))

        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=4)
        row1.grid_columnconfigure(0, weight=1)
        row1.grid_columnconfigure(1, weight=1)

        # Keyword Search
        col_search = ctk.CTkFrame(row1, fg_color="transparent")
        col_search.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkLabel(col_search, text=i18n.t("ae_search_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT).pack(anchor="w", pady=(0, 4))
        self.ae_search_entry = ctk.CTkEntry(col_search, placeholder_text=i18n.t("ae_search_placeholder"), height=32, fg_color=BG_RAIL, border_color=BORDER_COLOR)
        self.ae_search_entry.pack(fill="x")

        # Action Mode
        col_mode = ctk.CTkFrame(row1, fg_color="transparent")
        col_mode.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ctk.CTkLabel(col_mode, text=i18n.t("ae_mode_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT).pack(anchor="w", pady=(0, 4))
        self.ae_mode_segmented = ctk.CTkSegmentedButton(
            col_mode,
            values=[i18n.t("ae_mode_replace"), i18n.t("ae_mode_delete")],
            command=self.on_ae_mode_changed,
            selected_color=RED_ACCENT,
            selected_hover_color=RED_HOVER,
            unselected_color=BG_RAIL,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.ae_mode_segmented.set(i18n.t("ae_mode_replace"))
        self.ae_mode_segmented.pack(fill="x")

        # Row 1.5: Match Type selector
        row_match = ctk.CTkFrame(card, fg_color="transparent")
        row_match.pack(fill="x", padx=14, pady=(2, 4))
        ctk.CTkLabel(row_match, text=i18n.t("ae_match_type_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT).pack(side="left", padx=(0, 10))

        self.ae_match_segmented = ctk.CTkSegmentedButton(
            row_match,
            values=[i18n.t("ae_match_contains"), i18n.t("ae_match_exact")],
            selected_color=RED_ACCENT,
            selected_hover_color=RED_HOVER,
            unselected_color=BG_RAIL,
            height=30,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.ae_match_segmented.set(i18n.t("ae_match_contains"))
        self.ae_match_segmented.pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=4)
        row2.grid_columnconfigure(0, weight=1)
        row2.grid_columnconfigure(1, weight=1)

        # Replacement text (hidden if delete)
        self.col_replace = ctk.CTkFrame(row2, fg_color="transparent")
        self.col_replace.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.lbl_ae_replace = ctk.CTkLabel(self.col_replace, text=i18n.t("ae_replace_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT)
        self.lbl_ae_replace.pack(anchor="w", pady=(0, 4))
        self.ae_replace_entry = ctk.CTkEntry(self.col_replace, placeholder_text=i18n.t("ae_replace_placeholder"), height=32, fg_color=BG_RAIL, border_color=BORDER_COLOR)
        self.ae_replace_entry.insert(0, "[silindi]")
        self.ae_replace_entry.pack(fill="x")

        # Scope selector
        col_ae_scope = ctk.CTkFrame(row2, fg_color="transparent")
        col_ae_scope.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ctk.CTkLabel(col_ae_scope, text=i18n.t("ae_scope_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT).pack(anchor="w", pady=(0, 4))
        self.ae_scope_menu = ctk.CTkOptionMenu(
            col_ae_scope,
            values=[
                i18n.t("sd_scope_selected"),
                i18n.t("sd_scope_all_dms"),
                i18n.t("sd_scope_all_servers"),
                i18n.t("sd_scope_everywhere")
            ],
            fg_color=BG_RAIL,
            button_color=BG_SIDEBAR,
            height=32
        )
        self.ae_scope_menu.set(i18n.t("sd_scope_selected"))
        self.ae_scope_menu.pack(fill="x")

        # Button
        self.btn_start_auto_edit = ctk.CTkButton(
            card,
            text=i18n.t("ae_btn_start"),
            height=38,
            corner_radius=6,
            fg_color=RED_ACCENT,
            hover_color=RED_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.prompt_start_auto_edit
        )
        self.btn_start_auto_edit.pack(fill="x", padx=14, pady=(8, 12))

    def on_ae_mode_changed(self, val):
        if val == i18n.t("ae_mode_delete"):
            self.col_replace.grid_remove()
        else:
            self.col_replace.grid()

    # ================= 4. ACCOUNT TOOLS PANEL =================

    def setup_panel_account(self, card):
        self.lbl_acc_desc = ctk.CTkLabel(
            card,
            text=i18n.t("acc_tools_desc"),
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            wraplength=680,
            justify="left"
        )
        self.lbl_acc_desc.pack(anchor="w", padx=14, pady=(10, 8))

        tools_container = ctk.CTkScrollableFrame(card, fg_color="transparent", height=230)
        tools_container.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        # Card 1: Leave All Servers
        card_servers = ctk.CTkFrame(tools_container, fg_color=BG_RAIL, corner_radius=8, border_width=1, border_color=BORDER_COLOR)
        card_servers.pack(fill="x", pady=4)
        card_servers.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card_servers, text="🏰", font=ctk.CTkFont(size=24)).grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=10)
        self.lbl_acc_leave_title = ctk.CTkLabel(card_servers, text=i18n.t("acc_leave_title"), font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_LIGHT)
        self.lbl_acc_leave_title.grid(row=0, column=1, sticky="w", pady=(8, 0))
        self.lbl_acc_leave_desc = ctk.CTkLabel(card_servers, text=i18n.t("acc_leave_desc"), font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, wraplength=440, justify="left")
        self.lbl_acc_leave_desc.grid(row=1, column=1, sticky="w", pady=(0, 8))

        self.btn_leave_servers = ctk.CTkButton(
            card_servers,
            text=i18n.t("btn_leave_all_guilds"),
            height=34,
            width=190,
            corner_radius=6,
            fg_color=RED_ACCENT,
            hover_color=RED_HOVER,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.prompt_leave_all_servers
        )
        self.btn_leave_servers.grid(row=0, column=2, rowspan=2, padx=14, pady=10)

        # Card 2: Remove All Friends
        card_friends = ctk.CTkFrame(tools_container, fg_color=BG_RAIL, corner_radius=8, border_width=1, border_color=BORDER_COLOR)
        card_friends.pack(fill="x", pady=4)
        card_friends.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card_friends, text="👥", font=ctk.CTkFont(size=24)).grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=10)
        self.lbl_acc_friends_title = ctk.CTkLabel(card_friends, text=i18n.t("acc_friends_title"), font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_LIGHT)
        self.lbl_acc_friends_title.grid(row=0, column=1, sticky="w", pady=(8, 0))
        self.lbl_acc_friends_desc = ctk.CTkLabel(card_friends, text=i18n.t("acc_friends_desc"), font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, wraplength=440, justify="left")
        self.lbl_acc_friends_desc.grid(row=1, column=1, sticky="w", pady=(0, 8))

        self.btn_remove_friends = ctk.CTkButton(
            card_friends,
            text=i18n.t("btn_remove_all_friends"),
            height=34,
            width=190,
            corner_radius=6,
            fg_color=RED_ACCENT,
            hover_color=RED_HOVER,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.prompt_remove_all_friends
        )
        self.btn_remove_friends.grid(row=0, column=2, rowspan=2, padx=14, pady=10)

        # Card 3: Reset Nicknames
        card_nicks = ctk.CTkFrame(tools_container, fg_color=BG_RAIL, corner_radius=8, border_width=1, border_color=BORDER_COLOR)
        card_nicks.pack(fill="x", pady=4)
        card_nicks.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card_nicks, text="🏷️", font=ctk.CTkFont(size=24)).grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=10)
        self.lbl_acc_nicks_title = ctk.CTkLabel(card_nicks, text=i18n.t("acc_nicks_title"), font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_LIGHT)
        self.lbl_acc_nicks_title.grid(row=0, column=1, sticky="w", pady=(8, 0))
        self.lbl_acc_nicks_desc = ctk.CTkLabel(card_nicks, text=i18n.t("acc_nicks_desc"), font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, wraplength=440, justify="left")
        self.lbl_acc_nicks_desc.grid(row=1, column=1, sticky="w", pady=(0, 8))

        self.btn_reset_nicks = ctk.CTkButton(
            card_nicks,
            text=i18n.t("btn_reset_nicknames"),
            height=34,
            width=190,
            corner_radius=6,
            fg_color=BG_SIDEBAR,
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.prompt_reset_nicknames
        )
        self.btn_reset_nicks.grid(row=0, column=2, rowspan=2, padx=14, pady=10)

    # ================= 5. FAVORITE GIFS PANEL =================

    def setup_panel_gifs(self, card):
        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(10, 4))
        top_row.grid_columnconfigure(0, weight=1)
        top_row.grid_columnconfigure(1, weight=2)

        # Left Info Counter
        info_box = ctk.CTkFrame(top_row, fg_color=BG_RAIL, corner_radius=8)
        info_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.lbl_gif_count_label = ctk.CTkLabel(info_box, text=i18n.t("fav_gifs_count"), font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.lbl_gif_count_label.pack(anchor="w", padx=12, pady=(6, 1))

        self.lbl_gif_count_value = ctk.CTkLabel(info_box, text="--", font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"), text_color=TEXT_LIGHT)
        self.lbl_gif_count_value.pack(anchor="w", padx=12, pady=(0, 6))

        # Right Rules Selector
        rule_box = ctk.CTkFrame(top_row, fg_color="transparent")
        rule_box.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        ctk.CTkLabel(rule_box, text=i18n.t("gif_retention_label"), font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_LIGHT).pack(anchor="w", pady=(0, 4))

        self.gif_rules_map = {
            i18n.t("gif_rule_keep_3m"): "months_3",
            i18n.t("gif_rule_keep_1m"): "months_1",
            i18n.t("gif_rule_keep_6m"): "months_6",
            i18n.t("gif_rule_keep_10"): "count_10",
            i18n.t("gif_rule_keep_25"): "count_25",
            i18n.t("gif_rule_keep_50"): "count_50",
            i18n.t("gif_rule_keep_100"): "count_100",
            i18n.t("gif_rule_all"): "all",
            i18n.t("gif_rule_custom_months"): "custom_months",
            i18n.t("gif_rule_custom_count"): "custom_count",
        }

        self.gif_rule_menu = ctk.CTkOptionMenu(
            rule_box,
            values=list(self.gif_rules_map.keys()),
            command=self.on_gif_rule_changed,
            fg_color=BG_RAIL,
            button_color=BG_SIDEBAR,
            height=32
        )
        self.gif_rule_menu.set(i18n.t("gif_rule_keep_3m"))
        self.gif_rule_menu.pack(fill="x")

        # Custom Val Row for GIFs
        self.gif_custom_frame = ctk.CTkFrame(card, fg_color="transparent")
        ctk.CTkLabel(self.gif_custom_frame, text=i18n.t("gif_custom_val"), font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(side="left", padx=(0, 6))
        self.gif_custom_entry = ctk.CTkEntry(self.gif_custom_frame, width=80, height=28, fg_color=BG_RAIL, border_color=BORDER_COLOR)
        self.gif_custom_entry.insert(0, "3")
        self.gif_custom_entry.pack(side="left")

        # Action Buttons
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(6, 12))

        self.btn_check_gifs = ctk.CTkButton(
            btn_row,
            text=f"🔍 {i18n.t('fav_gifs_btn_fetch')}",
            height=36,
            corner_radius=6,
            fg_color=BG_SIDEBAR,
            hover_color=BG_CARD_HOVER,
            command=self.check_favorite_gifs_count
        )
        self.btn_check_gifs.pack(side="left", padx=(0, 8))

        self.btn_delete_gifs = ctk.CTkButton(
            btn_row,
            text=f"💥 {i18n.t('btn_delete_gifs')}",
            height=36,
            corner_radius=6,
            fg_color=RED_ACCENT,
            hover_color=RED_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.prompt_delete_favorite_gifs
        )
        self.btn_delete_gifs.pack(side="right", fill="x", expand=True)

    def on_gif_rule_changed(self, val):
        rule_code = self.gif_rules_map.get(val, "all")
        if rule_code in ("custom_months", "custom_count"):
            self.gif_custom_frame.pack(fill="x", padx=14, pady=(2, 4))
        else:
            self.gif_custom_frame.pack_forget()

    # ================= CONSOLE BOX =================

    def setup_console(self, parent):
        console_card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_COLOR)
        console_card.grid(row=3, column=0, sticky="nsew", padx=12, pady=(4, 10))
        console_card.grid_rowconfigure(1, weight=1)
        console_card.grid_columnconfigure(0, weight=1)

        metrics_bar = ctk.CTkFrame(console_card, fg_color="transparent")
        metrics_bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        metrics_bar.grid_columnconfigure(1, weight=1)

        self.lbl_console_title = ctk.CTkLabel(
            metrics_bar,
            text=f"🖥 {i18n.t('console_title')}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_LIGHT
        )
        self.lbl_console_title.grid(row=0, column=0, sticky="w")

        self.stats_box = ctk.CTkFrame(metrics_bar, fg_color="transparent")
        self.stats_box.grid(row=0, column=1, sticky="e")

        self.lbl_stat_scanned = ctk.CTkLabel(self.stats_box, text=f"{i18n.t('stat_scanned')}: 0", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.lbl_stat_scanned.pack(side="left", padx=8)

        self.lbl_stat_deleted = ctk.CTkLabel(self.stats_box, text=f"{i18n.t('stat_deleted')}: 0", font=ctk.CTkFont(size=11, weight="bold"), text_color=RED_ACCENT)
        self.lbl_stat_deleted.pack(side="left", padx=8)

        self.lbl_stat_rate = ctk.CTkLabel(self.stats_box, text=f"{i18n.t('stat_rate_limits')}: 0", font=ctk.CTkFont(size=11), text_color=YELLOW_ACCENT)
        self.lbl_stat_rate.pack(side="left", padx=8)

        self.lbl_stat_time = ctk.CTkLabel(self.stats_box, text=f"{i18n.t('stat_elapsed')}: 00:00", font=ctk.CTkFont(size=11), text_color=TEXT_LIGHT)
        self.lbl_stat_time.pack(side="left", padx=8)

        self.btn_clear_console = ctk.CTkButton(
            self.stats_box,
            text="🧹",
            width=26,
            height=26,
            corner_radius=4,
            fg_color=BG_RAIL,
            hover_color=BG_SIDEBAR,
            command=self.clear_console
        )
        self.btn_clear_console.pack(side="left", padx=(8, 0))

        self.console_textbox = ctk.CTkTextbox(
            console_card,
            fg_color=BG_CONSOLE,
            text_color=TEXT_LIGHT,
            corner_radius=6,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="char"
        )
        self.console_textbox.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

        try:
            self.console_textbox._textbox.tag_config("info", foreground="#949BA4")
            self.console_textbox._textbox.tag_config("success", foreground="#57F287")
            self.console_textbox._textbox.tag_config("delete", foreground="#ED4245")
            self.console_textbox._textbox.tag_config("warn", foreground="#FEE75C")
            self.console_textbox._textbox.tag_config("error", foreground="#FF5555")
            self.console_textbox._textbox.tag_config("time", foreground="#5E636E")
        except Exception:
            pass

        self.append_log("info", i18n.t("log_engine_ready"))

    def append_log(self, tag: str, message: str):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = f"[{now}] "
        tag_symbols = {"info": "[INFO]", "success": "[SUCCESS]", "delete": "[DELETE]", "warn": "[WARN]", "error": "[ERROR]"}
        symbol = tag_symbols.get(tag, "[LOG]")

        def _do_append():
            self.console_textbox.configure(state="normal")
            self.console_textbox._textbox.insert("end", prefix, "time")
            self.console_textbox._textbox.insert("end", f"{symbol} ", tag)
            self.console_textbox._textbox.insert("end", f"{message}\n", tag)
            self.console_textbox.see("end")
            self.console_textbox.configure(state="disabled")

        self.safe_ui(_do_append)

    def clear_console(self):
        self.console_textbox.configure(state="normal")
        self.console_textbox.delete("1.0", "end")
        self.console_textbox.configure(state="disabled")
        self.append_log("info", "Console cleared.")

    # ================= EVENT HANDLERS & LOGIC =================

    def on_lang_menu_selected(self, display_name: str):
        lang_code = i18n.get_code_from_display(display_name)
        i18n.set_language(lang_code)
        self.config_data["language"] = lang_code
        self.save_config()

    def on_lang_switch_click(self, value):
        if value:
            self.on_lang_menu_selected(value)

    def on_language_changed(self, lang):
        self.refresh_ui_texts()

    def on_sidebar_width_changed(self, choice):
        if choice == i18n.t("width_compact"):
            w = 185
        elif choice == i18n.t("width_wide"):
            w = 265
        else:
            w = 215
        self.sidebar_frame.configure(width=w)
        self.config_data["sidebar_width"] = w
        self.save_config()

    def refresh_ui_texts(self):
        self.title(f"Notcord {i18n.t('version_badge')} - {i18n.t('credit')}")
        self.credit_badge.configure(text=f"★ {i18n.t('credit')} ★")
        self.lbl_lang.configure(text=i18n.t("language") + ":")
        self.lbl_width.configure(text=i18n.t("sidebar_width") + ":")
        self.btn_links.configure(text=i18n.t("links_btn"))

        # Category Bar & Menus
        if hasattr(self, "category_bar"):
            cat_labels = [self.get_category_label(k) for k in self.CATEGORIES]
            self.category_bar.configure(values=cat_labels)
            self.category_bar.set(self.get_category_label(self.current_category))

        if hasattr(self, "width_menu"):
            self.width_menu.configure(values=[
                i18n.t("width_compact"),
                i18n.t("width_normal"),
                i18n.t("width_wide")
            ])
        if hasattr(self, "lang_menu"):
            self.lang_menu.set(i18n.get_display_name(i18n.current_lang))

        # Login View
        if hasattr(self, "lbl_login_title"):
            self.lbl_login_title.configure(text=i18n.t("login_title"))
        if hasattr(self, "lbl_login_desc"):
            self.lbl_login_desc.configure(text=i18n.t("login_desc"))
        if hasattr(self, "btn_connect_discord"):
            self.btn_connect_discord.configure(text=i18n.t("btn_connect_discord"))
        if hasattr(self, "lbl_token_warning"):
            self.lbl_token_warning.configure(text=i18n.t("token_security_note"))

        # Sidebar
        if hasattr(self, "lbl_sidebar_title"):
            if self.current_tab == "dms":
                self.lbl_sidebar_title.configure(text=i18n.t("tab_dms"))
                self.search_entry.configure(placeholder_text=i18n.t("search_dms_placeholder"))
            else:
                self.lbl_sidebar_title.configure(text=i18n.t("tab_servers"))
                self.search_entry.configure(placeholder_text=i18n.t("search_servers_placeholder"))
        if hasattr(self, "btn_add_id"):
            self.btn_add_id.configure(text=i18n.t("btn_add_by_id"))
        if hasattr(self, "lbl_user_name") and not self.user_data:
            self.lbl_user_name.configure(text=i18n.t("connecting"))

        # Target Header
        if hasattr(self, "lbl_target_name"):
            if not self.selected_target:
                self.lbl_target_name.configure(text=i18n.t("none_selected"))
                self.lbl_target_details.configure(text=i18n.t("select_chat_first"))
            else:
                self.select_target(self.selected_target)

        # 1. Purge Panel
        if hasattr(self, "lbl_type_filter"):
            self.lbl_type_filter.configure(text=i18n.t("filter_type_label"))
        if hasattr(self, "menu_type_filter"):
            self.type_options = [i18n.t("filter_all"), i18n.t("filter_photos"), i18n.t("filter_gifs"), i18n.t("filter_normal")]
            self.menu_type_filter.configure(values=self.type_options)
        if hasattr(self, "lbl_time_filter"):
            self.lbl_time_filter.configure(text=i18n.t("filter_time_label"))
        if hasattr(self, "menu_time_filter"):
            self.time_options = [i18n.t("time_all"), i18n.t("time_1h"), i18n.t("time_6h"), i18n.t("time_24h"), i18n.t("time_7d"), i18n.t("time_30d"), i18n.t("time_custom")]
            self.menu_time_filter.configure(values=self.time_options)
        if hasattr(self, "lbl_custom_time"):
            self.lbl_custom_time.configure(text=i18n.t("custom_time_val"))
        if hasattr(self, "custom_time_unit"):
            self.custom_time_unit.configure(values=[i18n.t("unit_hours"), i18n.t("unit_days")])
        if hasattr(self, "lbl_speed_preset"):
            self.lbl_speed_preset.configure(text=i18n.t("speed_mode"))
        if hasattr(self, "speed_segmented"):
            self.speed_segmented.configure(values=[i18n.t("speed_turbo"), i18n.t("speed_fast"), i18n.t("speed_normal"), i18n.t("speed_safe")])
        if hasattr(self, "random_delay_switch"):
            self.random_delay_switch.configure(text=i18n.t("random_cooldown_label"))
        if hasattr(self, "btn_delete_messages"):
            self.btn_delete_messages.configure(text=f"🗑 {i18n.t('btn_delete_messages')}")
        if hasattr(self, "btn_stop"):
            self.btn_stop.configure(text=f"⏹ {i18n.t('btn_stop')}")
        if hasattr(self, "delay_slider"):
            self.update_delay_label(self.delay_slider.get())

        # 2. Self-Destruct Panel
        if hasattr(self, "lbl_sd_desc"):
            self.lbl_sd_desc.configure(text=i18n.t("self_destruct_desc"))
        if hasattr(self, "sd_unit_menu"):
            self.sd_unit_menu.configure(values=[i18n.t("unit_seconds"), i18n.t("unit_minutes"), i18n.t("unit_hours"), i18n.t("unit_days")])
        if hasattr(self, "sd_scope_menu"):
            self.sd_scope_menu.configure(values=[i18n.t("sd_scope_selected"), i18n.t("sd_scope_all_dms"), i18n.t("sd_scope_all_servers"), i18n.t("sd_scope_everywhere")])
        if hasattr(self, "sd_window_menu"):
            self.sd_window_menu.configure(values=[i18n.t("sd_window_since_armed"), i18n.t("sd_window_1h"), i18n.t("sd_window_24h"), i18n.t("sd_window_all")])
        if hasattr(self, "btn_sd_arm"):
            self.btn_sd_arm.configure(text=f"💣 {i18n.t('btn_arm_sd')}")
        if hasattr(self, "btn_sd_cancel"):
            self.btn_sd_cancel.configure(text=f"🛑 {i18n.t('btn_disarm_sd')}")

        # 3. Auto-Edit Panel
        if hasattr(self, "lbl_ae_desc"):
            self.lbl_ae_desc.configure(text=i18n.t("auto_edit_desc"))
        if hasattr(self, "ae_search_entry"):
            self.ae_search_entry.configure(placeholder_text=i18n.t("ae_search_placeholder"))
        if hasattr(self, "ae_replace_entry"):
            self.ae_replace_entry.configure(placeholder_text=i18n.t("ae_replace_placeholder"))
        if hasattr(self, "ae_mode_segmented"):
            self.ae_mode_segmented.configure(values=[i18n.t("ae_mode_replace"), i18n.t("ae_mode_delete")])
        if hasattr(self, "btn_start_auto_edit"):
            self.btn_start_auto_edit.configure(text=i18n.t("btn_start_auto_edit"))

        # 4. Account Tools Panel
        if hasattr(self, "lbl_acc_desc"):
            self.lbl_acc_desc.configure(text=i18n.t("acc_tools_desc"))
        if hasattr(self, "lbl_acc_leave_title"):
            self.lbl_acc_leave_title.configure(text=i18n.t("acc_leave_title"))
        if hasattr(self, "lbl_acc_leave_desc"):
            self.lbl_acc_leave_desc.configure(text=i18n.t("acc_leave_desc"))
        if hasattr(self, "btn_leave_servers"):
            self.btn_leave_servers.configure(text=i18n.t("btn_leave_all_guilds"))
        if hasattr(self, "lbl_acc_friends_title"):
            self.lbl_acc_friends_title.configure(text=i18n.t("acc_friends_title"))
        if hasattr(self, "lbl_acc_friends_desc"):
            self.lbl_acc_friends_desc.configure(text=i18n.t("acc_friends_desc"))
        if hasattr(self, "btn_remove_friends"):
            self.btn_remove_friends.configure(text=i18n.t("btn_remove_all_friends"))
        if hasattr(self, "lbl_acc_nicks_title"):
            self.lbl_acc_nicks_title.configure(text=i18n.t("acc_nicks_title"))
        if hasattr(self, "lbl_acc_nicks_desc"):
            self.lbl_acc_nicks_desc.configure(text=i18n.t("acc_nicks_desc"))
        if hasattr(self, "btn_reset_nicks"):
            self.btn_reset_nicks.configure(text=i18n.t("btn_reset_nicknames"))

        # 5. Favorite GIFs Panel
        if hasattr(self, "lbl_gifs_desc"):
            self.lbl_gifs_desc.configure(text=i18n.t("gifs_desc"))
        if hasattr(self, "btn_fetch_gifs"):
            self.btn_fetch_gifs.configure(text=f"🔍 {i18n.t('gifs_fetch_btn')}")
        if hasattr(self, "menu_gif_rules"):
            self.menu_gif_rules.configure(values=[i18n.t("rule_all"), i18n.t("rule_retention"), i18n.t("rule_custom_months"), i18n.t("rule_custom_count")])
        if hasattr(self, "btn_delete_gifs"):
            self.btn_delete_gifs.configure(text=f"🗑 {i18n.t('btn_delete_gifs')}")

        # Console
        if hasattr(self, "lbl_console_title"):
            self.lbl_console_title.configure(text=f"🖥 {i18n.t('console_title')}")
        if hasattr(self, "status_text"):
            self.status_text.configure(text=i18n.t("status_ready") if not self.active_worker else i18n.t("status_running"))
        self.update_stats_display(0, 0, 0, 0, 0, "00:00")

    def on_time_option_changed(self, selected_value):
        if selected_value == i18n.t("time_custom"):
            self.custom_time_frame.pack(fill="x", padx=14, pady=(0, 4))
        else:
            self.custom_time_frame.pack_forget()

    def on_speed_preset_selected(self, val):
        if val == i18n.t("speed_turbo"):
            target_delay = 0.15
        elif val == i18n.t("speed_fast"):
            target_delay = 0.30
        elif val == i18n.t("speed_normal"):
            target_delay = 0.80
        elif val == i18n.t("speed_safe"):
            target_delay = 1.20
        else:
            target_delay = 0.15

        self.delay_slider.set(target_delay)
        self.update_delay_label(target_delay)
        self.config_data["delay"] = target_delay
        self.save_config()

    def update_delay_label(self, val: float):
        speed_rate = (1.0 / val) if val > 0 else 20.0
        if val <= 0.20:
            msg = f"{i18n.t('delay_label')} {val:.2f}s (~{speed_rate:.1f} msg/s - ⚡ TURBO)"
        else:
            msg = f"{i18n.t('delay_label')} {val:.2f}s (~{speed_rate:.1f} msg/s)"
        self.lbl_delay.configure(text=msg)

    def on_delay_slider_changed(self, value):
        val = round(value, 2)
        self.update_delay_label(val)
        self.config_data["delay"] = val
        self.save_config()

    # ================= SOCIAL LINKS MODAL =================

    def open_links_modal(self):
        modal = ctk.CTkToplevel(self)
        modal.title(i18n.t("links_title"))
        modal.geometry("540x550")
        modal.configure(fg_color=BG_CARD)
        modal.transient(self)
        modal.grab_set()
        self._apply_window_icon(modal)

        # Banner with Logo & Titles
        banner = ctk.CTkFrame(modal, fg_color=BG_RAIL, corner_radius=10)
        banner.pack(fill="x", padx=18, pady=(16, 10))

        if self.logo_img_32:
            lbl_logo = ctk.CTkLabel(banner, text="", image=self.logo_img_32)
            lbl_logo.pack(side="left", padx=(14, 10), pady=12)

        title_col = ctk.CTkFrame(banner, fg_color="transparent")
        title_col.pack(side="left", pady=10)

        ctk.CTkLabel(title_col, text="Qorelith - Notcord v2.3", font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"), text_color=TEXT_LIGHT).pack(anchor="w")
        ctk.CTkLabel(title_col, text=i18n.t("links_subtitle"), font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(anchor="w")

        # Scrollable Cards Container
        cards_container = ctk.CTkScrollableFrame(modal, fg_color="transparent", height=420)
        cards_container.pack(fill="both", expand=True, padx=18, pady=(0, 16))

        links_data = [
            {
                "title": "YouTube",
                "desc": i18n.t("links_yt_desc"),
                "url": "https://www.youtube.com/@qorelith",
                "color": "#FF0000",
                "image": self.youtube_icon_img,
                "fallback_icon": "▶"
            },
            {
                "title": "Instagram",
                "desc": i18n.t("links_ig_desc"),
                "url": "https://www.instagram.com/qorelith/",
                "color": "#E1306C",
                "image": self.instagram_icon_img,
                "fallback_icon": "📷"
            },
            {
                "title": "Discord (Notcord Server)",
                "desc": i18n.t("links_dc_desc"),
                "url": "https://discord.gg/qVtptkpGNq",
                "color": BLURPLE,
                "image": self.discord_icon_img,
                "fallback_icon": "💬"
            },
            {
                "title": "TikTok",
                "desc": i18n.t("links_tt_desc"),
                "url": "https://www.tiktok.com/@qorelith",
                "color": "#36013F",
                "image": self.tiktok_icon_img,
                "fallback_icon": "🎵"
            },
            {
                "title": "GitHub",
                "desc": i18n.t("links_gh_desc"),
                "url": "https://github.com/qorelith",
                "color": "#000000",
                "image": self.github_icon_img,
                "fallback_icon": "🐙"
            }
        ]

        def _open_url(u):
            webbrowser.open(u)

        def _copy_url(u, btn):
            self.clipboard_clear()
            self.clipboard_append(u)
            old_txt = btn.cget("text")
            btn.configure(text=i18n.t("link_copied"), fg_color=GREEN_ACCENT, text_color=BG_RAIL)
            self.after(1500, lambda: btn.configure(text=old_txt, fg_color=BG_RAIL, text_color=TEXT_LIGHT))

        for item in links_data:
            c = ctk.CTkFrame(cards_container, fg_color=BG_SIDEBAR, corner_radius=8, border_width=1, border_color=BORDER_COLOR)
            c.pack(fill="x", pady=4)
            c.grid_columnconfigure(1, weight=1)

            # Icon Box with real logo if available
            if item["image"]:
                icon_lbl = ctk.CTkLabel(c, text="", image=item["image"], width=36, height=36)
            else:
                icon_lbl = ctk.CTkLabel(c, text=item["fallback_icon"], width=36, height=36, corner_radius=18, fg_color=item["color"], font=ctk.CTkFont(size=16), text_color="#FFFFFF")
            icon_lbl.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=10)

            # Texts
            t_lbl = ctk.CTkLabel(c, text=item["title"], font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_LIGHT)
            t_lbl.grid(row=0, column=1, sticky="w", pady=(8, 0))

            d_lbl = ctk.CTkLabel(c, text=item["desc"], font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, wraplength=220, justify="left")
            d_lbl.grid(row=1, column=1, sticky="w", pady=(0, 8))

            # Buttons
            btn_box = ctk.CTkFrame(c, fg_color="transparent")
            btn_box.grid(row=0, column=2, rowspan=2, padx=10)

            btn_open = ctk.CTkButton(
                btn_box,
                text=i18n.t("btn_open_browser"),
                height=28,
                width=100,
                corner_radius=6,
                fg_color=item["color"] if item["color"] not in ("#010101", "#181717") else RED_ACCENT,
                hover_color=RED_HOVER,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda u=item["url"]: _open_url(u)
            )
            btn_open.pack(side="left", padx=4)

            btn_copy = ctk.CTkButton(
                btn_box,
                text=i18n.t("btn_copy_link"),
                height=28,
                width=60,
                corner_radius=6,
                fg_color=BG_RAIL,
                hover_color=BG_CARD_HOVER,
                font=ctk.CTkFont(size=11),
                command=lambda u=item["url"], b=None: None
            )
            btn_copy.configure(command=lambda u=item["url"], b=btn_copy: _copy_url(u, b))
            btn_copy.pack(side="left", padx=2)

    # ================= CUSTOM ID TARGET MODAL =================

    def open_id_target_modal(self):
        if not self.token:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_token"))
            return

        modal = ctk.CTkToplevel(self)
        modal.title(i18n.t("modal_id_title"))
        modal.geometry("460x280")
        modal.configure(fg_color=BG_CARD)
        modal.transient(self)
        modal.grab_set()
        self._apply_window_icon(modal)

        ctk.CTkLabel(modal, text=f"🔍 {i18n.t('modal_id_title')}", font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT_LIGHT).pack(padx=20, pady=(20, 8))
        ctk.CTkLabel(modal, text=i18n.t("modal_id_desc"), font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, wraplength=420, justify="center").pack(padx=20, pady=(0, 14))

        id_entry = ctk.CTkEntry(modal, placeholder_text=i18n.t("modal_id_placeholder"), height=38, width=380, fg_color=BG_RAIL, border_color=BORDER_COLOR, text_color=TEXT_LIGHT, font=ctk.CTkFont(family="Consolas", size=13))
        id_entry.pack(padx=20, pady=(0, 10))
        id_entry.focus()

        lbl_status = ctk.CTkLabel(modal, text="", font=ctk.CTkFont(size=11), text_color=RED_ACCENT)
        lbl_status.pack(padx=20, pady=(0, 10))

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=30, pady=(0, 16))

        def _do_resolve():
            raw_id = id_entry.get().strip()
            if not raw_id:
                lbl_status.configure(text="Please enter an ID!", text_color=RED_ACCENT)
                return

            btn_find.configure(state="disabled", text=i18n.t("modal_id_searching"))
            lbl_status.configure(text=i18n.t("modal_id_searching"), text_color=TEXT_MUTED)

            def _query_thread():
                ok, target, err = resolve_target_by_id(self.token, raw_id)
                def _callback():
                    btn_find.configure(state="normal", text=i18n.t("modal_id_btn_find"))
                    if ok and target:
                        self.select_target(target)
                        existing = [d for d in self.dms_list if d["id"] == target["id"]]
                        if not existing:
                            self.dms_list.insert(0, target)
                        if self.current_tab == "dms":
                            self.render_dms_list(self.dms_list)
                        self.append_log("success", f"Resolved and selected target: {target['name']} (ID: {target['id']})")
                        modal.destroy()
                    else:
                        lbl_status.configure(text=i18n.t("modal_id_not_found", err=err or "Unknown error"), text_color=RED_ACCENT)
                self.safe_ui(_callback)

            threading.Thread(target=_query_thread, daemon=True).start()

        id_entry.bind("<Return>", lambda e: _do_resolve())

        btn_find = ctk.CTkButton(btn_row, text=i18n.t("modal_id_btn_find"), height=36, fg_color=RED_ACCENT, hover_color=RED_HOVER, font=ctk.CTkFont(weight="bold"), command=_do_resolve)
        btn_find.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_cancel = ctk.CTkButton(btn_row, text=i18n.t("btn_cancel"), height=36, fg_color=BG_SIDEBAR, hover_color=BG_CARD_HOVER, command=modal.destroy)
        btn_cancel.pack(side="right", fill="x", expand=True, padx=(8, 0))

    # ================= AUTHENTICATION =================

    def do_direct_login(self, token: str, user_data: dict):
        """Performs login with a pre-verified token and user_data (token never shown or stored)."""
        self.token = token
        self.user_data = user_data
        # Never save token to disk
        self.config_data.pop("token", None)
        self.save_config()

        username = user_data.get("username", "Unknown")
        global_name = user_data.get("global_name") or username
        user_id = user_data.get("id", "")

        self.show_view("main")
        self.lbl_user_name.configure(text=global_name)
        self.lbl_user_handle.configure(text=f"@{username}")
        self.status_dot.configure(text_color=GREEN_ACCENT)
        self.status_text.configure(text=i18n.t("status_ready"))
        self.lbl_login_status.configure(text="", text_color=TEXT_MUTED)

        # Fetch real Discord Avatar for current user
        avatar_url = get_user_avatar_url(user_data, size=64)
        AvatarCache.load_avatar_async(
            avatar_url,
            (36, 36),
            lambda img: self.safe_ui(lambda: self._set_user_avatar_img(img))
        )

        self.append_log("success", i18n.t("log_login_success", user=f"{global_name} (@{username})", id=user_id))

        # Initialize self-destruct manager
        self.self_destruct_mgr = SelfDestructManager(
            token=self.token,
            user_id=user_id,
            on_log=self.append_log,
            on_tick=self.on_sd_tick,
            on_complete=self.on_sd_complete
        )

        self.load_dms()
        self.check_favorite_gifs_count()

    def _set_user_avatar_img(self, pil_img: Optional[Image.Image]):
        if pil_img:
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(34, 34))
            self._user_avatar_ctk = ctk_img  # Prevent GC from collecting CTkImage
            self.lbl_user_avatar.configure(text="", image=ctk_img)
        else:
            self._user_avatar_ctk = None
            self.lbl_user_avatar.configure(text="👤", image=None)

    def do_logout(self):
        self.token = ""
        self.user_data = None
        self.selected_target = None
        if self.self_destruct_mgr:
            self.self_destruct_mgr.cancel()
            self.self_destruct_mgr = None

        self.lbl_user_name.configure(text="")
        self.lbl_user_handle.configure(text="Not logged in")
        self.lbl_user_avatar.configure(text="👤", image=None)
        self.status_dot.configure(text_color=TEXT_MUTED)
        self.status_text.configure(text=i18n.t("status_ready"))
        self.lbl_target_name.configure(text=i18n.t("none_selected"))
        self.lbl_target_details.configure(text=i18n.t("select_chat_first"))
        self.lbl_target_avatar.configure(text="#", image=None)
        self.clear_sidebar()
        self.dms_list = []
        self.guilds_list = []
        if hasattr(self, "btn_connect_discord"):
            self.btn_connect_discord.configure(state="normal", text=i18n.t("btn_connect_discord"))
        if hasattr(self, "lbl_login_status"):
            self.lbl_login_status.configure(text="")
        self.show_view("login")

    # ================= SIDEBAR NAVIGATION & ITEMS =================

    def switch_nav_tab(self, tab_name: str):
        self.current_tab = tab_name
        self.btn_rail_dms.configure(fg_color=RED_ACCENT if tab_name == "dms" else BG_CARD)
        self.btn_rail_servers.configure(fg_color=RED_ACCENT if tab_name == "servers" else BG_CARD)

        if tab_name == "dms":
            self.lbl_sidebar_title.configure(text=i18n.t("tab_dms"))
            self.search_entry.configure(placeholder_text=i18n.t("search_dms_placeholder"))
            if not self.dms_list and self.token:
                self.load_dms()
            else:
                self.render_dms_list(self.dms_list)
        elif tab_name == "servers":
            self.lbl_sidebar_title.configure(text=i18n.t("tab_servers"))
            self.search_entry.configure(placeholder_text=i18n.t("search_servers_placeholder"))
            if not self.guilds_list and self.token:
                self.load_servers()
            else:
                self.render_guilds_list(self.guilds_list)

    def refresh_current_list(self):
        if not self.token:
            return
        if self.current_tab == "dms":
            self.load_dms()
        elif self.current_tab == "servers":
            self.load_servers()

    def clear_sidebar(self):
        for widget in self.items_scroll.winfo_children():
            widget.destroy()

    def load_dms(self):
        self.clear_sidebar()
        loading_lbl = ctk.CTkLabel(self.items_scroll, text=i18n.t("loading_dms"), text_color=TEXT_MUTED)
        loading_lbl.pack(pady=20)

        def _fetch():
            dms = get_dms(self.token)
            self.dms_list = dms
            self.safe_ui(lambda: self.render_dms_list(dms))

        threading.Thread(target=_fetch, daemon=True).start()

    def render_dms_list(self, dms: List[dict]):
        self.clear_sidebar()
        if not dms:
            lbl = ctk.CTkLabel(self.items_scroll, text=i18n.t("no_dms_found"), text_color=TEXT_MUTED)
            lbl.pack(pady=20)
            return

        def _truncate(s: str, max_len: int = 24) -> str:
            return s if len(s) <= max_len else s[:max_len - 1] + "…"

        for dm in dms:
            display_name = _truncate(dm['name'])
            display_handle = _truncate(dm['handle'])
            row_btn = ctk.CTkButton(
                self.items_scroll,
                text=f"  {display_name}\n  @{display_handle}",
                anchor="w",
                height=46,
                corner_radius=6,
                fg_color="transparent",
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_LIGHT,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda d=dm: self.select_target(d)
            )
            row_btn.pack(fill="x", pady=2)

            # Asynchronously load friend / group avatar
            if dm.get("avatar_url"):
                AvatarCache.load_avatar_async(
                    dm["avatar_url"],
                    (30, 30),
                    lambda img, b=row_btn: self.safe_ui(lambda: self._apply_btn_image(b, img))
                )

    def _apply_btn_image(self, btn: ctk.CTkButton, pil_img: Optional[Image.Image]):
        if pil_img and btn.winfo_exists():
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(30, 30))
            self._avatar_refs[id(btn)] = ctk_img  # Prevent GC from collecting CTkImage
            btn.configure(image=ctk_img, compound="left")

    def load_servers(self):
        self.clear_sidebar()
        loading_lbl = ctk.CTkLabel(self.items_scroll, text=i18n.t("loading_servers"), text_color=TEXT_MUTED)
        loading_lbl.pack(pady=20)

        def _fetch():
            guilds = get_guilds(self.token)
            self.guilds_list = guilds
            self.safe_ui(lambda: self.render_guilds_list(guilds))

        threading.Thread(target=_fetch, daemon=True).start()

    def render_guilds_list(self, guilds: List[dict]):
        self.clear_sidebar()
        if not guilds:
            lbl = ctk.CTkLabel(self.items_scroll, text=i18n.t("no_servers_found"), text_color=TEXT_MUTED)
            lbl.pack(pady=20)
            return

        def _truncate_guild(s: str, max_len: int = 26) -> str:
            return s if len(s) <= max_len else s[:max_len - 1] + "…"

        for g in guilds:
            display_gname = _truncate_guild(g['name'])
            g_btn = ctk.CTkButton(
                self.items_scroll,
                text=f"  {display_gname}",
                anchor="w",
                height=40,
                corner_radius=6,
                fg_color=BG_CARD,
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_LIGHT,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda gid=g["id"], gname=g["name"], gicon=g.get("icon_url"): self.toggle_guild_channels(gid, gname, gicon)
            )
            g_btn.pack(fill="x", pady=2)

            if g.get("icon_url"):
                AvatarCache.load_avatar_async(
                    g["icon_url"],
                    (28, 28),
                    lambda img, b=g_btn: self.safe_ui(lambda: self._apply_btn_image(b, img))
                )

    def toggle_guild_channels(self, guild_id: str, guild_name: str, guild_icon_url: Optional[str] = None):
        self.append_log("info", f"Fetching channels for server: {guild_name}...")

        def _fetch():
            channels = get_guild_channels(self.token, guild_id)
            self.safe_ui(lambda: self.open_channel_picker_dialog(guild_name, guild_icon_url, channels))

        threading.Thread(target=_fetch, daemon=True).start()

    def open_channel_picker_dialog(self, guild_name: str, guild_icon_url: Optional[str], channels: List[dict]):
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"{guild_name} - {i18n.t('server_channel')}")
        dialog.geometry("420x520")
        dialog.configure(fg_color=BG_SIDEBAR)
        dialog.transient(self)
        dialog.grab_set()
        self._apply_window_icon(dialog)

        top_header = ctk.CTkFrame(dialog, fg_color="transparent")
        top_header.pack(fill="x", padx=16, pady=(16, 8))

        lbl_icon = ctk.CTkLabel(top_header, text="🏰", font=ctk.CTkFont(size=20))
        lbl_icon.pack(side="left", padx=(0, 8))

        if guild_icon_url:
            AvatarCache.load_avatar_async(
                guild_icon_url,
                (32, 32),
                lambda img: self.safe_ui(lambda: lbl_icon.configure(text="", image=ctk.CTkImage(light_image=img, dark_image=img, size=(32, 32))) if img else None)
            )

        ctk.CTkLabel(top_header, text=guild_name, font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT_LIGHT).pack(side="left")

        scroll = ctk.CTkScrollableFrame(dialog, fg_color=BG_MAIN, corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=16, pady=8)

        if not channels:
            ctk.CTkLabel(scroll, text="No text channels accessible.", text_color=TEXT_MUTED).pack(pady=20)

        for ch in channels:
            ch_data = {
                "id": ch["id"],
                "name": f"{guild_name} / {ch['name']}",
                "handle": f"Server: {guild_name}",
                "type": "channel",
                "type_name": i18n.t("server_channel"),
                "avatar_url": guild_icon_url
            }
            btn = ctk.CTkButton(
                scroll,
                text=ch["name"],
                anchor="w",
                height=36,
                fg_color="transparent",
                hover_color=BG_CARD_HOVER,
                font=ctk.CTkFont(size=12),
                command=lambda d=ch_data, dlg=dialog: (self.select_target(d), dlg.destroy())
            )
            btn.pack(fill="x", pady=2)

    def filter_sidebar_items(self):
        query = self.search_entry.get().strip().lower()
        if self.current_tab == "dms":
            if not query:
                self.render_dms_list(self.dms_list)
            else:
                filtered = [d for d in self.dms_list if query in d["name"].lower() or query in d["handle"].lower()]
                self.render_dms_list(filtered)
        elif self.current_tab == "servers":
            if not query:
                self.render_guilds_list(self.guilds_list)
            else:
                filtered = [g for g in self.guilds_list if query in g["name"].lower()]
                self.render_guilds_list(filtered)

    def select_target(self, target: dict):
        self.selected_target = target
        self.lbl_target_name.configure(text=target["name"])
        target_type_str = target.get("type_name") or target.get("type", "").upper()
        self.lbl_target_details.configure(
            text=f"{i18n.t('target_type')} {target_type_str}  |  {i18n.t('channel_id')} {target['id']}"
        )

        # Set Target Avatar
        if target.get("avatar_url"):
            AvatarCache.load_avatar_async(
                target["avatar_url"],
                (38, 38),
                lambda img: self.safe_ui(lambda: self._set_target_avatar_img(img))
            )
        else:
            self._set_target_avatar_img(None, fallback="💬" if target.get("type") in ("dm", "group") else "#")

        self.append_log("info", f"Selected target: {target['name']} (ID: {target['id']})")

    def _set_target_avatar_img(self, pil_img: Optional[Image.Image], fallback: str = "💬"):
        if pil_img:
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(38, 38))
            self._target_avatar_ctk = ctk_img  # Prevent GC from collecting CTkImage
            self.lbl_target_avatar.configure(text="", image=ctk_img)
        else:
            self._target_avatar_ctk = None
            self.lbl_target_avatar.configure(text=fallback, image=None)

    # ================= MESSAGE PURGING OPERATION =================

    def get_time_limit_seconds(self) -> Optional[int]:
        selected = self.menu_time_filter.get()
        if selected == i18n.t("time_1h"):
            return 3600
        elif selected == i18n.t("time_6h"):
            return 3600 * 6
        elif selected == i18n.t("time_24h"):
            return 3600 * 24
        elif selected == i18n.t("time_7d"):
            return 3600 * 24 * 7
        elif selected == i18n.t("time_30d"):
            return 3600 * 24 * 30
        elif selected == i18n.t("time_custom"):
            try:
                val = float(self.custom_time_entry.get().strip())
                unit = self.custom_time_unit.get()
                if unit == i18n.t("unit_days"):
                    return int(val * 86400)
                else:
                    return int(val * 3600)
            except Exception:
                return None
        return None

    def get_filter_type_code(self) -> str:
        selected = self.menu_type_filter.get()
        if selected == i18n.t("filter_photos"):
            return "photos"
        elif selected == i18n.t("filter_gifs"):
            return "gifs"
        elif selected == i18n.t("filter_normal"):
            return "normal"
        return "all"

    def start_message_deletion(self):
        if not self.token or not self.user_data:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_token"))
            return

        if not self.selected_target:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_channel"))
            return

        if self.active_worker and self.active_worker.is_alive():
            self.show_alert(i18n.t("alert_notice"), i18n.t("error_already_running"))
            return

        filter_name = self.menu_type_filter.get()
        time_name = self.menu_time_filter.get()
        target_name = self.selected_target["name"]
        confirm_msg = i18n.t("confirm_del_msg", target=target_name, filter=filter_name, time=time_name)

        self.prompt_confirmation(
            title=i18n.t("confirm_del_title"),
            message=confirm_msg,
            on_confirm=self._execute_message_deletion
        )

    def _execute_message_deletion(self):
        channel_id = self.selected_target["id"]
        channel_name = self.selected_target["name"]
        user_id = self.user_data["id"]
        filter_type = self.get_filter_type_code()
        time_limit = self.get_time_limit_seconds()
        delay = self.delay_slider.get()

        # Read random delay settings
        random_delay_on = bool(self.random_delay_switch.get())
        try:
            min_d = float(self.min_delay_entry.get().strip())
        except Exception:
            min_d = 0.5
        try:
            max_d = float(self.max_delay_entry.get().strip())
        except Exception:
            max_d = 2.0

        self.btn_delete_messages.configure(state="disabled")
        self.btn_stop.configure(state="normal", fg_color=RED_ACCENT)
        self.status_dot.configure(text_color=YELLOW_ACCENT)
        self.status_text.configure(text=i18n.t("status_running"))

        self.active_worker = MessagePurgerWorker(
            token=self.token,
            channel_id=channel_id,
            channel_name=channel_name,
            user_id=user_id,
            filter_type=filter_type,
            time_limit_seconds=time_limit,
            delay=delay,
            random_delay=random_delay_on,
            min_delay=min_d,
            max_delay=max_d,
            on_log=self.append_log,
            on_progress=self.on_worker_progress,
            on_finished=self.on_worker_finished,
            on_stopped=self.on_worker_stopped
        )
        self.active_worker.start()

    def stop_active_operation(self):
        if self.active_worker and hasattr(self.active_worker, "stop"):
            self.append_log("warn", "Stopping purge operation...")
            self.active_worker.stop()
            self.btn_stop.configure(state="disabled")

    def on_worker_progress(self, scanned, deleted, skipped, errors, rate_limits, elapsed):
        self.safe_ui(lambda: self.update_stats_display(scanned, deleted, skipped, errors, rate_limits, elapsed))

    def update_stats_display(self, scanned, deleted, skipped, errors, rate_limits, elapsed):
        self.lbl_stat_scanned.configure(text=f"{i18n.t('stat_scanned')}: {scanned}")
        self.lbl_stat_deleted.configure(text=f"{i18n.t('stat_deleted')}: {deleted}")
        self.lbl_stat_rate.configure(text=f"{i18n.t('stat_rate_limits')}: {rate_limits}")
        self.lbl_stat_time.configure(text=f"{i18n.t('stat_elapsed')}: {elapsed}")

    def on_worker_finished(self, summary: dict):
        def _finish():
            self.btn_delete_messages.configure(state="normal")
            self.btn_stop.configure(state="disabled", fg_color=BG_RAIL)
            self.status_dot.configure(text_color=GREEN_ACCENT)
            self.status_text.configure(text=i18n.t("status_completed"))

            self.show_alert(
                i18n.t("delete_complete_title"),
                i18n.t("delete_complete_msg", deleted=summary["deleted"], scanned=summary["scanned"], time=summary["elapsed"])
            )
        self.safe_ui(_finish)

    def on_worker_stopped(self):
        def _stop():
            self.btn_delete_messages.configure(state="normal")
            self.btn_stop.configure(state="disabled", fg_color=BG_RAIL)
            self.status_dot.configure(text_color=TEXT_MUTED)
            self.status_text.configure(text=i18n.t("status_stopped"))
        self.safe_ui(_stop)

    # ================= SELF-DESTRUCT LOGIC =================

    def prompt_arm_self_destruct(self):
        if not self.token or not self.user_data:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_token"))
            return

        try:
            val = float(self.sd_val_entry.get().strip())
        except Exception:
            self.show_alert(i18n.t("error_title"), i18n.t("error_invalid_timer"))
            return

        unit = self.sd_unit_menu.get()
        if unit == i18n.t("unit_seconds"):
            secs = int(val)
        elif unit == i18n.t("unit_minutes"):
            secs = int(val * 60)
        elif unit == i18n.t("unit_hours"):
            secs = int(val * 3600)
        else:
            secs = int(val * 86400)

        scope_choice = self.sd_scope_menu.get()
        if scope_choice == i18n.t("sd_scope_all_dms"):
            scope_code = "all_dms"
        elif scope_choice == i18n.t("sd_scope_all_servers"):
            scope_code = "all_servers"
        elif scope_choice == i18n.t("sd_scope_everywhere"):
            scope_code = "everywhere"
        else:
            if not self.selected_target:
                self.show_alert(i18n.t("error_title"), i18n.t("error_no_channel"))
                return
            scope_code = "selected"

        ch_id = self.selected_target["id"] if self.selected_target else None
        ch_name = self.selected_target["name"] if self.selected_target else ""

        # Read purge window from UI
        window_choice = self.sd_window_menu.get()
        if window_choice == i18n.t("sd_window_1h"):
            purge_mode = "last_1h"
        elif window_choice == i18n.t("sd_window_24h"):
            purge_mode = "last_24h"
        elif window_choice == i18n.t("sd_window_all"):
            purge_mode = "all"
        else:
            purge_mode = "since_armed"

        confirm_msg = i18n.t(
            "confirm_sd_arm_msg",
            duration=f"{val} {unit} ({secs}s)",
            scope=scope_choice,
            window=window_choice
        )

        def _do_arm():
            self.btn_sd_arm.configure(state="disabled")
            self.btn_sd_detonate.configure(state="normal")
            self.btn_sd_cancel.configure(state="normal")
            self.self_destruct_mgr.arm(
                duration_seconds=secs,
                scope=scope_code,
                channel_id=ch_id,
                channel_name=ch_name,
                purge_mode=purge_mode
            )

        self.prompt_confirmation(
            title=i18n.t("confirm_sd_arm_title"),
            message=confirm_msg,
            on_confirm=_do_arm
        )

    def on_sd_tick(self, remaining: int, formatted: str):
        def _update():
            if formatted == "cancelled":
                self.lbl_sd_countdown.configure(text=f"⏱ {i18n.t('sd_status_idle')}", text_color=TEXT_MUTED)
                self.btn_sd_arm.configure(state="normal")
                self.btn_sd_detonate.configure(state="disabled")
                self.btn_sd_cancel.configure(state="disabled")
            else:
                self.lbl_sd_countdown.configure(
                    text=f"⏳ {i18n.t('sd_status_armed', time_left=formatted)}",
                    text_color="#FF4757"
                )
        self.safe_ui(_update)

    def on_sd_complete(self, total_deleted: int):
        def _done():
            self.lbl_sd_countdown.configure(text=f"💥 {i18n.t('sd_status_completed')} ({total_deleted} msg)", text_color=GREEN_ACCENT)
            self.btn_sd_arm.configure(state="normal")
            self.btn_sd_detonate.configure(state="disabled")
            self.btn_sd_cancel.configure(state="disabled")
            self.show_alert(i18n.t("sd_complete_title"), i18n.t("sd_complete_msg", count=total_deleted))
        self.safe_ui(_done)

    def trigger_detonate_now(self):
        if self.self_destruct_mgr and self.self_destruct_mgr.is_armed:
            self.lbl_sd_countdown.configure(text=f"💥 {i18n.t('sd_status_purging')}", text_color=YELLOW_ACCENT)
            self.self_destruct_mgr.detonate_now()

    def cancel_self_destruct(self):
        if self.self_destruct_mgr:
            self.self_destruct_mgr.cancel()

    # ================= AUTO-DETECT DISCORD LOGIN =================

    def do_auto_detect_discord(self):
        """Scans local Discord installations for an active session token. Token never shown or stored."""
        if hasattr(self, "btn_connect_discord"):
            self.btn_connect_discord.configure(state="disabled", text=i18n.t("auto_detect_searching"))
        if hasattr(self, "lbl_login_status"):
            self.lbl_login_status.configure(text=i18n.t("auto_detect_searching"), text_color=TEXT_MUTED)

        def _scan():
            sessions = find_local_discord_sessions()

            def _callback():
                if hasattr(self, "btn_connect_discord"):
                    self.btn_connect_discord.configure(state="normal", text=i18n.t("btn_connect_discord"))
                if sessions:
                    token, user_data = sessions[0]
                    username = user_data.get("username", "Unknown")
                    global_name = user_data.get("global_name") or username
                    if hasattr(self, "lbl_login_status"):
                        self.lbl_login_status.configure(
                            text=i18n.t("auto_detect_found", user=f"{global_name} (@{username})"),
                            text_color=GREEN_ACCENT
                        )
                    # Login directly — token is never placed in any UI widget
                    self.after(400, lambda: self.do_direct_login(token, user_data))
                else:
                    if hasattr(self, "lbl_login_status"):
                        self.lbl_login_status.configure(
                            text=i18n.t("auto_detect_not_found"),
                            text_color=RED_ACCENT
                        )
            self.safe_ui(_callback)

        threading.Thread(target=_scan, daemon=True).start()

    # ================= RANDOM DELAY TOGGLE =================

    def on_random_delay_toggled(self):
        """Saves random delay switch state to config."""
        enabled = bool(self.random_delay_switch.get())
        self.config_data["random_delay"] = enabled
        try:
            self.config_data["min_delay"] = float(self.min_delay_entry.get().strip())
        except Exception:
            pass
        try:
            self.config_data["max_delay"] = float(self.max_delay_entry.get().strip())
        except Exception:
            pass
        self.save_config()

    # ================= AUTO-EDIT LOGIC =================

    def prompt_start_auto_edit(self):
        if not self.token or not self.user_data:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_token"))
            return

        keyword = self.ae_search_entry.get().strip()
        if not keyword:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_search_phrase"))
            return

        mode_val = self.ae_mode_segmented.get()
        action_mode = "delete" if mode_val == i18n.t("ae_mode_delete") else "replace"
        replacement = self.ae_replace_entry.get() if action_mode == "replace" else ""

        scope_val = self.ae_scope_menu.get()
        if scope_val == i18n.t("sd_scope_all_dms"):
            scope_code = "all_dms"
        elif scope_val == i18n.t("sd_scope_all_servers"):
            scope_code = "all_servers"
        elif scope_val == i18n.t("sd_scope_everywhere"):
            scope_code = "everywhere"
        else:
            if not self.selected_target:
                self.show_alert(i18n.t("error_title"), i18n.t("error_no_channel"))
                return
            scope_code = "selected"

        ch_id = self.selected_target["id"] if self.selected_target else None
        ch_name = self.selected_target["name"] if self.selected_target else "Selected Chat"

        confirm_msg = i18n.t(
            "confirm_ae_msg",
            search=keyword,
            mode=mode_val,
            replace=replacement if action_mode == "replace" else "N/A",
            scope=scope_val
        )

        def _execute_auto_edit():
            self.btn_start_auto_edit.configure(state="disabled")
            self.append_log("warn", "Starting Auto-Edit operation...")

            def _on_finish(summary):
                self.safe_ui(lambda: (
                    self.btn_start_auto_edit.configure(state="normal"),
                    self.show_alert(
                        i18n.t("ae_complete_title"),
                        i18n.t("ae_complete_msg", scanned=summary["scanned"], modified=summary["modified"], time=summary["elapsed"])
                    )
                ))

            # Read match type from UI
            match_val = self.ae_match_segmented.get()
            match_type = "exact" if match_val == i18n.t("ae_match_exact") else "contains"

            worker = AutoEditWorker(
                token=self.token,
                user_id=self.user_data["id"],
                search_keyword=keyword,
                action_mode=action_mode,
                match_type=match_type,
                replacement_text=replacement,
                scope=scope_code,
                target_channel_id=ch_id,
                target_channel_name=ch_name,
                delay=self.delay_slider.get(),
                on_log=self.append_log,
                on_finished=_on_finish
            )
            worker.start()

        self.prompt_confirmation(
            title=i18n.t("confirm_ae_title"),
            message=confirm_msg,
            on_confirm=_execute_auto_edit
        )

    # ================= ACCOUNT TOOLS LOGIC =================

    def prompt_leave_all_servers(self):
        if not self.token:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_token"))
            return

        def _execute():
            self.btn_leave_servers.configure(state="disabled")
            self.append_log("warn", "Starting mass server leave operation...")

            def _on_finish(left, skipped):
                self.safe_ui(lambda: (
                    self.btn_leave_servers.configure(state="normal"),
                    self.load_servers(),
                    self.show_alert(
                        i18n.t("acc_leave_complete_title"),
                        i18n.t("acc_leave_complete_msg", left=left, skipped=skipped)
                    )
                ))

            worker = MassLeaveGuildsWorker(self.token, on_log=self.append_log, on_finished=_on_finish)
            worker.start()

        self.prompt_confirmation(
            title=i18n.t("confirm_leave_guilds_title"),
            message=i18n.t("confirm_leave_guilds_msg"),
            on_confirm=_execute
        )

    def prompt_remove_all_friends(self):
        if not self.token:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_token"))
            return

        def _execute():
            self.btn_remove_friends.configure(state="disabled")
            self.append_log("warn", "Starting mass friend removal operation...")

            def _on_finish(removed):
                self.safe_ui(lambda: (
                    self.btn_remove_friends.configure(state="normal"),
                    self.load_dms(),
                    self.show_alert(
                        i18n.t("acc_friends_complete_title"),
                        i18n.t("acc_friends_complete_msg", removed=removed)
                    )
                ))

            worker = MassRemoveFriendsWorker(self.token, on_log=self.append_log, on_finished=_on_finish)
            worker.start()

        self.prompt_confirmation(
            title=i18n.t("confirm_remove_friends_title"),
            message=i18n.t("confirm_remove_friends_msg"),
            on_confirm=_execute
        )

    def prompt_reset_nicknames(self):
        if not self.token:
            self.show_alert(i18n.t("error_title"), i18n.t("error_no_token"))
            return

        def _execute():
            self.btn_reset_nicks.configure(state="disabled")
            self.append_log("warn", "Starting friend nickname reset...")

            def _on_finish(reset_cnt):
                self.safe_ui(lambda: (
                    self.btn_reset_nicks.configure(state="normal"),
                    self.load_dms(),
                    self.show_alert(
                        i18n.t("acc_nicks_complete_title"),
                        i18n.t("acc_nicks_complete_msg", reset=reset_cnt)
                    )
                ))

            worker = FriendNicknameResetWorker(self.token, on_log=self.append_log, on_finished=_on_finish)
            worker.start()

        self.prompt_confirmation(
            title=i18n.t("confirm_reset_nicks_title"),
            message=i18n.t("confirm_reset_nicks_msg"),
            on_confirm=_execute
        )

    # ================= FAVORITE GIFS OPERATION =================

    def check_favorite_gifs_count(self):
        if not self.token:
            return
        self.lbl_gif_count_value.configure(text=i18n.t("fav_gifs_loading"))

        def _query():
            count, _ = get_favorite_gifs(self.token)
            def _update():
                self.lbl_gif_count_value.configure(text=str(count))
                self.append_log("info", f"Favorite GIFs count: {count}")
            self.safe_ui(_update)

        threading.Thread(target=_query, daemon=True).start()

    def prompt_delete_favorite_gifs(self):
        if not self.token:
            self.show_alert("Error", i18n.t("error_no_token"))
            return

        selected_label = self.gif_rule_menu.get()
        rule_code = self.gif_rules_map.get(selected_label, "all")

        custom_val = 0
        if rule_code in ("custom_months", "custom_count"):
            try:
                custom_val = float(self.gif_custom_entry.get().strip())
            except Exception:
                custom_val = 3

        def _proceed_with_count(count):
            if count == 0:
                self.show_alert("Info", i18n.t("fav_gifs_none"))
                return

            confirm_msg = i18n.t(
                "confirm_gif_retention_msg",
                rule=selected_label,
                total=count,
                to_delete=count if rule_code == "all" else "Filtered",
                to_keep="0" if rule_code == "all" else "Filtered"
            )

            self.prompt_confirmation(
                title=i18n.t("confirm_gif_title"),
                message=confirm_msg,
                on_confirm=lambda: self._execute_delete_favorite_gifs(rule_code, custom_val)
            )

        def _fetch():
            count, _ = get_favorite_gifs(self.token)
            self.safe_ui(lambda: _proceed_with_count(count))

        threading.Thread(target=_fetch, daemon=True).start()

    def _execute_delete_favorite_gifs(self, rule_code: str, custom_val: float):
        self.append_log("warn", i18n.t("log_clearing_gifs"))
        self.btn_delete_gifs.configure(state="disabled")

        def _do_clear():
            ok, deleted, kept, err = delete_favorite_gifs_advanced(self.token, keep_mode=rule_code, custom_val=custom_val)
            def _done():
                self.btn_delete_gifs.configure(state="normal")
                if ok:
                    self.lbl_gif_count_value.configure(text=str(kept))
                    self.append_log("success", i18n.t("log_cleared_gifs_success", count=deleted))
                    self.show_alert(
                        i18n.t("gif_complete_title"),
                        i18n.t("gif_complete_retention_msg", deleted=deleted, kept=kept)
                    )
                else:
                    self.append_log("error", f"Failed to clear GIFs: {err}")
                    self.show_alert(i18n.t("error_title"), f"Could not clear favorite GIFs: {err}")
            self.safe_ui(_done)

        threading.Thread(target=_do_clear, daemon=True).start()

    # ================= MODALS & DIALOGS =================

    def prompt_confirmation(self, title: str, message: str, on_confirm: callable):
        modal = ctk.CTkToplevel(self)
        modal.title(title)
        modal.geometry("460x280")
        modal.configure(fg_color=BG_CARD)
        modal.transient(self)
        modal.grab_set()
        self._apply_window_icon(modal)

        lbl_t = ctk.CTkLabel(modal, text=title, font=ctk.CTkFont(size=16, weight="bold"), text_color=RED_ACCENT)
        lbl_t.pack(padx=20, pady=(20, 10))

        lbl_m = ctk.CTkLabel(modal, text=message, font=ctk.CTkFont(size=12), text_color=TEXT_LIGHT, wraplength=410, justify="center")
        lbl_m.pack(padx=20, pady=(0, 24))

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=30, pady=(0, 16))

        def _confirm_action():
            modal.destroy()
            on_confirm()

        btn_yes = ctk.CTkButton(btn_row, text=i18n.t("btn_yes"), height=36, fg_color=RED_ACCENT, hover_color=RED_HOVER, font=ctk.CTkFont(weight="bold"), command=_confirm_action)
        btn_yes.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_cancel = ctk.CTkButton(btn_row, text=i18n.t("btn_cancel"), height=36, fg_color=BG_SIDEBAR, hover_color=BG_CARD_HOVER, command=modal.destroy)
        btn_cancel.pack(side="right", fill="x", expand=True, padx=(8, 0))

    def show_alert(self, title: str, message: str):
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("400x220")
        dialog.configure(fg_color=BG_CARD)
        dialog.transient(self)
        dialog.grab_set()
        self._apply_window_icon(dialog)

        ctk.CTkLabel(dialog, text=title, font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT_LIGHT).pack(padx=20, pady=(20, 10))
        ctk.CTkLabel(dialog, text=message, font=ctk.CTkFont(size=12), text_color=TEXT_MUTED, wraplength=350, justify="center").pack(padx=20, pady=(0, 20))
        ctk.CTkButton(dialog, text=i18n.t("btn_ok"), width=100, height=34, fg_color=RED_ACCENT, hover_color=RED_HOVER, command=dialog.destroy).pack(pady=(0, 16))


def main():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            myappid = "qorelith.notcord.discordmanager.2.2.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
    app = NotcordApp()
    app.mainloop()


if __name__ == "__main__":
    main()
