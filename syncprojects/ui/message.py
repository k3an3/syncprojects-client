import logging
import tkinter as tk
from tkinter.messagebox import showinfo, showerror, showwarning

WARNING = "warning"
ERROR = "error"
INFO = "info"

LEVELS = {
    WARNING: showwarning,
    ERROR: showerror,
    INFO: showinfo,
}


class MessageBoxUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.withdraw()
        self.logger = logging.getLogger('syncprojects.ui.message.MessageBoxUI')

    def show(self, message: str, title: str = "", level: str = INFO):
        if level not in LEVELS:
            raise NotImplementedError()
        if not title:
            title = level.title()
        self.logger.debug(f"Showing message box: {level=} {title=} {message=}")
        LEVELS[level](master=self.window, title=title, message=message)
        self.window.destroy()

    @staticmethod
    def info(message: str, title: str = ""):
        MessageBoxUI().show(message, title, INFO)

    @staticmethod
    def warning(message: str, title: str = ""):
        MessageBoxUI().show(message, title, WARNING)

    @staticmethod
    def error(message: str, title: str = ""):
        MessageBoxUI().show(message, title, ERROR)
