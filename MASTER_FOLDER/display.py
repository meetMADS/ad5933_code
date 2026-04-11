#Header Files
import os
import gc
import time
import sys
from machine import Pin, SPI
from ili9341xnew import ILI9341
import glcdfont
import ad5933
import math
import ic_code

# ================== Colors (RGB565) ==================
def color565(r, g, b):
    return (r & 0xf8) << 8 | (g & 0xfc) << 3 | b >> 3

BLACK      = color565(0, 0, 0)
WHITE      = color565(255, 255, 255)
DARK_GRAY  = color565(50, 50, 50)
GRAY       = color565(80, 80, 80)
LIGHT_GRAY = color565(180, 180, 180)
BLUE       = color565(40, 130, 190)
LIGHT_BLUE = color565(100, 150, 255)
GREEN      = color565(60, 170, 90)
GREEN_PLOT = color565(0, 255, 0)
YELLOW     = color565(210, 170, 30)
PURPLE     = color565(150, 80, 170)

# ================== TFT Pins & Init (SPI0) ==================
TFT_MISO_PIN = 16
TFT_CS_PIN   = 17
TFT_CLK_PIN  = 18
TFT_MOSI_PIN = 19
TFT_DC_PIN   = 20
TFT_RST_PIN  = 21
spi = SPI(0, baudrate=40000000, miso=Pin(TFT_MISO_PIN), mosi=Pin(TFT_MOSI_PIN), sck=Pin(TFT_CLK_PIN))
# 320x240 Landscape Mode
display = ILI9341( spi, cs=Pin(TFT_CS_PIN), dc=Pin(TFT_DC_PIN), rst=Pin(TFT_RST_PIN), w=320, h=240,r=1)
display.set_font(glcdfont)

# =============================== RAW FILE VIEWER ====================
def draw_raw_image(filename, x, y, width, height, display):
    """
    Reads a raw RGB565 image file in chunks and streams it to the ILI9341.
    """
    try:
        os.stat(filename) 
        with open(filename, "rb") as f:
            # 1. Set the drawing window on the display.
            # The library expects coordinates to be inclusive, so we subtract 1.
            display._writeblock(x, y, x + width - 1, y + height - 1, None)
            # 2. Buffer setup: width * 2 bytes/pixel * 10 rows
            buf = bytearray(width * 2 * 10)
            while True:
                bytes_read = f.readinto(buf)
                if not bytes_read:
                    break # End of file reached
                # 3. Stream data via SPI. 
                # We use memoryview() so that on the final, smaller chunk of the file, 
                # we only send the exact bytes read rather than the whole buffer.
                display._data(memoryview(buf)[:bytes_read]) 
    except OSError as e:
        # print(f"File error: {e}. Check if '{filename}' is uploaded.")
        pass
    finally:
        gc.collect()

# ================== BATTERY =============================
def update_battery_display(percent):
    percent = max(0, min(100, int(percent)))
    bx, by, bw, bh = 280, 9, 10, 24
    draw_outline(bx, by, bw, bh, BLACK)
    fill_h = int((percent / 100.0) * (bh - 2))
    fill_y = by + 1 + (bh - 2 - fill_h)
    if fill_h > 0:
        display.fill_rectangle(bx + 1, fill_y, bw - 2, fill_h, BLACK)
    display.fill_rectangle(290, 9, 25, 24, BLUE)
    display.set_color(WHITE, BLUE)
    center_text(f"{percent}%", 290, 9, 25, 24)

# ===================== DRAWING HEADER FILES =========================
def draw_big_header(text, hdr_h, bg_color, text_color):
    """Draws a scaled-up header to bypass the 6x8 font limitation."""
    display.fill_rectangle(0, 0, 320, hdr_h, bg_color)
    char_w = 5 * 3
    char_h = 7 * 3
    gap = 1 * 3
    total_w = len(text) * (char_w + gap) - gap
    start_x = (320 - total_w) // 2
    start_y = (hdr_h - char_h) // 2
    display.set_color(text_color, bg_color)
    display.big_chars(text, start_x, start_y)
    display.set_color(WHITE, BLACK)
    
def draw_outline(x, y, w, h, color, thickness=1):
    """Draws a rectangular border with a specific color and thickness."""
    display.fill_rectangle(x, y, w, thickness, color)                  # Top edge
    display.fill_rectangle(x, y + h - thickness, w, thickness, color)  # Bottom edge
    display.fill_rectangle(x, y, thickness, h, color)                  # Left edge
    display.fill_rectangle(x + w - thickness, y, thickness, h, color)  # Right edge

def center_text(text, box_x, box_y, box_w, box_h):
    """Centers text precisely inside any given box dimensions."""
    text_width = len(text) * 6  # glcdfont characters are 6px wide
    text_height = 8             # glcdfont characters are 8px tall
    # Calculate offsets to perfectly center the text
    pos_x = box_x + (box_w - text_width) // 2
    pos_y = box_y + (box_h - text_height) // 2
    display.chars(text, pos_x, pos_y)
    
def draw_back_arrow(x, y, color):
    """Draws a blocky left-pointing back arrow using filled rectangles."""
    # Arrowhead (Left-pointing triangle built with vertical slices)
    display.fill_rectangle(x, y + 6, 2, 4, color)       # Arrow tip
    display.fill_rectangle(x + 2, y + 4, 2, 8, color)
    display.fill_rectangle(x + 4, y + 2, 2, 12, color)
    display.fill_rectangle(x + 6, y, 2, 16, color)      # Widest part of head
    display.fill_rectangle(x + 8, y + 5, 16, 6, color)  # Horizontal body
    

# =================== DRAW THE MENU PAGE ==================
btn_w = 65
btn_h = 130
btn_y = 65
b1_x = 12  
b2_x = b1_x + btn_w + 12
b3_x = b2_x + btn_w + 12
b4_x = b3_x + btn_w + 12

def draw_menu():
    display.fill_rectangle(0, 0, 320, 240, DARK_GRAY)
    draw_big_header("WELCOME USER", 42, bg_color=BLUE, text_color=WHITE)
    #update_battery_display(75)                                      --- Uncomment for Battery

    # --- Block 1: Single Measure (GREEN) ---
    display.fill_rectangle(b1_x, btn_y, btn_w, btn_h, GREEN)
    draw_outline(b1_x, btn_y, btn_w, btn_h, LIGHT_GRAY)
    display.set_color(WHITE, GREEN) # Match text background to button color
    center_text("CUSTOM", b1_x, btn_y + 5, btn_w, 20)
    center_text("MODE", b1_x, btn_y + 20, btn_w, 20)
    cx1 = b1_x + (btn_w // 2)
    cy1 = btn_y + 48
    display.fill_rectangle(cx1 - 12, cy1, 4, 24, DARK_GRAY)       # Track
    display.fill_rectangle(cx1 - 16, cy1 + 4, 12, 6, WHITE)       # Knob (High)
    display.fill_rectangle(cx1 - 2, cy1, 4, 24, DARK_GRAY)        # Track
    display.fill_rectangle(cx1 - 6, cy1 + 14, 12, 6, WHITE)       # Knob (Low)
    display.fill_rectangle(cx1 + 8, cy1, 4, 24, DARK_GRAY)        # Track
    display.fill_rectangle(cx1 + 4, cy1 + 8, 12, 6, WHITE)        # Knob (Mid)
    display.set_color(WHITE, GREEN)
    center_text("SET", b1_x, btn_y + 80, btn_w, 20)
    center_text("VALUE", b1_x, btn_y + 95, btn_w, 20)

    # --- Block 2: Data Sweep (BLUE) ---
    display.fill_rectangle(b2_x, btn_y, btn_w, btn_h, BLUE)
    draw_outline(b2_x, btn_y, btn_w, btn_h, LIGHT_GRAY)
    display.set_color(WHITE, BLUE)
    center_text("SWEEP", b2_x, btn_y + 5, btn_w, 20)
    cx2 = b2_x + (btn_w // 2)
    cy2 = btn_y + 65 # Base of the chart
    display.fill_rectangle(cx2 - 14, cy2, 28, 2, WHITE)
    display.fill_rectangle(cx2 - 12, cy2 - 8, 6, 8, WHITE)
    display.fill_rectangle(cx2 - 3, cy2 - 16, 6, 16, WHITE)
    display.fill_rectangle(cx2 + 6, cy2 - 24, 6, 24, WHITE)
    display.set_color(WHITE, BLUE)
    center_text("CHOOSE", b2_x, btn_y + 80, btn_w, 20)
    center_text("MODE", b2_x, btn_y + 95, btn_w, 20)
    
    # --- Block 3: Check Data (YELLOW) ---
    display.fill_rectangle(b3_x, btn_y, btn_w, btn_h, YELLOW)
    draw_outline(b3_x, btn_y, btn_w, btn_h, LIGHT_GRAY)
    display.set_color(WHITE, YELLOW)
    center_text("CHECK", b3_x, btn_y + 5, btn_w, 20)
    center_text("DATA", b3_x, btn_y + 20, btn_w, 20)
    icon_w = 24
    icon_h = 32
    icon_x = b3_x + (btn_w - icon_w) // 2  # Center horizontally in the button
    icon_y = btn_y + 42                    # Place it nicely between the text blocks
    display.fill_rectangle(icon_x, icon_y, icon_w, icon_h, WHITE)
    display.fill_rectangle(icon_x + icon_w - 8, icon_y + 8, 8, 8, LIGHT_GRAY)
    display.fill_rectangle(icon_x + 4, icon_y + 12, 16, 2, DARK_GRAY)
    display.fill_rectangle(icon_x + 4, icon_y + 18, 16, 2, DARK_GRAY)
    display.fill_rectangle(icon_x + 4, icon_y + 24, 10, 2, DARK_GRAY) # Shorter line
    display.set_color(WHITE, YELLOW)
    center_text("CHECK", b3_x, btn_y + 80, btn_w, 20)
    center_text("DATA", b3_x, btn_y + 95, btn_w, 20)

    # --- Block 4: Other Options (PURPLE) ---
    display.fill_rectangle(b4_x, btn_y, btn_w, btn_h, PURPLE)
    draw_outline(b4_x, btn_y, btn_w, btn_h, LIGHT_GRAY)
    display.set_color(WHITE, PURPLE)
    center_text("CREDITS", b4_x, btn_y + 5, btn_w, 20)
    
    cx = b4_x + (btn_w // 2)
    cy = btn_y + 40 + 12  
    
    # --- NEW HEART ICON ---
    display.fill_rectangle(cx - 8, cy - 10, 6, 6, WHITE)  # Left top hump
    display.fill_rectangle(cx + 2, cy - 10, 6, 6, WHITE)  # Right top hump
    display.fill_rectangle(cx - 10, cy - 4, 20, 8, WHITE) # Main upper body
    display.fill_rectangle(cx - 8, cy + 4, 16, 4, WHITE)  # Middle taper
    display.fill_rectangle(cx - 4, cy + 8, 8, 4, WHITE)   # Lower taper
    display.fill_rectangle(cx - 2, cy + 12, 4, 4, WHITE)  # Bottom tip
    # ----------------------
    
    display.set_color(WHITE, PURPLE)
    center_text("SHOW", b4_x, btn_y + 80, btn_w, 20)
    center_text("CREDITS", b4_x, btn_y + 95, btn_w, 20)
    
    # 4. Footer Block
    footer_y = 210
    box_w = 80
    box_h = 20
    box_x = (320 - box_w) // 2
    # Draw a hollow white box
    draw_outline(box_x, footer_y, box_w, box_h, WHITE)
    # Draw the text perfectly centered inside that new box
    display.set_color(WHITE, DARK_GRAY) 
    center_text("SELECT ONE", box_x, footer_y, box_w, box_h)
    
# ============================ DRAW CREDITS ===============================
def draw_credits():
    display.fill_rectangle(0, 0, 320, 240, DARK_GRAY)
    display.set_color(WHITE, DARK_GRAY)
    center_text("CREDITS", 0, 4, 320, 12)
    display.fill_rectangle(0, 20, 320, 1, WHITE)
    # 2. Centered Text Structure; Tuple format: (Text string, Y-coordinate)
    lines = [
        ("Made with Love by", 35),
        ("Darsh Patel", 55),
        ("Yaswanth Ram Kumar", 70),
        ("Meet Agrawal", 85),
        ("Arnav Bhate", 100),
        ("Aditya Jungade", 115),
        ("Guided by", 145),
        ("Prof. S. Tallur     Prof. S. Mulleti", 160),
        ("Special Thanks to", 190),
        ("Maheshwar Sir       Ankur Sir", 205)
    ]
    for text, y in lines:
        center_text(text, 0, y, 320, 8)   
    display.fill_rectangle(0, 225, 320, 1, WHITE)
    center_text("PRESS BACK TO RETURN", 0, 228, 320, 10)


# ====================== DRAW THE FILES PAGE =================================
files_list = []
current_plot_file = ""
row_h = 25
col1_w = 40
header_h = 42
file_cursor_idx = 0          # Tracks which file is selected (0 to len-1)

def update_files_list():
    """Reads the directory and updates the global list."""
    global files_list
    try:
        files_list = os.listdir('/Sweeps') 
    except OSError:
        files_list = ["Error Reading FS"]

def draw_files():
    """Full-redraw of the Files page (called once on state entry)."""
    update_files_list()
    global file_cursor_idx
    file_cursor_idx = 0
    display.fill_rectangle(0, 0, 320, 240, DARK_GRAY)
    draw_big_header("FILES", header_h, BLUE, WHITE)
    #update_battery_display(75)                         --- Uncomment for Battery
    draw_back_arrow(15, 13, WHITE)
    display.fill_rectangle(0, 0, 320, 2, WHITE)
    display.fill_rectangle(0, 0, 2, 240, WHITE)
    display.fill_rectangle(319, 0, 2, 240, WHITE)
    display.fill_rectangle(0, 239, 320, 2, WHITE)     # Bottom
    # Horizontal line separating header from the file list
    display.fill_rectangle(0, header_h, 320, 2, WHITE)
    render_files_list(-1, 0)
    
# ─────────────────────────────────────────────────────────────────────────────
#  OPTIMISED FILE-LIST RENDERER
#
#  old_idx = -1  →  full redraw (used on first open / after deletion).
#  Otherwise only old_idx and new_idx rows are repainted, avoiding the
#  full-screen refresh that caused the original scrolling lag.
# ─────────────────────────────────────────────────────────────────────────────
def render_files_list(old_idx=-1, new_idx=0):
    start_y = header_h + 2
    if not files_list or files_list[0] == "Error Reading FS":
        display.set_color(WHITE, DARK_GRAY)
        center_text("NO FILES FOUND", 0, 100, 320,20)
        return
    
    repaint = set(range(len(files_list))) if old_idx == -1 else {old_idx, new_idx}
    
    for i in repaint:
        if i >= len(files_list):
            continue
        row_y = start_y + i * row_h
        if row_y + row_h > 239:
            break
        background_color = LIGHT_GRAY if i == new_idx else DARK_GRAY
        display.fill_rectangle(2, row_y, 316, row_h, background_color)
        display.fill_rectangle(col1_w, row_y, 2, row_h, WHITE)
        display.fill_rectangle(2, row_y + row_h - 1, 316, 1, WHITE)
        display.set_color(WHITE, background_color)
        display.chars(str(i + 1), 12, row_y + 8)
        display.chars(files_list[i], col1_w + 10,  row_y + 8)
        
# ===================== SAVE SWEEP DATA =============================
i = 0
def save_sweep_data(sweep_data):
    global i
    """Converts Real/Imaginary to Mag/Phase and saves to a CSV."""
    # 1. Ensure the /Sweeps directory exists
    try:
        os.stat("Sweep")
    except:
        os.mkdir("Sweep")
    # 2. Generate a unique filename by counting existing files
    files = os.listdir("Sweep")
            while i < 10000:
                name = f"{i:04}.csv"
                if name not in files:
                    with open("Sweep/" + name, "w") as f:
                        # 3. Write data to the file
                        # f.write("Frequency,Magnitude,Phase\n") # Header (skipped by plot_it)
                        for freq, real, imag, _ in sweep_data:
                            # Calculate Magnitude and phase
                            # mag = math.sqrt(real**2 + imag**2)
                            # phase = math.atan2(imag, real) * (180.0 / math.pi) 
                            f.write(f"{freq},{real},{imag}\n")
    # print(f"Data successfully saved to {filename}")

# ===================== CUSTOM MODE ================================

custom_start_f = 1000
custom_stop_f = 5100
custom_steps_val = 50
custom_vpp_idx = 2
vpp_options = [1, 2, 3, 4]
custom_cursor_idx = 0    # 0=START, 1=STOP, 2=STEPS, 3=MODE, 4=START BUTTON
custom_edit_mode = False

MULT_VALUES = [1, 10, 100, 1000, 10000]
current_mult_idx = 2  # Starts by editing the 100s place

labels = ["START FREQ:", "STOP FREQ:", "STEPS:", "MODE:"]

def _custom_vals():
    """Always returns fresh display strings from the live state variables."""
    return [
        f"{custom_start_f} Hz",
        f"{custom_stop_f} Hz",
        f"{custom_steps_val}",
        f"{vpp_options[custom_vpp_idx]} Vpp",
    ]

def draw_custom_row(i):
    y_pos = 48 + (i * 30)
    display.fill_rectangle(155, y_pos + 4, 140, 16, DARK_GRAY)
    
    box_color = (GREEN if custom_edit_mode else WHITE) if custom_cursor_idx == i else DARK_GRAY
    draw_outline(12, y_pos, 296, 28, box_color, 2)
    
    display.fill_rectangle(150, y_pos + 2, 156, 24, GRAY)
    display.fill_rectangle(148, y_pos + 2, 2, 24, box_color)
    display.set_color(WHITE, GRAY)
    display.chars(_custom_vals()[i], 160, y_pos + 10)
    
    global current_mult_idx
    if custom_edit_mode and custom_cursor_idx == i and i < 3: 
        # Get the numeric part as a string
        if i == 0:   num_str = str(custom_start_f)
        elif i == 1: num_str = str(custom_stop_f)
        elif i == 2: num_str = str(custom_steps_val)
        
        # Calculate character index from the right
        pos_from_end = current_mult_idx
        
        # Cap the cursor so it doesn't float off to the left if the multiplier is larger than the number
        if pos_from_end >= len(num_str):
            char_idx = 0
        else:
            char_idx = len(num_str) - 1 - pos_from_end
            
        cursor_x = 160 + (char_idx * 6)
        
        # Draw the underline
        display.fill_rectangle(cursor_x, y_pos + 16, 6, 2, GREEN)
    
# Thin public wrappers used by the original call sites
def custom_start():    draw_custom_row(0)
def custom_stop():     draw_custom_row(1)
def custom_steps():    draw_custom_row(2)
def custom_mode_set(): draw_custom_row(3)
        
def custom_sweep():
    """Repaints only the START button at the bottom of Custom Mode."""
    border = WHITE if custom_cursor_idx == 4 else DARK_GRAY
    draw_outline(110, 192, 100, 36, border, 2)
    display.fill_rectangle(112, 194, 96, 32, GREEN)
    display.set_color(WHITE, GREEN)
    center_text("START", 110, 192, 100, 36)

def custom_mode():
    """Full-redraw of the Custom Mode page (called once on state entry)."""
    global custom_cursor_idx, custom_edit_mode, current_mult_idx
    global custom_start_f, custom_stop_f, custom_steps_val, custom_vpp_idx
    
    custom_start_f = 1000
    custom_stop_f = 5100
    custom_steps_val = 50
    custom_vpp_idx = 2
    current_mult_idx = 2
    
    custom_cursor_idx = 0       # Start at the top parameter
    custom_edit_mode = False
    display.fill_rectangle(0, 0, 320, 240, DARK_GRAY)
    draw_big_header("CUSTOM MODE", 42, bg_color=BLUE, text_color=WHITE)
    draw_back_arrow(15, 13, WHITE)
    display.fill_rectangle(0, 0, 320, 2, WHITE)
    display.fill_rectangle(0, 239, 320, 2, WHITE)     # Bottom
    display.fill_rectangle(0, 0, 2, 240, WHITE)       # Left
    display.fill_rectangle(319, 0, 2, 240, WHITE)	  #Right
    display.fill_rectangle(0, 42, 320, 2, WHITE)
    display.fill_rectangle(15, 48, 290, 130, DARK_GRAY)
    display.set_color(WHITE, DARK_GRAY)
    for i in range(4):
        display.chars(labels[i], 30, 55 + i*30 + 6) 
    custom_start(); custom_stop(); custom_steps(); custom_mode_set(); custom_sweep()

# ====================== CHOOSE MODE ================================
selected_mode = 1
MODE_PARAMS = {
    1: (1000.0, 20000.0, 200, 1),
    2: (20000.0, 40000.0, 200, 1),
    3: (40000.0, 60000.0, 200, 1),
    4: (60000.0, 80000.0, 200, 1)
}
UNSELECTED = color565(50, 50, 50)
def draw_box():
    display.fill_rectangle(12, 65, 65, 100, UNSELECTED)
    draw_outline(12, 65, 65, 100, LIGHT_GRAY)
    display.set_color(WHITE, UNSELECTED) 
    center_text("MODE 1", 12, 65, 65, 20)
    center_text("START: 1k", 12, 85, 65, 20)
    center_text("STOP: 20k", 12, 105, 65, 20)
    center_text("STEPS: 200", 12, 125, 65, 20)
    center_text("VPP: 1", 12, 145, 65, 20)
    display.fill_rectangle(89, 65, 65, 100, UNSELECTED)
    draw_outline(89, 65, 65, 100, LIGHT_GRAY)
    display.set_color(WHITE, UNSELECTED) 
    center_text("MODE 2", 89, 65, 65, 20)
    center_text("START: 20k", 89, 85, 65, 20)
    center_text("STOP: 40k", 89, 105, 65, 20)
    center_text("STEPS: 200", 89, 125, 65, 20)
    center_text("VPP: 1", 89, 145, 65, 20)
    display.fill_rectangle(166, 65, 65, 100, UNSELECTED)
    draw_outline(166, 65, 65, 100, LIGHT_GRAY)
    display.set_color(WHITE, UNSELECTED) 
    center_text("MODE 3", 166, 65, 65, 20)
    center_text("START: 40k", 166, 85, 65, 20)
    center_text("STOP: 60k", 166, 105, 65, 20)
    center_text("STEPS: 200", 166, 125, 65, 20)
    center_text("VPP: 1", 166, 145, 65, 20)
    display.fill_rectangle(243, 65, 65, 100, UNSELECTED)
    draw_outline(243, 65, 65, 100, LIGHT_GRAY)
    display.set_color(WHITE, UNSELECTED) 
    center_text("MODE 4", 243, 65, 65, 20)
    center_text("START: 60k", 243, 85, 65, 20)
    center_text("STOP: 80k", 243, 105, 65, 20)
    center_text("STEPS: 200", 243, 125, 65, 20)
    center_text("VPP: 1", 243, 145, 65, 20)

def choose_mode():
    display.fill_rectangle(0, 0, 320, 240, DARK_GRAY)
    draw_big_header("CHOOSE MODE", 42, bg_color=BLUE, text_color=WHITE)
    draw_back_arrow(15, 13, WHITE)
    display.fill_rectangle(0, 0, 320, 2, WHITE)
    display.fill_rectangle(0, 239, 320, 2, WHITE)     # Bottom
    display.fill_rectangle(0, 0, 2, 240, WHITE)       # Left
    display.fill_rectangle(319, 0, 2, 240, WHITE)	  #Right
    display.fill_rectangle(0, 42, 320, 2, WHITE)
    draw_box()

    #START BUTTON
    display.fill_rectangle(128, 180, 64, 45, GREEN)
    draw_outline(128, 180, 64, 45, LIGHT_GRAY)
    display.set_color(WHITE, GREEN) # Match text background to button color
    center_text("START", 128, 185, 64, 40)
    
# ========================= ZOOM PLOTTER ==============================
ZP_L, ZP_R = 40, 285
ZP_T, ZP_B = 15, 220
def big_plot(filename):
    gc.collect()
    
    display.set_color(WHITE, DARK_GRAY)
    display.fill_rectangle(0, 0, 320, 240, DARK_GRAY)

    # Plot boundaries
    display.fill_rectangle(ZP_L, ZP_T, ZP_R - ZP_L, 1, WHITE) # Top
    display.fill_rectangle(ZP_L, ZP_B, ZP_R - ZP_L, 1, WHITE) # Bottom
    display.fill_rectangle(ZP_L, ZP_T, 1, ZP_B - ZP_T, WHITE) # Left
    display.fill_rectangle(ZP_R, ZP_T, 1, ZP_B - ZP_T, WHITE) # Right

    # Mini legend at the very top 
    display.fill_rectangle(ZP_L + 10, 5, 20, 2, GREEN)
    display.chars("MAG", ZP_L + 35, 2)
    display.fill_rectangle(ZP_R - 55, 5, 20, 2, YELLOW)
    display.chars("PHASE", ZP_R - 30, 2)

    # =============================
    # ===========Pass 1============
    # =============================
    f_min, f_max = float('inf'), float('-inf')
    mag_min, mag_max = float('inf'), float('-inf')
    ph_min, ph_max = float('inf'), float('-inf')
    
    try:
        with open(filename, 'r') as f:
            f.readline()
            for line in f:
                parts = line.strip().split(',')
                if len(parts) >= 3:
                    try:
                        freq = float(parts[0])
                        real = float(parts[1])
                        imag  = float(parts[2])
                        mag = math.sqrt(real**2 + imag**2)
                        ph = math.atan2(imag, real) * (180.0 / math.pi)
                        
                        if freq < f_min: f_min = freq
                        if freq > f_max: f_max = freq
                        if mag  < mag_min: mag_min = mag
                        if mag  > mag_max: mag_max = mag
                        if ph   < ph_min: ph_min = ph
                        if ph   > ph_max: ph_max = ph
                    except ValueError:
                        pass
    except OSError:
        center_text("Error: FILE NOT FOUND", 80, 100, 160, 20)
        return
    
    mag_pad = (mag_max - mag_min) * 0.05 if mag_max != mag_min else 1.0
    mag_max += mag_pad
    mag_min -= mag_pad
    
    ph_pad = (ph_max - ph_min) * 0.05 if ph_max != ph_min else 1.0
    ph_max += ph_pad
    ph_min -= ph_pad    
    
    # =============================
    # =======Math & Grid===========
    # =============================
    plot_w = ZP_R - ZP_L
    plot_h = ZP_B - ZP_T
    
    # Increased number of labels for the zoomed plot
    num_x_steps = 6
    num_y_steps = 8
    
    x_steps = [int(ZP_L + i*(plot_w/(num_x_steps-1))) for i in range(num_x_steps)]
    y_steps = [int(ZP_T + i*(plot_h/(num_y_steps-1))) for i in range(num_y_steps)]
    
    x_labels = [format_val(f_min + i*(f_max - f_min)/(num_x_steps-1)) for i in range(num_x_steps)]
    y_labels_L = [format_val(mag_max - i*(mag_max - mag_min)/(num_y_steps-1)) for i in range(num_y_steps)]
    y_labels_R = [format_val(ph_max - i*(ph_max - ph_min)/(num_y_steps-1)) for i in range(num_y_steps)]
    
    # Y-axis grid
    for i in range(num_y_steps):
        y = y_steps[i]
        if 0 < i < num_y_steps - 1:
            for x in range(ZP_L, ZP_R, 4):
                display.pixel(x, y, GRAY)
        display.chars(y_labels_L[i], 2, y - 3)
        display.chars(y_labels_R[i], ZP_R + 5, y - 3)
        
    # X-axis grid
    for i in range(num_x_steps):
        x = x_steps[i]
        if 0 < i < num_x_steps - 1:
            for y in range(ZP_T, ZP_B, 4):
                display.pixel(x, y, GRAY)
        center_text(x_labels[i], x - 15, ZP_B + 5, 30, 15)
    
    # =============================
    # ===========PASS 2============
    # =============================
    prev_x, prev_y_mag, prev_y_ph = None, None, None
    with open(filename, 'r') as f:
        f.readline()
        for line in f:
            parts = line.strip().split(',')
            if len(parts) >= 3:
                try:
                    freq = float(parts[0])
                    real = float(parts[1])
                    imag  = float(parts[2])
                    mag = math.sqrt(real**2 + imag**2)
                    ph = math.atan2(imag, real) * (180.0 / math.pi)
                    
                    x = ZP_L + int(((freq - f_min) / (f_max - f_min))*plot_w)
                    y_mag = ZP_B - int(((mag - mag_min) / (mag_max - mag_min))*plot_h)
                    y_ph = ZP_B - int(((ph - ph_min) / (ph_max - ph_min))*plot_h)
                    
                    x = max(ZP_L, min(ZP_R, x))
                    y_mag = max(ZP_T, min(ZP_B, y_mag))
                    y_ph = max(ZP_T, min(ZP_B, y_ph))
                    
                    if prev_x is not None:
                        draw_line(prev_x, prev_y_mag, x, y_mag, GREEN)
                        draw_line(prev_x, prev_y_ph, x, y_ph, YELLOW)
                    else:
                        display.pixel(x, y_mag, GREEN)
                        display.pixel(x, y_ph, YELLOW)
                    prev_x, prev_y_mag, prev_y_ph = x, y_mag, y_ph
                except ValueError:
                    continue


# ========================== PLOTTER PAGE ==============================
P_L, P_R = 40, 285
P_T, P_B = 35, 175

plotter_cursor_idx = 0

def format_val(v):
    """Formats large numbers into clean, readable strings for the axes."""
    if abs(v) >= 1000000:
        return "{:.1f}M".format(v / 1000000)
    if abs(v) >= 1000:
        return "{:.1f}k".format(v / 1000)
    # For small values, keep 1 decimal place
    return "{:.1f}".format(v)

def draw_line(x0, y0, x1, y1, color):
    """Bresenham's line algorithm for smooth data point connection."""
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        display.pixel(x0, y0, color)
        if x0 == x1 and y0 == y1: break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy

def render_plotter_menu():
    """Redraws the plotter footer menu, updating the highlight."""
    options = ["BACK", "DELETE", "MENU", "ZOOM"]
    for i in range(4):
        plot_bg_color = LIGHT_GRAY if i == plotter_cursor_idx else DARK_GRAY
        # Draw background slightly below the top border (y=201) to protect the line
        display.fill_rectangle(i * 80 + 2, 202, 76, 38, plot_bg_color)
        display.set_color(WHITE, plot_bg_color)
        center_text(options[i], i * 80, 200, 80, 40)

def plot_it(filename):
    gc.collect()
    options = ["BACK", "DELETE", "MENU", "ZOOM"]
    display.set_color(WHITE, DARK_GRAY)
    display.fill_rectangle(0, 0, 320, 240, DARK_GRAY)
    display.chars(f"IMPEDANCE ANALYZER - {filename}", 5, 6)
    display.fill_rectangle(0, 20, 320, 1, WHITE)
    #update_battery_display(75)                     --- Uncomment for Battery
    # Footer Menu
    # Footer Menu (Dynamic)
    global plotter_cursor_idx
    plotter_cursor_idx = 0  # Reset cursor to "BACK"
    for i in range(4):
        plot_bg_color = LIGHT_GRAY if i == 0 else DARK_GRAY
        display.fill_rectangle(i * 80, 201, 80, 39, DARK_GRAY)
        display.fill_rectangle(i * 80 + 2, 202, 76, 38, plot_bg_color)
        display.set_color(WHITE, plot_bg_color)
        center_text(options[i], i * 80, 200, 80, 40)
    display.fill_rectangle(0, 200, 320, 1, WHITE)     # Top horizontal divider
    for i in range(1, 4):
        display.fill_rectangle(i * 80, 200, 1, 40, WHITE)
    
    display.fill_rectangle(P_L, P_T, P_R - P_L, 1, WHITE) # Top
    display.fill_rectangle(P_L, P_B, P_R - P_L, 1, WHITE) # Bottom
    display.fill_rectangle(P_L, P_T, 1, P_B - P_T, WHITE) # Left
    display.fill_rectangle(P_R, P_T, 1, P_B - P_T, WHITE) # Right
    
    display.fill_rectangle(91, 27, 30, 2, GREEN)   
    display.set_color(WHITE, BLACK)
    display.chars("MAG", 126, 24)                  
    
    # 2. Phase Indicator
    display.fill_rectangle(164, 27, 30, 2, YELLOW) 
    display.set_color(WHITE, BLACK)
    display.chars("PHASE", 199, 24)
    
    #=============================
    #===========Pass 1============
    #=============================
    f_min, f_max = float('inf'), float('-inf')
    mag_min, mag_max = float('inf'), float('-inf')
    ph_min, ph_max = float('inf'), float('-inf')
    
    try:
        with open(filename, 'r') as f:
            f.readline()
            for line in f:
                parts = line.strip().split(',')
                if len(parts) >= 3:
                    try:
                        freq = float(parts[0])
                        real = float(parts[1])
                        imag  = float(parts[2])
                        mag = math.sqrt(real**2 + imag**2)
                        ph = math.atan2(imag, real) * (180.0 / math.pi)
                        
                        if freq < f_min: f_min = freq
                        if freq > f_max: f_max = freq
                        if mag  < mag_min: mag_min = mag
                        if mag  > mag_max: mag_max = mag
                        if ph   < ph_min: ph_min = ph
                        if ph   > ph_max: ph_max = ph
                    except ValueError:
                        pass
    except OSError:
        center_text("Error: FILE NOT FOUND", 80, 100, 160, 20)
        return
    
    mag_pad = (mag_max - mag_min) * 0.05 if mag_max != mag_min else 1.0
    mag_max += mag_pad
    mag_min -= mag_pad
    
    ph_pad = (ph_max - ph_min) * 0.05 if ph_max != ph_min else 1.0
    ph_max += ph_pad
    ph_min -= ph_pad    
    
    #=============================
    #=======Math & Grid===========
    #=============================
    
    plot_w = P_R - P_L
    plot_h = P_B - P_T
    
    x_steps = [int(P_L + i*(plot_w/3)) for i in range(4)]
    y_steps = [int(P_T + i*(plot_h/5)) for i in range(6)]
    x_labels = [format_val(f_min + i*(f_max - f_min)/3) for i in range(4)]
    y_labels_L = [format_val(mag_max - i*(mag_max - mag_min)/5) for i in range(6)]
    y_labels_R = [format_val(ph_max - i*(ph_max - ph_min)/5) for i in range (6)]
    
    #Y-axis grid
    for i in range(6):
        y = y_steps[i]
        if 0 < i < 5:
            for x in range(P_L, P_R, 4):
                display.pixel(x, y, GRAY)
        # Left Labels (Impedance)
        display.chars(y_labels_L[i], 2, y - 3)
        # Right Labels (Phase)
        display.chars(y_labels_R[i], P_R + 5, y - 3)
    #X-axis grid
    for i in range(4):
        x = x_steps[i]
        if 0 < i < 4:
            for y in range(P_T, P_B, 4):
                display.pixel(x, y, GRAY)
        center_text(x_labels[i], x - 15, P_B + 5, 30, 15)
    
    #=============================
    #===========PASS 2============
    #=============================
        
    prev_x, prev_y_mag, prev_y_ph = None, None, None
    with open(filename, 'r') as f:
        f.readline()
        for line in f:
            parts = line.strip().split(',')
            if len(parts) >= 3:
                try:
                    freq = float(parts[0])
                    mag  = float(parts[1])
                    ph   = float(parts[2])
                    
                    #Convert pixel to coordinates
                    x = P_L + int(((freq - f_min) / (f_max - f_min))*plot_w)
                    y_mag = P_B - int(((mag - mag_min) / (mag_max - mag_min))*plot_h)
                    y_ph = P_B - int(((ph - ph_min) / (ph_max - ph_min))*plot_h)
                    
                    #Clamp coordinates so we never go out of area
                    x = max(P_L, min(P_R, x))
                    y_mag = max(P_T, min(P_B, y_mag))
                    y_ph = max(P_T, min(P_B, y_ph))
                    
                    if prev_x is not None:
                        draw_line(prev_x, prev_y_mag, x, y_mag, GREEN)
                        draw_line(prev_x, prev_y_ph, x, y_ph, YELLOW)
                    else:
                        display.pixel(x, y_mag, GREEN)
                        display.pixel(x, y_ph, YELLOW)
                    prev_x, prev_y_mag, prev_y_ph = x, y_mag, y_ph
                except ValueError:
                    continue

# ================== ENCODER SETUP ==================
class RotaryEncoder:
    _TABLE = [
        # curr_ab: 00  01  10  11
           0,  -1,  1,  0,   # prev_ab = 00
           1,   0,  0, -1,   # prev_ab = 01
          -1,   0,  0,  1,   # prev_ab = 10
           0,   1, -1,  0,   # prev_ab = 11
    ]
    _STEPS_PER_EVENT = 2    # Tune: 2 for half-step encoders, 4 for full-step

    def __init__(self, pin_a, pin_b, pin_sw):
        self._a  = Pin(pin_a,  Pin.IN, Pin.PULL_UP)
        self._b  = Pin(pin_b,  Pin.IN, Pin.PULL_UP)
        self._sw = Pin(pin_sw, Pin.IN, Pin.PULL_UP)

        self._ab     = (self._a.value() << 1) | self._b.value()
        self._count  = 0       # Running half-step count  (+CW, −CCW)
        self._sw_evt = False
        self._t_sw   = 0       # Timestamp of last switch press
        self._t_enc  = 0       # Timestamp of last encoder edge

        # Both edges on both channels – the state machine handles direction
        self._a.irq( trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._isr_enc)
        self._b.irq( trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._isr_enc)
        self._sw.irq(trigger=Pin.IRQ_FALLING,                  handler=self._isr_sw)

    def _isr_enc(self, _):
        now = time.ticks_ms()
        # 3 ms per-edge guard – suppresses residual contact bounce spikes
        if time.ticks_diff(now, self._t_enc) < 3:
            return
        self._t_enc = now
        new_ab = (self._a.value() << 1) | self._b.value()
        self._count += self._TABLE[(self._ab << 2) | new_ab]
        self._ab = new_ab
        cnt = self._count
        if abs(cnt) >= self._STEPS_PER_EVENT:
            self._count = 0
        if cnt >=  self._STEPS_PER_EVENT:
            encoder_right_pressed()
        if cnt <= -self._STEPS_PER_EVENT:
            encoder_left_pressed()
        
    def _isr_sw(self, _):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._t_sw) > 250:   # 250 ms debounce
            self._t_sw   = now
            enter_button_pressed()


# ================== PUSH BUTTON SETUP ==================
class _Button:
    _DEBOUNCE_MS = 50

    def __init__(self, pin_num, name, manager):
        self._pin = Pin(pin_num, Pin.IN, Pin.PULL_UP)
        self._name = name
        self._mgr  = manager
        self._t    = 0
        self._pin.irq(trigger=Pin.IRQ_FALLING, handler=self._isr)

    def _isr(self, _):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._t) >= self._DEBOUNCE_MS:
            self._t = now
            self._mgr._post(self._name)


class ButtonManager:
    def __init__(self, left_pin, right_pin, back_pin):
        # Each button is an independent object with its own debounce timer
        self._left  = _Button(left_pin,  "LEFT",  self)
        self._right = _Button(right_pin, "RIGHT", self)
        self._back  = _Button(back_pin,  "BACK",  self)

    def _post(self, name):
        """Called from ISR: stores event only if the slot is empty."""
        if name == "LEFT":
            left_button_pressed()
        elif name == "RIGHT":
            right_button_pressed()
        elif name == "BACK":
            back_button_pressed()
            


# ── Hardware pin assignments ──────────────────────────────────────────────────
ENC_A_PIN     = 2
ENC_B_PIN     = 3
ENC_SW_PIN    = 4
BTN_LEFT_PIN  = 5
BTN_RIGHT_PIN = 6
BTN_BACK_PIN  = 7

encoder = RotaryEncoder(ENC_A_PIN, ENC_B_PIN, ENC_SW_PIN)
buttons = ButtonManager(BTN_LEFT_PIN, BTN_RIGHT_PIN, BTN_BACK_PIN)

current_state = "LOGO"
draw_raw_image('/logo2.raw', 0, 0, 320, 240, display)
menu_block = 1

# ============================= BUTTON FUNCTIONS ================================
def left_button_pressed():
    global current_state
    global menu_block
    global plotter_cursor_idx
    global custom_edit_mode, custom_cursor_idx, current_mult_idx
    global selected_mode
    
    if current_state == "Menu":
        if menu_block == 2:
            draw_outline(84, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(7, 60, 75, 140, WHITE, 2)
            menu_block = 1
        elif menu_block == 3:
            draw_outline(161, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(84, 60, 75, 140, WHITE, 2)
            menu_block = 2
            
        elif menu_block == 4:
            draw_outline(238, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(161, 60, 75, 140, WHITE, 2)
            menu_block = 3
    
    elif current_state == "Custom_MODE":
        if custom_edit_mode and custom_cursor_idx < 3:
            current_mult_idx = min(4, current_mult_idx + 1)
            draw_custom_row(custom_cursor_idx)
            
    elif current_state == "Choose_MODE":      
        if selected_mode == 2:
            selected_mode = 1
            draw_outline(84, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(7, 60, 75, 110, WHITE, 2)
        elif selected_mode == 3:
            selected_mode = 2
            draw_outline(161, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(84, 60, 75, 110, WHITE, 2)            
        elif selected_mode == 4:
            selected_mode = 3
            draw_outline(238, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(161, 60, 75, 110, WHITE, 2)
            
    elif current_state == "Plotter":
        old_idx = plotter_cursor_idx
        if plotter_cursor_idx > 0:
            plotter_cursor_idx -= 1
        if old_idx != plotter_cursor_idx and current_state == "Plotter":
            render_plotter_menu()
    
def right_button_pressed():
    global current_state
    global menu_block
    global plotter_cursor_idx
    global custom_edit_mode, custom_cursor_idx, current_mult_idx
    global selected_mode
    
    if current_state == "Menu":
        if menu_block == 1:
            draw_outline(7, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(84, 60, 75, 140, WHITE, 2)
            menu_block = 2
        elif menu_block == 2:
            draw_outline(84, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(161, 60, 75, 140, WHITE, 2)
            menu_block = 3
        elif menu_block == 3:
            draw_outline(161, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(238, 60, 75, 140, WHITE, 2)
            menu_block = 4
    
    elif current_state == "Custom_MODE":
        if custom_edit_mode and custom_cursor_idx < 3:
            current_mult_idx = max(0, current_mult_idx - 1)
            draw_custom_row(custom_cursor_idx)
            
    elif current_state == "Choose_MODE":
        if selected_mode == 1:
            draw_outline(7, 60, 75, 110, WHITE, 2)
            selected_mode = 2
            draw_outline(7, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(84, 60, 75, 110, WHITE, 2)            
        elif selected_mode == 2:
            selected_mode = 3
            draw_outline(84, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(161, 60, 75, 110, WHITE, 2)
        elif selected_mode == 3:
            selected_mode = 4
            draw_outline(161, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(238, 60, 75, 110, WHITE, 2)
            
    elif current_state == "Plotter":
        old_idx = plotter_cursor_idx
        if plotter_cursor_idx < 3:  
            plotter_cursor_idx += 1
        if old_idx != plotter_cursor_idx and current_state == "Plotter":
            render_plotter_menu()
            
    
def back_button_pressed():
    global current_state
    global menu_block
    
    if current_state == "Credits":
        draw_menu()
        menu_block = 1
        current_state = "Menu"
        
    elif current_state == "Custom_MODE":
        current_state = "Menu"
        menu_block = 1
        draw_menu()
    
    elif current_state == "Choose_MODE":
        current_state = "Menu"
        menu_block = 1
        draw_menu()
        
    elif current_state == "Files":
        menu_block = 1
        current_state = "Menu"
        draw_menu()
    
    elif current_state == "Plotter":
        current_state = "Files"
        draw_files()
    
def enter_button_pressed():
    global current_state
    global menu_block
    global custom_cursor_idx, custom_edit_mode, current_mult_idx
    global current_plot_file
    global plotter_cursor_idx
    global file_cursor_idx
    
    if current_state == "LOGO":
        current_state = "Menu"
        draw_menu()
        menu_block = 1
        
    elif current_state == "Menu":
        if menu_block == 1:
            custom_mode()
            current_state = "Custom_MODE"
        elif menu_block == 2:
            choose_mode()
            current_state = "Choose_MODE"
        elif menu_block == 3:
            draw_files()
            current_state = "Files"
        elif menu_block == 4:
            draw_credits()
            current_state = "Credits"
            
    elif current_state == "Custom_MODE":
        if 0 <= custom_cursor_idx <= 3: # PARAMETER selected
             # Toggle edit mode on/off and redraw the box color (White <-> Green)
            custom_edit_mode = not custom_edit_mode
            if custom_edit_mode:
                current_mult_idx = 2
            draw_custom_row(custom_cursor_idx)
        elif custom_cursor_idx == 4: # START BUTTON selected
            if not custom_edit_mode: # Failsafe
                vpp_val = vpp_options[custom_vpp_idx]
                    
                # Visual feedback for Saving
                display.fill_rectangle(130, 187, 60, 36, BLUE)
                display.set_color(WHITE, BLUE)
                center_text("SAVING", 130, 187, 60, 36)
                    
                # Execute Sweep
                gf_mat, cal_freq_array = ic_code.calibration_table_maker(custom_start_f, custom_stop_f, custom_steps_val)
                sweep_data = ic_code.sweep(gf_mat, custom_start_f, custom_stop_f, custom_steps_val, 2, cal_freq_array)
                #sweep_data = ad5933.sweep(start=custom_start_f, stop=custom_stop_f, number=custom_steps_val, mode=vpp_val)
                save_sweep_data(sweep_data)
                time.sleep(0.5)
                
                # Return to Main Menu
                current_state = "Menu"
                menu_block = 1
                draw_menu()
                
    elif current_state == "Choose_MODE":
        start_f, stop_f, steps, vpp = MODE_PARAMS[selected_mode]
        #sweep_data = ad5933.sweep(start=start_f, stop=stop_f, number=steps, mode=vpp)
        gf_mat, cal_freq_array = ic_code.calibration_table_maker(custom_start_f, custom_stop_f, custom_steps_val)
        sweep_data = ic_code.sweep(gf_mat, custom_start_f, custom_stop_f, custom_steps_val, 2, cal_freq_array)
        display.fill_rectangle(128, 180, 64, 45, BLUE)
        display.set_color(WHITE, BLUE)
        center_text("SAVING", 128, 185, 64, 40)
        save_sweep_data(sweep_data)
        time.sleep(0.5) # Brief pause so the user actually sees "SAVING"
        # Reset UI state and return to Home Screen
        draw_menu()
        menu_block = 1
        current_state = "Menu"
        
    elif current_state == "Files":
        if len(files_list) > 0 and files_list[0] != "Error Reading FS":
            current_plot_file = "/Sweeps/" + files_list[file_cursor_idx]
            current_state = "Plotter"
            plot_it(current_plot_file)
        if old_idx != file_cursor_idx:
            render_files_list(old_idx, file_cursor_idx)
            
    elif current_state == "BIG_PLOT":
        plot_it(current_plot_file)
        current_state = "Plotter"
        
    elif current_state == "Plotter":
        old_idx = plotter_cursor_idx
        if plotter_cursor_idx == 0:    # "BACK"
            current_state = "Files"
            draw_files()
        elif plotter_cursor_idx == 1:  # "DELETE"
            try:
                os.remove(current_plot_file)
            except OSError:
                pass # Failsafe in case file is already gone
            current_state = "Files"
            draw_files()
        elif plotter_cursor_idx == 2:  # "MENU"
            current_state = "Menu"
            menu_block = 1
            draw_menu()        
        elif plotter_cursor_idx == 3:
            current_state = "BIG_PLOT"
            big_plot(current_plot_file)
        if old_idx != plotter_cursor_idx and current_state == "Plotter":
            render_plotter_menu()

def encoder_right_pressed():
    global current_state
    global menu_block
    global custom_edit_mode, custom_cursor_idx
    global file_cursor_idx
    global selected_mode
    global plotter_cursor_idx
    global custom_start_f, custom_stop_f, custom_steps_val, custom_vpp_idx
        
    if current_state == "Menu":
        if menu_block == 1:
            draw_outline(7, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(84, 60, 75, 140, WHITE, 2)
            menu_block = 2
        elif menu_block == 2:
            draw_outline(84, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(161, 60, 75, 140, WHITE, 2)
            menu_block = 3
        elif menu_block == 3:
            draw_outline(161, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(238, 60, 75, 140, WHITE, 2)
            menu_block = 4
            
    elif current_state == "Custom_MODE":
        if custom_edit_mode:
            step_val = MULT_VALUES[current_mult_idx]
            # Increment Values
            if custom_cursor_idx == 0:
                custom_start_f = min(100000, custom_start_f + step_val)
                if custom_stop_f <= custom_start_f: custom_stop_f = custom_start_f + step_val
                custom_start()
                custom_stop()
            elif custom_cursor_idx == 1:
                custom_stop_f = min(100000, custom_stop_f + step_val)
                custom_stop()
            elif custom_cursor_idx == 2:
                s_val = min(step_val, 100)
                custom_steps_val = min(500, custom_steps_val + s_val)
                custom_steps()
            elif custom_cursor_idx == 3:
                custom_vpp_idx = min(3, custom_vpp_idx + 1)
                custom_mode_set()
        else:
            # Move Cursor Down
            if custom_cursor_idx < 3:
                old = custom_cursor_idx
                custom_cursor_idx += 1
                draw_custom_row(old)
                if custom_cursor_idx < 4:
                    draw_custom_row(custom_cursor_idx)
                custom_sweep()
    
    elif current_state == "Files":
         old_idx = file_cursor_idx
         if file_cursor_idx < len(files_list) -1:
            file_cursor_idx += 1
         if old_idx != file_cursor_idx:
            render_files_list(old_idx, file_cursor_idx)
    
    elif current_state == "Choose_MODE":
        if selected_mode == 1:
            draw_outline(7, 60, 75, 110, WHITE, 2)
            selected_mode = 2
            draw_outline(7, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(84, 60, 75, 110, WHITE, 2)            
        elif selected_mode == 2:
            selected_mode = 3
            draw_outline(84, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(161, 60, 75, 110, WHITE, 2)
        elif selected_mode == 3:
            selected_mode = 4
            draw_outline(161, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(238, 60, 75, 110, WHITE, 2)
            
    elif current_state == "Plotter":
        old_idx = plotter_cursor_idx
        if plotter_cursor_idx < 3:  
            plotter_cursor_idx += 1
        if old_idx != plotter_cursor_idx and current_state == "Plotter":
            render_plotter_menu()
            
def encoder_left_pressed():
    global current_state
    global menu_block
    global file_cursor_idx
    global selected_mode
    global plotter_cursor_idx
    global custom_edit_mode, current_mult_idx, custom_cursor_idx
    global custom_start_f, custom_stop_f, custom_steps_val, custom_vpp_idx
        
    if current_state == "Menu":
        if menu_block == 2:
            draw_outline(84, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(7, 60, 75, 140, WHITE, 2)
            menu_block = 1
        elif menu_block == 3:
            draw_outline(161, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(84, 60, 75, 140, WHITE, 2)
            menu_block = 2
            
        elif menu_block == 4:
            draw_outline(238, 60, 75, 140, DARK_GRAY, 2)
            draw_outline(161, 60, 75, 140, WHITE, 2)
            menu_block = 3
    
    elif current_state == "Custom_MODE":
        if custom_edit_mode:
            step_val = MULT_VALUES[current_mult_idx]
            # Decrement Values
            if custom_cursor_idx == 0:
                custom_start_f = max(10, custom_start_f - step_val)
                if custom_stop_f <= custom_start_f: custom_stop_f = custom_start_f + step_val
                custom_start()
                custom_stop()
            elif custom_cursor_idx == 1:
                custom_stop_f = max(custom_start_f + 10, custom_stop_f - step_val)
                custom_stop()
            elif custom_cursor_idx == 2:
                s_val = min(step_val, 100)
                custom_steps_val = max(10, custom_steps_val - s_val)
                custom_steps()
            elif custom_cursor_idx == 3:
                custom_vpp_idx = max(0, custom_vpp_idx - 1)
                custom_mode_set()
        else:                
            if custom_cursor_idx > 0:
                old = custom_cursor_idx
                custom_cursor_idx -= 1
                draw_custom_row(old)
                draw_custom_row(custom_cursor_idx)
                custom_sweep()
    
    elif current_state == "Choose_MODE":      
        if selected_mode == 2:
            selected_mode = 1
            draw_outline(84, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(7, 60, 75, 110, WHITE, 2)
        elif selected_mode == 3:
            selected_mode = 2
            draw_outline(161, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(84, 60, 75, 110, WHITE, 2)            
        elif selected_mode == 4:
            selected_mode = 3
            draw_outline(238, 60, 75, 110, DARK_GRAY, 2)
            draw_outline(161, 60, 75, 110, WHITE, 2)

    elif current_state == "Files":
         old_idx = file_cursor_idx
         if file_cursor_idx > 0:
            file_cursor_idx -= 1
         if old_idx != file_cursor_idx:
            render_files_list(old_idx, file_cursor_idx)
            
    elif current_state == "Plotter":
        old_idx = plotter_cursor_idx
        if plotter_cursor_idx > 0:
            plotter_cursor_idx -= 1
        if old_idx != plotter_cursor_idx and current_state == "Plotter":
            render_plotter_menu()
