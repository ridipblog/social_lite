"""
Main entry point for SocialLite Messenger.
Uses modern CustomTkinter interface.
Run:
    python main.py
"""

import customtkinter as ctk
from gui import SocialLiteGUI


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    app = SocialLiteGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
