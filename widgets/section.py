import customtkinter as ctk


class Section(ctk.CTkFrame):
    def __init__(self, master, title: str):
        super().__init__(master)

        self.pack_propagate(False)

        self.title = ctk.CTkLabel(
            self,
            text=title,
            font=("Microsoft YaHei", 16, "bold"),
            anchor="w"
        )

        self.title.pack(
            fill="x",
            padx=15,
            pady=(12, 8)
        )

        self.body = ctk.CTkFrame(
            self,
            fg_color="transparent"
        )

        self.body.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=(0, 10)
        )