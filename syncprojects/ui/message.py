import logging
import tkinter as tk
from tkinter.messagebox import showinfo, showerror, showwarning, askyesnocancel, askyesno

WARNING = "warning"
ERROR = "error"
INFO = "info"
YESNO = "yesno"
YESNOCANCEL = "yesnocancel"

LEVELS = {
    WARNING: showwarning,
    ERROR: showerror,
    INFO: showinfo,
    YESNO: askyesno,
    YESNOCANCEL: askyesnocancel,
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
        result = LEVELS[level](master=self.window, title=title, message=message)
        self.window.destroy()
        return result

    @staticmethod
    def info(message: str, title: str = ""):
        return MessageBoxUI().show(message, title, INFO)

    @staticmethod
    def warning(message: str, title: str = ""):
        return MessageBoxUI().show(message, title, WARNING)

    @staticmethod
    def error(message: str, title: str = ""):
        return MessageBoxUI().show(message, title, ERROR)

    @staticmethod
    def yesno(message: str, title: str = ""):
        return MessageBoxUI().show(message, title, YESNO)

    @staticmethod
    def yesnocancel(message: str, title: str = ""):
        return MessageBoxUI().show(message, title, YESNOCANCEL)
