import customtkinter as ctk

from modules.ui_theme import SPACING_LARGE
from widgets.components.knowledge_panel import KnowledgePanel
from widgets.components.memory_panel import MemoryPanel
from widgets.components.persona_panel import PersonaPanel


class LearningCenterPage(ctk.CTkFrame):
    """AppShell container that groups Aurora learning workspaces."""

    def __init__(
        self,
        parent,
        *,
        knowledge_store,
        memory_store,
        persona_store,
        search_memories,
        settings,
        text,
        translate,
        logger,
        version,
        retrieval_summary,
        final_prompt_preview_callback=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.logger = logger
        self.panel_tabs = {}
        self.tabs_by_panel = {}
        self.panel_specs = {}
        self.panels = {}
        self.last_panel_id = "knowledge"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=SPACING_LARGE,
            pady=SPACING_LARGE
        )

        self._add_panel_tab(
            "knowledge",
            "nav_library",
            KnowledgePanel,
            knowledge_store=knowledge_store,
            settings=settings,
            text=text,
            translate=translate,
            logger=logger,
            version=version,
            retrieval_summary=retrieval_summary,
            show_close_button=False,
            show_header_title=False
        )
        self._add_panel_tab(
            "memory",
            "nav_memory",
            MemoryPanel,
            memory_store=memory_store,
            search_memories=search_memories,
            translate=translate,
            logger=logger,
            show_close_button=False,
            show_header_title=False
        )
        self._add_panel_tab(
            "persona",
            "nav_persona",
            PersonaPanel,
            persona_store=persona_store,
            settings=settings,
            translate=translate,
            logger=logger,
            final_prompt_preview_callback=final_prompt_preview_callback,
            show_close_button=False,
            show_header_title=False
        )
        self.tabs.configure(command=self._on_tab_changed)
        self.show_tab("knowledge")

        if self.logger:
            self.logger.info("LearningCenterPage initialized")

    def _add_panel_tab(self, panel_id, tab_key, panel_class, **panel_kwargs):
        tab = self.tabs.add(self.t(tab_key))
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        tab_name = self.t(tab_key)
        self.panel_tabs[panel_id] = tab_name
        self.tabs_by_panel[tab_name] = panel_id
        self.panel_specs[panel_id] = (tab, panel_class, panel_kwargs)

    def _on_tab_changed(self):
        panel_id = self.tabs_by_panel.get(self.tabs.get())
        if panel_id:
            self._ensure_panel(panel_id)
            self.last_panel_id = panel_id
            if self.logger:
                self.logger.info(f"LearningCenterPage tab switched: {panel_id}")

    def _ensure_panel(self, panel_id):
        if panel_id in self.panels:
            return self.panels[panel_id]
        tab, panel_class, panel_kwargs = self.panel_specs[panel_id]
        panel = panel_class(tab, **panel_kwargs)
        panel.grid(row=0, column=0, sticky="nsew")
        self.panels[panel_id] = panel
        if self.logger:
            self.logger.info(f"LearningCenterPage lazy created panel: {panel_id}")
        return panel

    def show_tab(self, panel_id):
        tab_name = self.panel_tabs.get(panel_id)
        if tab_name:
            self._ensure_panel(panel_id)
            self.tabs.set(tab_name)
            self.last_panel_id = panel_id
            if self.logger:
                self.logger.info(f"LearningCenterPage selected tab: {panel_id}")

    def on_show(self):
        """Restore the last selected workspace when AppShell shows this page."""
        self.show_tab(self.last_panel_id)
