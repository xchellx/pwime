import argparse
import dataclasses
import functools
import typing
from pathlib import Path

from imgui_bundle import imgui, hello_imgui, immapp
from imgui_bundle import portable_file_dialogs
from retro_data_structures.asset_manager import AssetManager, IsoFileProvider, FileProvider
from retro_data_structures.base_resource import NameOrAssetId, BaseResource
from retro_data_structures.exceptions import UnknownAssetId
from retro_data_structures.formats import Mlvl
from retro_data_structures.formats.mrea import Area
from retro_data_structures.formats.script_object import ScriptInstance
from retro_data_structures.game_check import Game
from retro_data_structures.properties.base_property import BaseProperty

_args: argparse.Namespace | None = None

T = typing.TypeVar("T", bound=BaseResource)


class OurAssetManager(AssetManager):
    memory_files: dict[NameOrAssetId, BaseResource]

    def __init__(self, provider: FileProvider, target_game: Game):
        super().__init__(provider, target_game)
        self.memory_files = {}

    def get_file(self, path: NameOrAssetId, type_hint: type[T] = BaseResource) -> T:
        if path not in self.memory_files:
            self.memory_files[path] = self.get_parsed_asset(path, type_hint=type_hint)
        return self.memory_files[path]


@dataclasses.dataclass()
class GuiState:
    asset_manager: OurAssetManager | None = None
    mlvls: tuple[int, ...] = ()
    open_file_dialog: portable_file_dialogs.open_file = None
    selected_asset: int | None = None
    pending_new_docks: list[hello_imgui.DockableWindow] = dataclasses.field(default_factory=list)

    def load_iso(self, path: Path):
        self.asset_manager = OurAssetManager(IsoFileProvider(path), Game.ECHOES)
        self.mlvls = tuple(
            i for i in self.asset_manager.all_asset_ids() if self.asset_manager.get_asset_type(i) == "MLVL"
        )


state = GuiState()


def _render_property(props: BaseProperty) -> None:
    for field in dataclasses.fields(props):
        imgui.table_next_row()
        imgui.table_next_column()

        item = getattr(props, field.name)
        is_struct = isinstance(item, BaseProperty)

        flags = imgui.TreeNodeFlags_.span_full_width
        if not is_struct:
            flags |= imgui.TreeNodeFlags_.leaf | imgui.TreeNodeFlags_.bullet | imgui.TreeNodeFlags_.no_tree_push_on_open

        is_open = imgui.tree_node_ex(field.name, flags)
        imgui.table_next_column()
        imgui.text(type(item).__name__)
        imgui.table_next_column()

        if is_struct:
            imgui.text("--")
        else:
            imgui.text(str(item))

        if is_struct and is_open:
            _render_property(item)
            imgui.tree_pop()


def _render_script_instance(instance: ScriptInstance) -> None:
    props = instance.get_properties()

    if imgui.begin_table("Properties", 3,
                         imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_h | imgui.TableFlags_.resizable):
        imgui.table_setup_column("Name")
        imgui.table_setup_column("Type")
        imgui.table_setup_column("Value")
        imgui.table_headers_row()
        _render_property(props)
        imgui.end_table()


def _create_dock_window_for_instance(area: Area, instance: ScriptInstance) -> hello_imgui.DockableWindow:
    return hello_imgui.DockableWindow(
        f"{instance.name} - {instance.id} ({area.name})",
        "MainDockSpace",
        gui_function_=functools.partial(_render_script_instance, instance)
    )


def _render_area(area: Area) -> None:
    if imgui.begin_table("Objects", 4,
                         imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_h | imgui.TableFlags_.resizable):
        imgui.table_setup_column("Layer", imgui.TableColumnFlags_.width_fixed)
        imgui.table_setup_column("Instance Id", imgui.TableColumnFlags_.width_fixed)
        imgui.table_setup_column("Type", imgui.TableColumnFlags_.width_fixed)
        imgui.table_setup_column("Name")
        imgui.table_headers_row()

        for layer in area.all_layers:
            for instance in layer.instances:
                imgui.table_next_row()

                imgui.table_next_column()
                imgui.text(layer.name if layer.has_parent else "<Generated Objects>")
                imgui.table_next_column()
                imgui.text(str(instance.id))
                imgui.table_next_column()
                imgui.text(instance.type.__name__)
                imgui.table_next_column()
                if imgui.selectable(
                        f"{instance.name}##{instance.id}",
                        False,
                        imgui.SelectableFlags_.span_all_columns | imgui.SelectableFlags_.allow_item_overlap,
                )[1]:
                    state.pending_new_docks.append(_create_dock_window_for_instance(area, instance))

        imgui.end_table()


def _create_dock_window_for_area(area: Area) -> hello_imgui.DockableWindow:
    return hello_imgui.DockableWindow(
        area.name,
        "MainDockSpace",
        gui_function_=functools.partial(_render_area, area)
    )


def _create_dock_window_for_mlvl(mlvl_id: int) -> hello_imgui.DockableWindow:
    mlvl = state.asset_manager.get_file(mlvl_id, Mlvl)
    try:
        name = mlvl.world_name
    except UnknownAssetId:
        name = f"MLVL {mlvl_id:08x}"

    return hello_imgui.DockableWindow(
        name,
        "MainDockSpace",
        gui_function_=functools.partial(_render_mlvl, mlvl, mlvl_id)
    )


def _render_mlvl(mlvl: Mlvl, mlvl_id: int) -> None:
    if imgui.begin_table("Areas", 2, imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_h):
        imgui.table_setup_column("Name", imgui.TableColumnFlags_.width_fixed)
        imgui.table_setup_column("Asset Id", imgui.TableColumnFlags_.width_fixed)
        imgui.table_headers_row()

        for area in mlvl.areas:
            imgui.table_next_row()

            imgui.table_next_column()
            imgui.text(area.name)

            imgui.table_next_column()
            if imgui.selectable(
                    f"{area.mrea_asset_id:08x}",
                    False,
                    imgui.SelectableFlags_.span_all_columns | imgui.SelectableFlags_.allow_item_overlap,
            )[1]:
                state.pending_new_docks.append(_create_dock_window_for_area(area))

        imgui.end_table()


def main_gui() -> None:
    if state.asset_manager is not None:
        if imgui.begin_table("All Assets", 3, imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_h):
            imgui.table_setup_column("Type", imgui.TableColumnFlags_.width_fixed)
            imgui.table_setup_column("Asset Id", imgui.TableColumnFlags_.width_fixed)
            imgui.table_setup_column("Name")

            imgui.table_headers_row()

            for i in state.mlvls:
                imgui.table_next_row()

                imgui.table_next_column()
                imgui.text(state.asset_manager.get_asset_type(i))

                imgui.table_next_column()
                if imgui.selectable(
                        f"{i:08x}",
                        False,
                        imgui.SelectableFlags_.span_all_columns | imgui.SelectableFlags_.allow_item_overlap,
                )[1]:
                    state.pending_new_docks.append(_create_dock_window_for_mlvl(i))

                imgui.table_next_column()
                imgui.text_disabled("<unknown>")

            imgui.end_table()
    else:
        imgui.text("No ISO loaded. Open one in the Projects menu above.")


def _show_menu() -> None:
    if imgui.begin_menu("Project"):
        if imgui.menu_item("Open ISO", "", False)[0]:
            state.open_file_dialog = portable_file_dialogs.open_file("Select ISO", filters=["*.iso"])
        imgui.end_menu()

    if state.open_file_dialog is not None and state.open_file_dialog.ready():
        files = state.open_file_dialog.result()
        if files:
            state.load_iso(Path(files[0]))
        state.open_file_dialog = None

    imgui.text_disabled("Bai")


def _pre_new_frame() -> None:
    if state.pending_new_docks:
        params = hello_imgui.get_runner_params().docking_params
        params.dockable_windows = params.dockable_windows + state.pending_new_docks
        state.pending_new_docks = []


def run_gui(args: argparse.Namespace) -> None:
    state.load_iso(args.iso)

    runner_params = hello_imgui.RunnerParams()
    runner_params.callbacks.show_menus = _show_menu
    runner_params.callbacks.pre_new_frame = _pre_new_frame
    runner_params.app_window_params.window_title = "Prime World Interactive Media Editor"
    runner_params.imgui_window_params.show_menu_app = False
    runner_params.imgui_window_params.show_menu_bar = True
    runner_params.imgui_window_params.show_status_bar = True

    runner_params.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    )
    # In this demo, we also demonstrate multiple viewports.
    # you can drag windows outside out the main window in order to put their content into new native windows
    runner_params.imgui_window_params.enable_viewports = True

    #
    # Define our dockable windows : each window provide a Gui callback, and will be displayed
    # in a docking split.
    #
    dockable_windows: list[hello_imgui.DockableWindow] = []

    def add_dockable_window(label: str, demo_gui: typing.Callable[[], None]):
        window = hello_imgui.DockableWindow()
        window.label = label
        window.dock_space_name = "MainDockSpace"
        window.gui_function = demo_gui
        dockable_windows.append(window)

    add_dockable_window("File List", main_gui)
    runner_params.docking_params.dockable_windows = dockable_windows

    immapp.run(runner_params=runner_params)
