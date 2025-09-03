import os
import sys
import time
import json
import re
import threading
import array
from enum import Enum
from typing import Union

from PIL import Image, ImageDraw, ImageFont
import pystray
import tkinter as tk

# pystray docs: https://pystray.readthedocs.io/en/latest/index.html
# compile with: pyinstaller --onefile --noconsole .\razer_battery.py

class BatteryStatus:
    def __init__(self, device_name: str, charging_status: str, level: int):
        self.device_name = device_name
        self.charging_status = charging_status
        self.level = level
    device_name: str
    charging_status: str
    level: int

class Error(Enum):
    COULD_NOT_FIND_LOGGING_DIRECTORY = 0
    COULD_NOT_FIND_LOG_FILE = 1
    FAILED_TO_PARSE_LOG_FILE = 2

def load_font(filename, size) -> ImageFont.FreeTypeFont:
    try:
        font = ImageFont.truetype(filename, size)
    except:
        font = ImageFont.load_default(size)
    return font

def get_font(text, max_width, max_height) -> ImageFont.FreeTypeFont:
    '''Returns a font with maximum size, either ariblk or the system default'''
    size = 20
    while True:
        font = load_font('ariblk.ttf', size)
        dummy_img = Image.new("RGBA", (max_width, max_height))
        draw = ImageDraw.Draw(dummy_img)
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width > max_width or height > max_height:
            break
        size += 2
    return load_font('ariblk.ttf', size - 2)

def get_foreground_color(text) -> tuple[int, int, int]:
    '''Returns the RGB value of the text, depending on the numberic value. The lower the redder.'''
    if not isinstance(text, (int, float)):
        return (0, 0, 0)        # black
    elif text >= 80:
        return (98, 252, 3)     # green
    elif text >= 60:
        return (175, 255, 3)    # lime
    elif text >= 40:
        return (255, 210, 0)    # light orange
    elif text >= 20:
        return (255, 137, 0)    # orange
    else:
        return (255, 0, 0)      # red

def create_number_image(number) -> Image.Image:
    '''Creates an image from a number. Number may be a string.'''
    width = 256
    height = 256
    foreground = get_foreground_color(number)
    
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    text = f"{number}"
    font = get_font(text, width, height)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = (width - text_width) // 2
    text_y = (height - text_height) // 2 - bbox[1]
    draw.text((text_x, text_y), text, fill=foreground, font=font)
    return image

def parse_log_file(filepath) -> array.array[BatteryStatus]:
    '''Parses a log file for all devices'''
    extraction_regex = re.compile(r'({.*})')
    product_ids = []
    battery_stati = []
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in reversed(f.readlines()):
            try:
                raw_json = extraction_regex.search(line).group(1)
                outer_data = json.loads(raw_json)
                data = json.loads(outer_data["newValue"])
                id = data["productId"]
                name = data["productName"]["en"]
                charging_status = data["powerStatus"]["chargingStatus"]
                level = data["powerStatus"]["level"]
            except:
                continue
            if id in product_ids:
                continue
            product_ids.append(id)
            battery_stati.append(BatteryStatus(name, charging_status, level))
    return battery_stati

def get_battery_stati() -> Union[array.array[BatteryStatus], Error]:
    '''Finds the latest logfile and parses for the current Battery Status.'''
    log_dir = os.path.join(os.environ['LOCALAPPDATA'], 'Razer', 'RazerAppEngine', 'User Data', 'Logs')
    if not os.path.exists(log_dir):
        return Error.COULD_NOT_FIND_LOGGING_DIRECTORY
    pattern = re.compile(r'^background-manager(?:\d+)?\.log$')
    max_num = -1
    latest_file = None
    for filename in os.listdir(log_dir):
        match = pattern.match(filename)
        if match:
            # Zahl extrahieren, wenn vorhanden – sonst 0
            num_part = re.search(r"\d+", filename)
            num = int(num_part.group()) if num_part else 0

            if num > max_num:
                max_num = num
                latest_file = filename
    if latest_file is None:
        return Error.COULD_NOT_FIND_LOG_FILE
    full_path = os.path.join(log_dir, latest_file)
    stati = parse_log_file(full_path)
    if stati == []:
        return Error.FAILED_TO_PARSE_LOG_FILE
    return stati

def update_window(title_text):
    global optional_window
    if optional_window == None:
        return
    for widget in optional_window.winfo_children():
        widget.destroy()
    window_label = tk.Label(optional_window, text=title_text, font=("Arial", 20), foreground="Black")
    window_label.pack(padx=20, pady=20)

def on_close_window():
    global optional_window
    optional_window.destroy()
    optional_window = None

def on_show_as_window():
    if optional_window != None:
        return
    def thread_func():
        global optional_window
        optional_window = tk.Tk()
        optional_window.attributes("-topmost", True)
        optional_window.resizable(False, False)
        optional_window.title("Razer Battery Display")
        optional_window.protocol("WM_DELETE_WINDOW", on_close_window)
        optional_window.mainloop()
    threading.Thread(target=thread_func, daemon=True).start()

def on_quit(icon):
    icon.stop()
    sys.exit()

def update_loop(icon):
    '''The main loop of the programm. Periodically checks for new battery status.
    Must run in a seperate Thread.'''
    while True:
        stati = get_battery_stati()
        if isinstance(stati, Error):
            title_text = f"Error: {stati}\n"
            icon_img = create_number_image("!")
        else:
            lowest_battery = 100
            title_text = ""
            for i, status in enumerate(stati):
                if i > 0:
                    title_text += "\n"
                title_text += f"{status.device_name} - {status.level}%"
                lowest_battery = min(lowest_battery, status.level)
            icon_img = create_number_image(lowest_battery)
        update_window(title_text)
        icon.icon = icon_img
        icon.title = title_text[:128]
        time.sleep(10)

def main():
    icon = pystray.Icon(name='Razer Battery Display',
        icon=create_number_image("..."),
        title="Razer Battery Status")
    icon.menu = pystray.Menu(
        pystray.MenuItem('Quit', on_quit),
        pystray.MenuItem('Show as window', on_show_as_window)
    )
    threading.Thread(target=update_loop, args=(icon,), daemon=True).start()
    icon.run()

optional_window = None

if __name__ == '__main__':
    main()