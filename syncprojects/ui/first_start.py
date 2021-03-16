import logging
import tkinter as tk
from tkinter.filedialog import askdirectory
from tkinter.messagebox import showwarning


class SetupUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Syncprojects-client Setup")
        self.sync_source_button = None
        self.audio_sync_source_button = None
        self.sync_source_dir = None
        self.audio_sync_source_dir = None
        self.logger = logging.getLogger('syncprojects.ui.first_start.SetupUI')

    def get_sync_dir(self):
        result = askdirectory(parent=self.window, title="Select the top level sync folder")
        if result:
            self.sync_source_button["text"] = result
            self.sync_source_dir = result

    def get_audio_dir(self):
        # TODO: deduplicate code
        result = askdirectory(parent=self.window, title="Select the top level sync folder")
        if result:
            self.audio_sync_source_button["text"] = result
            self.audio_sync_source_dir = result

    def run(self):
        self.logger.debug("Building main window...")
        frame_a = tk.Frame()
        frame_b = tk.Frame()
        frame_c = tk.Frame()

        label_a = tk.Label(master=frame_a, text="Select the top level folder where you want DAW project folders to be "
                                                "synced to/from:")
        label_a.pack()
        self.sync_source_button = tk.Button(master=frame_a,
                                            text="Configure project sync location",
                                            command=self.get_sync_dir)
        self.sync_source_button.pack()

        label_b = tk.Label(master=frame_b, text="Select the top level folder where you want audio files (e.g. mp3s) "
                                                "synced to/from. Subfolders will be used for each project.")
        label_b.pack()
        self.audio_sync_source_button = tk.Button(master=frame_b,
                                                  text="Configure audio file sync location",
                                                  command=self.get_audio_dir)
        self.audio_sync_source_button.pack()

        frame_a.pack()
        frame_b.pack()

        save_button = tk.Button(master=frame_c, text="Save", command=self.quit)
        save_button.pack()

        frame_c.pack()

        self.logger.debug("Entering main loop...")
        self.window.mainloop()

    def quit(self):
        if not self.sync_source_dir and not self.audio_sync_source_dir:
            showwarning(master=self.window, title="Missing Information!",
                        message="Please set all fields correctly.")
            self.logger.debug("Quit button pressed. Fields not completed.")
        elif self.sync_source_dir == self.audio_sync_source_dir:
            showwarning(master=self.window, title="Duplicate Entries!",
                        message="Please ensure the same folder was not chosen for both fields.")
            self.logger.debug("Quit button pressed. Fields are the same.")
        else:
            self.logger.debug("Quit button pressed. Exiting")
            self.window.destroy()
            # self.window.quit()


if __name__ == "__main__":
    # testing only
    ui = SetupUI()
    ui.run()
