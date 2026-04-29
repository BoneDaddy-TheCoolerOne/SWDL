import os
import sys
import shutil
import subprocess
import re
import asyncio
import aiohttp
from pathlib import Path
import json
import zipfile
import requests
from selectolax.parser import HTMLParser
import logging

logging.basicConfig(level=logging.DEBUG,
format='%(asctime)s - %(levelname)s - %(message)s',
filename='workshop_downloader.log',
filemode='w')

TEXTS = {
    "en": {
        "main_menu_title": "Steam Workshop Downloader",
        "credits": "Original by notSeilce on github - Forked by Frakess",
        "main_menu_current_game": "Current Game: {game_name} [ID: {game_id}]",
        "main_menu_no_game_selected": "No game selected!",
        "main_menu_items_with_game": ["1. Download mods from URLs", "2. Download mods from collection", "3. Change Game", "4. Exit"],
        "main_menu_items_no_game": ["1. Select Game", "2. Exit"],
        "main_menu_prompt": "Choose an action: ",
        "setup_game_title": "Game Setup",
        "setup_game_instruction": "Insert game id (press enter to default to Source Filmmaker)",
        "setup_game_example": "Or enter Steam link (e.g., https://store.steampowered.com/app/108600/Project_Zomboid/)",
        "setup_game_link_prompt": "Input: ",
        "setup_game_invalid_input": "\nInvalid input. Please try again.\n",
        "install_mods_urls_instructions": "Paste Steam Workshop mod links\nPress Enter twice to finish (or 'x' to cancel)",
        "install_mods_urls_downloaded_message": "\nProcess finished. Press Enter to continue...",
        "install_mods_collection_instruction_link": "Enter the Steam Workshop Collection link",
        "install_mods_collection_mods_found": "\nCollection: {name}\nMods found: {count}",
        "install_mods_collection_confirm_install": "\nStart downloading into collection folder? (y/n): ",
        "steamclient_not_found": "steamclient.dll not found. Initializing SteamCMD binaries...",
        "steamcmd_not_found_error": "SteamCMD not found. Installing...",
        "steamclient_exit_prompt": "Press Enter to exit...",
        "install_mod_process_installing_mod": "Downloading mod [{mod_title}]...",
        "install_mod_process_mod_already_exists": "Mod [{mod_title}] is already installed.",
        "general_separator": "─" * 47,
        "general_cls": 'cls' if os.name == 'nt' else 'clear',
    }
}

CURRENT_LANG = "en"
TEXT = TEXTS[CURRENT_LANG]
STEAMCMD_DOWNLOAD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

class SteamWorkshopDownloader:
    def __init__(self):
        self.script_dir = Path(os.path.dirname(sys.executable)) if getattr(sys, 'frozen', False) else Path(__file__).parent.absolute()
        self.steamcmd_dir = self.script_dir / "main" / "SteamCMD"
        self.steamcmd_path = self.steamcmd_dir / "steamcmd.exe"
        self.steamclient_path = self.steamcmd_dir / "steamclient.dll"
        self.base_downloads_path = self.script_dir / "Downloads"
        self.game_name = None
        self.game_id = None
        self.game_folder = None
        self.mods_path = None
        self.config_path = self.script_dir / "main" / "config.json"
        self.installed_mods_path = self.script_dir / "main" / "installed_mods.json"
        self.installed_mods = self.load_installed_mods()

        self.check_and_install_steamcmd()
        self.check_and_install_steamclient()
        self.load_config()

        if not self.game_id:
            self.setup_game()

    def check_and_install_steamcmd(self):
        if not self.steamcmd_path.exists():
            print(TEXT["steamcmd_not_found_error"])
            self.steamcmd_dir.mkdir(parents=True, exist_ok=True)
            try:
                response = requests.get(STEAMCMD_DOWNLOAD_URL, stream=True)
                zip_path = self.steamcmd_dir / "steamcmd.zip"
                with open(zip_path, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        file.write(chunk)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(self.steamcmd_dir)
                os.remove(zip_path)
            except Exception as e:
                self._exit_with_error(f"SteamCMD Download Error: {e}")

    def check_and_install_steamclient(self):
        if not self.steamclient_path.exists():
            print(TEXT["steamclient_not_found"])
            try:
                subprocess.run([str(self.steamcmd_path), '+quit'], capture_output=True)
            except Exception as e:
                self._exit_with_error(f"SteamCMD Initialization Error: {e}")
            
            if not self.steamclient_path.exists():
                 self._exit_with_error("SteamCMD failed to fetch binaries. Try running steamcmd.exe manually.")

    def _exit_with_error(self, message):
        print(f"\n[!] ERROR: {message}")
        logging.error(message)
        input(TEXT["steamclient_exit_prompt"])
        sys.exit(1)

    def load_config(self):
        if not self.config_path.exists(): return
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            self.game_name = config.get('GAME_NAME', '').strip('"')
            self.game_id = config.get('GAME_ID')
            self.game_folder = config.get('GAME_FOLDER')
            if self.game_folder:
                self.mods_path = self.base_downloads_path / self.game_folder
        except Exception as e:
            logging.error(f"Config load error: {e}")

    def save_config(self):
        config = {'GAME_NAME': f'"{self.game_name}"', 'GAME_ID': self.game_id, 'GAME_FOLDER': self.game_folder}
        self.script_dir.joinpath("main").mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as configfile:
            json.dump(config, configfile, indent=4)

    def clean_folder_name(self, name):
        cleaned = re.sub(r'[\/:*?"<>|]', '', name).strip().replace(" ", "_")
        return cleaned[:50]

    def fetch_game_name(self, app_id):
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get(app_id) and data[app_id].get('success'):
                    return data[app_id]['data']['name']
        except Exception as e:
            logging.error(f"Failed to fetch game name for {app_id}: {e}")
        return f"Game_{app_id}"

    def setup_game(self):
        os.system(TEXT["general_cls"])
        print(f"\n{TEXT['general_separator']}\n {TEXT['setup_game_title']}\n{TEXT['general_separator']}")
        print(f"{TEXT['setup_game_instruction']}\n")
        
        while True:
            game_input = input(TEXT["setup_game_link_prompt"]).strip()
            app_id = "1840" if not game_input else None
            
            if not app_id:
                if game_input.isdigit():
                    app_id = game_input
                else:
                    match = re.search(r'/app/(\d+)', game_input)
                    if match:
                        app_id = match.group(1)
            
            if app_id:
                print(f"Fetching game info for ID: {app_id}...")
                self.game_id = app_id
                self.game_name = self.fetch_game_name(app_id)
                break
                
            print(TEXT["setup_game_invalid_input"])

        self.game_folder = self.clean_folder_name(self.game_name)
        self.mods_path = self.base_downloads_path / self.game_folder
        os.makedirs(self.mods_path, exist_ok=True)
        self.save_config()

    def load_installed_mods(self):
        if self.installed_mods_path.exists():
            try:
                with open(self.installed_mods_path, 'r') as f: return json.load(f)
            except: return []
        return []

    def save_installed_mods(self):
        with open(self.installed_mods_path, 'w') as f:
            json.dump(self.installed_mods, f, indent=4, ensure_ascii=False)

    async def fetch_mod_info(self, mod_id):
        url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        text = await response.text()
                        parser = HTMLParser(text)
                        title_node = parser.css_first('div.workshopItemTitle')
                        title = title_node.text(strip=True) if title_node else mod_id
                        
                        game_link = parser.css_first('a[href*="/app/"]')
                        if game_link:
                            found_id = re.search(r'/app/(\d+)', game_link.attributes['href'])
                            if found_id and found_id.group(1) != self.game_id:
                                return title, False, found_id.group(1)
                        return title, True, self.game_id
        except Exception as e:
            logging.error(f"Error fetching mod info for {mod_id}: {e}")
        return mod_id, True, self.game_id

    def extract_with_7z(self, archive_path, extract_path):
        seven_zip = "7z"
        if os.name == 'nt':
            default_path = Path(r"C:\Program Files\7-Zip\7z.exe")
            if default_path.exists(): seven_zip = str(default_path)
        cmd = [seven_zip, "x", str(archive_path), f"-o{extract_path}", "-y"]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except: return False

    async def install_mod(self, mod_id, semaphore, custom_dest=None):
        mod_title, is_match, correct_appid = await self.fetch_mod_info(mod_id)
        cleaned_title = self.clean_folder_name(mod_title)
        target_base = custom_dest if custom_dest else self.mods_path
        dest = target_base / cleaned_title
        
        if dest.exists():
            print(TEXT["install_mod_process_mod_already_exists"].format(mod_title=mod_title))
            return

        if not is_match:
            err = f"ID Mismatch! Mod [{mod_title}] belongs to AppID {correct_appid}, not {self.game_id}."
            print(f"[!] ERROR: {err}")
            logging.error(err)
            return

        async with semaphore:
            print(TEXT["install_mod_process_installing_mod"].format(mod_title=mod_title))
            temp_path = self.script_dir / "temp" / mod_id
            os.makedirs(temp_path, exist_ok=True)
            
            cmd = [str(self.steamcmd_path), "+force_install_dir", str(temp_path), "+login", "anonymous", "+workshop_download_item", self.game_id, mod_id, "+quit"]
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await process.communicate()
            
            logging.debug(f"--- Mod ID: {mod_id} ---\nSTDOUT:\n{stdout.decode()}\nSTDERR:\n{stderr.decode()}")
            
            mod_src = temp_path / "steamapps" / "workshop" / "content" / self.game_id / mod_id
            
            if not mod_src.exists() or not any(mod_src.iterdir()):
                print(f"[!] FAILED: {mod_title} ({mod_id})")
            else:
                os.makedirs(dest, exist_ok=True)
                bin_files = list(mod_src.rglob("*.bin"))
                if bin_files:
                    for b in bin_files: self.extract_with_7z(b, dest)
                else:
                    src_files = mod_src / "mods" if (mod_src / "mods").exists() else mod_src
                    await asyncio.to_thread(shutil.copytree, src_files, dest, dirs_exist_ok=True)
                
                with open(dest / "metadata.json", 'w', encoding='utf-8') as f:
                    json.dump({"id": mod_id, "title": mod_title, "workshop_id": mod_id}, f, indent=4)
                
                self.installed_mods.append(f"{target_base.name}/{cleaned_title}")
                self.save_installed_mods()
                print(f"    Successfully installed to: {dest.relative_to(self.script_dir)}")

            await asyncio.to_thread(shutil.rmtree, temp_path, ignore_errors=True)

    async def _run_downloads(self, ids, custom_dest=None):
        semaphore = asyncio.Semaphore(5)
        await asyncio.gather(*[self.install_mod(i, semaphore, custom_dest) for i in ids])

    def main_menu(self):
        while True:
            os.system(TEXT["general_cls"])
            print(f"{TEXT['main_menu_title']}\n{TEXT['general_separator']}")
            print(f"{TEXT['credits']}\n{TEXT['general_separator']}")
            if self.game_name:
                print(TEXT['main_menu_current_game'].format(game_name=self.game_name, game_id=self.game_id))
                print(f"{TEXT['general_separator']}\n" + "\n".join(TEXT["main_menu_items_with_game"]))
            else:
                print(TEXT['main_menu_no_game_selected'] + "\n" + "\n".join(TEXT["main_menu_items_no_game"]))
            print(f"\n{TEXT['general_separator']}\n{TEXT['main_menu_prompt']}")
            choice = input().strip()
            if self.game_name:
                if choice == "1": self.install_from_urls()
                elif choice == "2": self.install_from_collection()
                elif choice == "3": self.setup_game()
                elif choice == "4": sys.exit(0)
            else:
                if choice == "1": self.setup_game()
                elif choice == "2": sys.exit(0)

    def install_from_urls(self):
        os.system(TEXT["general_cls"])
        print(f"{TEXT['install_mods_urls_instructions']}\n")
        urls = []
        while True:
            url = input().strip()
            if url.lower() == 'x': return
            if not url:
                if urls: break
                else: continue
            urls.append(url)
        ids = [m.group(1) for u in urls if (m := re.search(r'[?&]id=(\d+)', u))]
        if ids: asyncio.run(self._run_downloads(ids))
        input(TEXT["install_mods_urls_downloaded_message"])

    def install_from_collection(self):
        os.system(TEXT["general_cls"])
        print(f"{TEXT['install_mods_collection_instruction_link']}")
        url = input().strip()
        if url.lower() == 'x': return
        
        coll_match = re.search(r'id=(\d+)', url)
        if not coll_match:
            print("Invalid collection link.")
            input("Press Enter...")
            return
            
        coll_id = coll_match.group(1)
        try:
            async def parse_collection():
                async with aiohttp.ClientSession() as s:
                    async with s.get(url) as r:
                        if r.status == 200:
                            h = HTMLParser(await r.text())
                            name_node = h.css_first('div.workshopItemTitle')
                            coll_name = name_node.text(strip=True) if name_node else "Collection"
                            ids = list(set(re.search(r'id=(\d+)', a.attributes['href']).group(1) 
                                          for a in h.css('a') 
                                          if a.attributes.get('href') and 'id=' in a.attributes['href'] and 'sharedfiles' in a.attributes['href']))
                            # Filter out the collection ID itself from the items list
                            ids = [i for i in ids if i != coll_id]
                            return coll_name, ids
            
            name, ids = asyncio.run(parse_collection())
            if ids:
                print(TEXT["install_mods_collection_mods_found"].format(name=name, count=len(ids)))
                if input(TEXT["install_mods_collection_confirm_install"]).lower() == 'y':
                    coll_folder = self.clean_folder_name(f"{name}_{coll_id}")
                    custom_path = self.mods_path / coll_folder
                    os.makedirs(custom_path, exist_ok=True)
                    asyncio.run(self._run_downloads(ids, custom_dest=custom_path))
                    input(TEXT["install_mods_urls_downloaded_message"])
            else:
                print("No items found in this collection.")
                input("Press Enter...")
        except Exception as e:
            logging.error(f"Collection error: {e}")
            print(f"Error: {e}")
            input("Press Enter...")

if __name__ == "__main__":
    SteamWorkshopDownloader().main_menu()
