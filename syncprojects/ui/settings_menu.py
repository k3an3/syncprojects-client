import logging
import tkinter as tk
from tkinter.filedialog import askdirectory
from tkinter.messagebox import showwarning

from syncprojects import config
from syncprojects.storage import appdata


class SettingsUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Syncprojects-client Setup")
        # Buttons/objects
        self.sync_source_button = None
        self.audio_sync_source_button = None
        self.nested_check = tk.BooleanVar()
        self.nested_check.set(appdata.get('nested_folders', False))
        # Dest variables
        self.sync_source_dir = appdata.get('source')
        self.audio_sync_source_dir = appdata.get('audio_sync_dir')
        self.nested = False
        self.workers_field = None
        self.workers = appdata.get('workers', config.MAX_WORKERS)
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
        frame_d = tk.Frame()

        label_a = tk.Label(master=frame_a, text="Select the top level folder where you want DAW project folders to be "
                                                "synced to/from:")
        label_a.pack()
        self.sync_source_button = tk.Button(master=frame_a,
                                            text=appdata.get('source', "Configure project sync location"),
                                            command=self.get_sync_dir)
        self.sync_source_button.pack()

        label_nested_path = tk.Label(master=frame_a, text="Check if you would like songs to be nested by project. "
                                                          "Otherwise, all of your songs will be in the same folder.")
        label_nested_path.pack()
        nested_check = tk.Checkbutton(master=frame_a, text='Nested folder structure', variable=self.nested_check,
                                      onvalue=True, offvalue=False)
        nested_check.pack()

        label_b = tk.Label(master=frame_b, text="Select the top level folder where you want audio files (e.g. mp3s) "
                                                "synced to/from. Subfolders will be used for each project.")
        label_b.pack()
        self.audio_sync_source_button = tk.Button(master=frame_b,
                                                  text=appdata.get('audio_sync_dir',
                                                                   "Configure audio file sync location"),
                                                  command=self.get_audio_dir)
        self.audio_sync_source_button.pack()

        frame_a.pack()
        frame_b.pack()

        label_c = tk.Label(master=frame_c, text="How many parallel upload/downloads to allow:")
        self.workers_field = tk.Entry(master=frame_c, text=appdata.get('workers', config.MAX_WORKERS))
        label_c.pack()
        self.workers_field.pack()
        frame_c.pack()

        save_button = tk.Button(master=frame_d, text="Save", command=self.quit)
        save_button.pack()

        frame_d.pack()

        self.logger.debug("Entering main loop...")
        self.window.mainloop()

    def quit(self):
        self.nested = self.nested_check.get()
        self.logger.debug("Quit button pressed.")
        if not self.sync_source_dir or not self.audio_sync_source_dir:
            showwarning(master=self.window, title="Missing Information!",
                        message="Please set all fields correctly.")
            self.logger.debug("Fields not completed.")
        elif self.sync_source_dir == self.audio_sync_source_dir:
            showwarning(master=self.window, title="Duplicate Entries!",
                        message="Please ensure the same folder was not chosen for both fields.")
            self.logger.debug("Fields are the same.")
        else:
            try:
                self.workers = int(self.workers_field.get())
                if self.workers <= 0:
                    raise ValueError()
            except ValueError:
                self.logger.debug("Workers not a valid number.")
                showwarning(master=self.window, title="Invalid number!",
                            message="Please ensure a valid, positive number is used for the workers field.")
            else:
                self.logger.debug("Quit button pressed. Exiting")
                self.window.destroy()
                # self.window.quit()


if __name__ == "__main__":
    # testing only
    ui = SettingsUI()
    ui.run()
