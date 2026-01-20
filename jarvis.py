#!/usr/bin/env python3
"""
Jarvis assistant (single-file)

Features:
- Camera panel (Tkinter + OpenCV)
- Voice recognition (speech_recognition) and text command entry
- Text-to-speech (pyttsx3)
- Answer questions using wikipedia; fallback to google search and fetch first page snippet
- Basic OS control commands (open app/folder, shutdown/restart with confirmation, take screenshot, capture photo)
- Buttons to start/stop camera and listening
- Wakeword support ("Hey Jarvis") for voice commands; typed commands may include wakeword and it will be stripped
"""

import threading
import queue
import time
import platform
import subprocess
import os
import sys
from datetime import datetime
import re

import cv2
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pyttsx3
import speech_recognition as sr

import wikipedia
import requests
from bs4 import BeautifulSoup
import webbrowser

# Try to import googlesearch (may be named different on some systems)
try:
    # pip install googlesearch-python
    from googlesearch import search as google_search
except Exception:
    google_search = None

# ---------- Configuration ----------
CAMERA_INDEX = 0  # default camera
WIKI_SENTENCES = 2
ENGINE_RATE = 170
WAKEWORD = "hey jarvis"  # wakeword (lowercase)
# -----------------------------------

# Initialize TTS engine
engine = pyttsx3.init()
engine.setProperty('rate', ENGINE_RATE)

def speak(text):
    """Speak text (non-blocking)"""
    def _s():
        engine.say(text)
        engine.runAndWait()
    t = threading.Thread(target=_s, daemon=True)
    t.start()

# Recognizer setup
recognizer = sr.Recognizer()
mic = None
try:
    mic = sr.Microphone()
except Exception:
    mic = None

def listen(timeout=5, phrase_time_limit=8):
    """Listen from microphone and return recognized text. Returns None on failure."""
    if mic is None:
        return None
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.8)
        try:
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            text = recognizer.recognize_google(audio)
            return text
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            return None

# ---------- Wakeword helpers ----------
def normalize_text(t: str) -> str:
    return re.sub(r"[^\w\s]", "", t).lower().strip()

def has_wakeword(t: str) -> bool:
    """Return True if the wakeword appears at the start or is spoken addressed in the text."""
    if not t:
        return False
    norm = normalize_text(t)
    # allow "hey jarvis" at start or maybe "jarvis" alone as target
    return norm.startswith(WAKEWORD) or norm.startswith("jarvis")

def strip_wakeword(t: str) -> str:
    """Remove wakeword/prefix like 'hey jarvis' or 'jarvis' from the beginning of text."""
    if not t:
        return t
    norm = t.strip()
    # remove common punctuation and lowercase-check for wakeword forms
    # Use regex to remove leading 'hey', optional comma, then 'jarvis'
    stripped = re.sub(r'^\s*(hey[,]*\s+)?jarvis[,:\s-]*', '', norm, flags=re.I).strip()
    return stripped if stripped else ""

# ---------- Search Helpers ----------
def search_wikipedia(query):
    try:
        wikipedia.set_lang("en")
        summary = wikipedia.summary(query, sentences=WIKI_SENTENCES)
        return summary
    except Exception:
        return None

def google_first_snippet(query):
    """Use googlesearch to find URLs, then fetch the first page snippet/title/first paragraph"""
    urls = []
    try:
        if google_search:
            for u in google_search(query, num_results=5):
                urls.append(u)
        else:
            # Fallback: open a browser search and return None
            webbrowser.open(f"https://www.google.com/search?q={requests.utils.requote_uri(query)}")
            return None
    except Exception:
        # fallback to browser open
        webbrowser.open(f"https://www.google.com/search?q={requests.utils.requote_uri(query)}")
        return None

    for url in urls:
        try:
            resp = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else url
            # find first meaningful paragraph
            p = soup.find("p")
            snippet = p.get_text().strip() if p else ""
            if snippet:
                return f"{title}\n\n{snippet}\n\nSource: {url}"
            else:
                return f"{title}\n\nSource: {url}"
        except Exception:
            continue
    return None

# ---------- OS Control Helpers ----------
def safe_run(command_list):
    """Run a command list and return (ok, output)."""
    try:
        out = subprocess.check_output(command_list, stderr=subprocess.STDOUT, shell=False, text=True)
        return True, out
    except subprocess.CalledProcessError as e:
        return False, e.output
    except Exception as e:
        return False, str(e)

def open_application(app_name):
    """Try to open common applications. Practical mappings for Windows/Linux/macOS"""
    system = platform.system().lower()
    app_name_lower = app_name.lower()

    # Simple mapping:
    if "notepad" in app_name_lower or "text" in app_name_lower:
        if system == "windows":
            subprocess.Popen(["notepad"])
            return True
        else:
            # try gedit, xed, or nano in terminal
            for candidate in (["gedit"], ["xed"], ["kate"]):
                try:
                    subprocess.Popen(candidate)
                    return True
                except Exception:
                    continue
            # fallback: open home folder
            subprocess.Popen(["xdg-open", os.path.expanduser("~")])
            return True
    if "chrome" in app_name_lower or "google chrome" in app_name_lower:
        try:
            if system == "windows":
                subprocess.Popen(["start", "chrome"], shell=True)
            elif system == "darwin":
                subprocess.Popen(["open", "-a", "Google Chrome"])
            else:
                subprocess.Popen(["google-chrome"])
            return True
        except Exception:
            webbrowser.open("https://www.google.com")
            return True
    if "browser" in app_name_lower or "firefox" in app_name_lower:
        webbrowser.open("https://www.google.com")
        return True

    # Try to open application directly by name
    try:
        if system == "windows":
            os.startfile(app_name)  # may raise
        elif system == "darwin":
            subprocess.Popen(["open", "-a", app_name])
        else:
            subprocess.Popen([app_name])
        return True
    except Exception:
        return False

def open_folder(path):
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return False, "Path does not exist"
        system = platform.system().lower()
        if system == "windows":
            os.startfile(path)
        elif system == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True, "Opened"
    except Exception as e:
        return False, str(e)

def system_shutdown(confirm=False):
    if not confirm:
        return False, "Confirmation required"
    system = platform.system().lower()
    try:
        if system == "windows":
            subprocess.Popen(["shutdown", "/s", "/t", "10"])
        elif system == "darwin" or system == "linux":
            subprocess.Popen(["shutdown", "-h", "now"])
        return True, "Shutdown initiated"
    except Exception as e:
        return False, str(e)

def system_restart(confirm=False):
    if not confirm:
        return False, "Confirmation required"
    system = platform.system().lower()
    try:
        if system == "windows":
            subprocess.Popen(["shutdown", "/r", "/t", "10"])
        elif system == "darwin" or system == "linux":
            subprocess.Popen(["shutdown", "-r", "now"])
        return True, "Restart initiated"
    except Exception as e:
        return False, str(e)

# ---------- GUI and Camera ----------
class JarvisApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Jarvis Assistant")
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

        self.video_frame = ttk.LabelFrame(root, text="Camera")
        self.video_frame.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        self.panel = tk.Label(self.video_frame)
        self.panel.pack()

        controls = ttk.LabelFrame(root, text="Controls & Commands")
        controls.grid(row=1, column=0, padx=8, pady=8, sticky="ew")

        self.entry = ttk.Entry(controls, width=60)
        self.entry.grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.send_btn = ttk.Button(controls, text="Send Command", command=self.on_command)
        self.send_btn.grid(row=0, column=1, padx=4, pady=4)

        self.listen_btn = ttk.Button(controls, text="Start Listening", command=self.toggle_listening)
        self.listen_btn.grid(row=1, column=0, padx=4, pady=4, sticky="w")

        self.capture_btn = ttk.Button(controls, text="Capture Photo", command=self.capture_photo)
        self.capture_btn.grid(row=1, column=1, padx=4, pady=4)

        camcontrols = ttk.Frame(root)
        camcontrols.grid(row=2, column=0, padx=8, pady=8, sticky="ew")
        self.start_cam_btn = ttk.Button(camcontrols, text="Start Camera", command=self.start_camera)
        self.start_cam_btn.grid(row=0, column=0, padx=4)
        self.stop_cam_btn = ttk.Button(camcontrols, text="Stop Camera", command=self.stop_camera, state="disabled")
        self.stop_cam_btn.grid(row=0, column=1, padx=4)
        self.quit_btn = ttk.Button(camcontrols, text="Quit", command=self.on_quit)
        self.quit_btn.grid(row=0, column=2, padx=4)

        # Wakeword / status label
        status_frame = ttk.Frame(root)
        status_frame.grid(row=3, column=0, padx=8, pady=(0,4), sticky="ew")
        self.wake_label = ttk.Label(status_frame, text="Not listening")
        self.wake_label.pack(side="left", padx=4)

        self.log = tk.Text(root, height=10, state="disabled")
        self.log.grid(row=4, column=0, padx=8, pady=8, sticky="ew")

        # camera variables
        self.cap = None
        self.camera_running = False
        self.camera_thread = None

        # listening variables
        self.listening = False
        self.listen_thread = None

        self.command_queue = queue.Queue()

    def log_message(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{timestamp}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # Camera methods
    def start_camera(self):
        if self.camera_running:
            return
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        if not self.cap.isOpened():
            self.log_message("Unable to open camera.")
            messagebox.showerror("Camera Error", "Unable to open camera.")
            return
        self.camera_running = True
        self.start_cam_btn.config(state="disabled")
        self.stop_cam_btn.config(state="normal")
        self.camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self.camera_thread.start()
        self.log_message("Camera started.")

    def _camera_loop(self):
        while self.camera_running and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.1)
                continue
            # convert BGR->RGB and flip horizontally for mirror
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.flip(frame, 1)
            img = Image.fromarray(frame)
            imgtk = ImageTk.PhotoImage(image=img)
            # update panel in main thread via after
            self.panel.imgtk = imgtk
            self.panel.configure(image=imgtk)
            time.sleep(1/30)
        # release capture
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        self.panel.configure(image="")
        self.log_message("Camera stopped.")

    def stop_camera(self):
        if not self.camera_running:
            return
        self.camera_running = False
        self.start_cam_btn.config(state="normal")
        self.stop_cam_btn.config(state="disabled")

    def capture_photo(self):
        if not self.cap or not self.cap.isOpened():
            messagebox.showwarning("Capture", "Camera not running.")
            return
        ret, frame = self.cap.read()
        if not ret:
            messagebox.showwarning("Capture", "Unable to capture photo.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".jpg", filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")])
        if not path:
            return
        cv2.imwrite(path, frame)
        self.log_message(f"Photo saved to {path}")
        speak(f"Photo saved.")

    # Listening and command processing
    def toggle_listening(self):
        if not self.listening:
            self.listening = True
            self.listen_btn.config(text="Stop Listening")
            self.wake_label.config(text=f"Listening (awaiting: \"{WAKEWORD}\")")
            self.listen_thread = threading.Thread(target=self._listening_loop, daemon=True)
            self.listen_thread.start()
            self.log_message("Listening started.")
            speak(f"Listening. Say {WAKEWORD} followed by your command.")
        else:
            self.listening = False
            self.listen_btn.config(text="Start Listening")
            self.wake_label.config(text="Not listening")
            self.log_message("Listening stopped.")
            speak("Stopped listening.")

    def _listening_loop(self):
        # When listening, act only on utterances that include the wakeword (or start addressing "jarvis")
        while self.listening:
            txt = listen(timeout=6, phrase_time_limit=6)
            if txt:
                self.log_message(f"Voice raw: {txt}")
                if has_wakeword(txt):
                    # strip wakeword and process
                    command_text = strip_wakeword(txt)
                    if not command_text:
                        # the user just said "Hey Jarvis" — prompt briefly
                        self.log_message("Wakeword detected but no command followed.")
                        speak("Yes?")
                        # small pause to allow follow-up (could be improved into a two-stage listen)
                        time.sleep(0.6)
                        # try a short follow-up listen
                        follow = listen(timeout=3, phrase_time_limit=4)
                        if follow:
                            self.log_message(f"Follow-up voice: {follow}")
                            self.process_command(follow)
                        continue
                    self.log_message(f"Wakeword detected. Command: {command_text}")
                    self.wake_label.config(text="Processing command...")
                    speak("Processing your command.")
                    self.process_command(command_text)
                    self.wake_label.config(text=f"Listening (awaiting: \"{WAKEWORD}\")")
                else:
                    # ignore unrelated speech
                    self.log_message("No wakeword detected in speech; ignoring.")
            else:
                # small pause to avoid loop spin
                time.sleep(0.5)

    def on_command(self):
        txt = self.entry.get().strip()
        if not txt:
            return
        self.entry.delete(0, "end")
        # strip wakeword from typed commands if present
        if has_wakeword(txt):
            txt = strip_wakeword(txt) or txt
        self.log_message(f"Command: {txt}")
        self.process_command(txt)

    def process_command(self, text):
        text = (text or "").strip()
        if not text:
            return
        text_lower = text.lower().strip()

        # OS control commands
        if text_lower.startswith("open folder") or text_lower.startswith("open directory"):
            # expect: open folder C:\path or open folder documents
            parts = text.split(" ", 2)
            path = parts[2] if len(parts) >= 3 else os.path.expanduser("~")
            ok, msg = open_folder(path)
            if ok:
                self.log_message(f"Opened folder: {path}")
                speak("Opened folder.")
            else:
                self.log_message(f"Failed to open folder: {msg}")
                speak("I could not open that folder.")
            return

        if text_lower.startswith("open ") or text_lower.startswith("launch "):
            # open application or URL
            target = text.split(" ", 1)[1]
            if target.startswith("http"):
                webbrowser.open(target)
                speak("Opening browser.")
                return
            ok = open_application(target)
            if ok:
                self.log_message(f"Opened application: {target}")
                speak(f"Opening {target}")
            else:
                self.log_message(f"Failed to open application: {target}")
                speak("I could not open that application.")
            return

        if "shutdown" in text_lower:
            # require explicit confirmation phrase
            if "confirm" in text_lower or "yes" in text_lower:
                ok, msg = system_shutdown(confirm=True)
                self.log_message(msg)
                speak("Shutting down. Goodbye.")
            else:
                self.log_message("Shutdown requested - confirmation required. Say 'shutdown confirm' to proceed.")
                speak("Shutdown requested. Say shutdown confirm to proceed.")
            return

        if "restart" in text_lower or "reboot" in text_lower:
            if "confirm" in text_lower or "yes" in text_lower:
                ok, msg = system_restart(confirm=True)
                self.log_message(msg)
                speak("Restarting now.")
            else:
                self.log_message("Restart requested - confirmation required. Say 'restart confirm' to proceed.")
                speak("Restart requested. Say restart confirm to proceed.")
            return

        if "screenshot" in text_lower or "screen shot" in text_lower:
            # take screenshot of screen
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG","*.png")])
                if path:
                    img.save(path)
                    self.log_message(f"Screenshot saved to {path}")
                    speak("Screenshot saved.")
                else:
                    self.log_message("Screenshot cancelled.")
            except Exception as e:
                self.log_message(f"Screenshot failed: {e}")
                speak("I could not take a screenshot.")
            return

        if "capture" in text_lower and ("photo" in text_lower or "picture" in text_lower):
            # capture photo from camera
            self.capture_photo()
            return

        # Knowledge queries: prefer wikipedia
        if text_lower.startswith("wikipedia ") or text_lower.startswith("wiki "):
            q = text.split(" ", 1)[1]
            self.log_message(f"Searching Wikipedia for: {q}")
            speak(f"Searching Wikipedia for {q}")
            ans = search_wikipedia(q)
            if ans:
                self.log_message(f"Wikipedia: {ans}")
                speak(ans)
            else:
                self.log_message("No Wikipedia result.")
                speak("I could not find a wikipedia entry. I'll search the web.")
                web_ans = google_first_snippet(q)
                if web_ans:
                    self.log_message(web_ans)
                    speak(web_ans)
                else:
                    speak("I couldn't find an answer.")
            return

        # General question: try wikipedia first
        # Example heuristics: if sentence contains "who", "what", "when", "where", "why", "how" treat as question
        if any(w in text_lower.split() for w in ("who", "what", "when", "where", "why", "how", "which")):
            self.log_message(f"Question detected: {text}")
            speak("Let me look that up.")
            ans = search_wikipedia(text)
            if ans:
                self.log_message(f"Wikipedia: {ans}")
                speak(ans)
                return
            # fallback to google snippet
            web_ans = google_first_snippet(text)
            if web_ans:
                self.log_message(web_ans)
                speak(web_ans)
                return
            # as last resort, open browser
            webbrowser.open(f"https://www.google.com/search?q={requests.utils.requote_uri(text)}")
            speak("I opened the browser with search results.")
            return

        # Otherwise, perform a web search and open browser
        self.log_message(f"No direct action matched. Searching web for: {text}")
        speak(f"Searching the web for {text}")
        if google_search:
            try:
                urls = list(google_search(text, num_results=5))
                if urls:
                    # open top 1-2 in browser
                    webbrowser.open(urls[0])
                    self.log_message(f"Opened {urls[0]}")
                    speak("I opened the first result in your browser.")
                    return
            except Exception:
                pass
        # fallback to open google
        webbrowser.open(f"https://www.google.com/search?q={requests.utils.requote_uri(text)}")
        speak("I opened the browser with search results.")

    def on_quit(self):
        if messagebox.askokcancel("Quit", "Are you sure you want to quit Jarvis?"):
            self.listening = False
            self.camera_running = False
            try:
                if self.cap:
                    self.cap.release()
            except Exception:
                pass
            try:
                self.root.destroy()
            except Exception:
                sys.exit(0)

def main():
    root = tk.Tk()
    root.geometry("800x700")
    app = JarvisApp(root)
    speak("Jarvis is starting up.")
    app.log_message("Jarvis initialized. Ready.")
    root.mainloop()

if __name__ == "__main__":
    main()
