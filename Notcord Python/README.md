# Notcord 🚀
> **Discord Message & Favorite GIF Purger**  
> **Author:** **Qorelith**

---

<p align="center">
  <img src="assets/logo.png" width="160" alt="Notcord Logo" />
</p>

## 🌟 Features

- ⚡ **Turbo-Fast Deletion (~5-7 Messages/Second):** Persistent HTTP connections (Keep-Alive) and a configurable delay (`0.15s` default, ranging from `0.05s - 3.50s`) to wipe messages rapidly.
- ➕ **Target by ID:** Easily clear chats by entering a User ID (even if not friends) or any Channel ID directly.
- 💬 **Targeted DM & Group Purging:** Clean your messages across Direct Messages (DMs), Group Chats, or Server Channels.
- ⚡ **Advanced Message Filters:**
  - *All Messages:* Deletes all your messages within the selected timeframe.
  - *Images Only:* Removes only messages containing images/photos.
  - *GIFs Only:* Cleans messages containing GIFs.
  - *Plain Text Only:* Deletes text-only messages containing no media.
- ⏳ **Timeframe Options:**
  - Past 1 Hour
  - Past 6 Hours
  - Past 24 Hours (1 Day)
  - Past 7 Days
  - Past 30 Days
  - Custom Duration (Specify hours or days)
  - All Time (Unlimited)
- ⭐ **Favorite GIF Purger:** Remove all favorited GIFs from your account or filter them by specific time ranges (e.g., last 6 months / first 6 months) with a single click.
- 🖥 **Live Event Console:** Real-time colored terminal logging showing deleted message IDs, content previews, and Discord rate limit (429) statuses.
- 🛑 **Safe Stop:** Pause or stop the deletion process at any time.
- 🌐 **Five Language Support:** Dynamic one-click switching between English, Turkish, Spanish, Portuguese, and Russian.
- 🎨 **Discord-Inspired Modern UI:** Crafted with CustomTkinter featuring a sleek red, dark gray, black, and white color scheme.

---

## 🛠 Installation & Usage

## 📥 For Users (The Easy Way)
If you just want to use the program:
1. Go to the **Releases** section on the right sidebar.
2. Download the `.exe` file from the latest release.
3. Run it directly! (No extra Python or library installation **required**).

## 💻 For Developers (Source Code)
If you want to inspect the code or contribute:

Install the required libraries:
```bash
pip install -r requirements.txt