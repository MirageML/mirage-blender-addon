import os
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool
from tempfile import NamedTemporaryFile

import bpy
import requests
from bpy.types import Operator, Panel, PropertyGroup

bl_info = {
    "name": "Mirage",
    "category": "Import-Export",
    "version": (0, 1, 0),
    "blender": (3, 3, 0),
    'location': 'View3D > Tools > Mirage',
    'description': 'Browse and Create 3D Models on Mirage',
    'isDraft': False,
    'developer': "MirageML Inc.",
    'url': 'https://github.com/MirageML/mirage-blender-addon'
}

MIRAGE_API = "https://api.mirageml.com"
PUBLIC, PRIVATE = "PUBLIC", "PRIVATE"

# app state
preview_collection = {}
custom_icons = {}


def headers(api_key, auth_key):
    return {
        "Content-Type": "application/json",
        "Authorization": auth_key,
        "x-api-key": api_key,
    }


class API:
    @staticmethod
    def list_projects(api_key, auth_key):
        search_query = ""
        try: search_query = bpy.context.scene.PromptProps.search
        except: pass

        params = {
            "filter": search_query
        }

        resp = requests.get(
            f"{MIRAGE_API}/texture-mesh/projects",
            headers=headers(api_key, auth_key),
            params=params
        )
        print(resp.json())
        return resp.json()["data"]

    @staticmethod
    def list_public_projects():
        page_number = 1
        search_query = ""
        try: page_number = bpy.context.scene.PromptProps.page_number = 5
        except: pass

        try: search_query = bpy.context.scene.PromptProps.search
        except: pass

        print(page_number, search_query)

        params = {
            # "page": str(page_number),
            "filter": search_query
        }
        resp = requests.get(
            f"{MIRAGE_API}/texture-mesh/public-projects", params=params
        )
        return resp.json()["data"]

    @staticmethod
    def get_mesh_url_for_prompt(prompt, api_key, auth_key):
        (project,) = [
            proj
            for proj in API.list_projects(api_key, auth_key)
            if proj["node"]["prompt"] == prompt
        ]
        return project["glbUrl"]

    @staticmethod
    def create_project(prompt, api_key, auth_key):
        resp = requests.post(
            f"{MIRAGE_API}/texture-mesh/project/create",
            json={"prompt": prompt},
            headers=headers(api_key, auth_key),
        )
        return resp.json()

    @staticmethod
    def get_private_mesh_data(data):
        image_paths = []
        gltfs = []
        prompts = []
        paths = []
        urls = []
        for i, mesh in enumerate(data):
            if mesh["gltfUrl"] is None: continue
            path = "/tmp/" + mesh["id"] + ".png"
            if not os.path.exists(path):
                paths.append(path)
                urls.append(mesh["pngUrl"])
            image_paths.append(mesh["id"] + ".png")
            gltfs.append(mesh["gltfUrl"])
            prompts.append(mesh["prompt"])
        return image_paths, gltfs, prompts, paths, urls

    @staticmethod
    def get_public_mesh_data(data):
        image_paths = []
        gltfs = []
        prompts = []
        paths = []
        urls = []
        for i, mesh in enumerate(data):
            if mesh["gltf_url"] is None: continue
            path = "/tmp/" + mesh["id"] + ".png"
            if not os.path.exists(path):
                paths.append(path)
                urls.append(mesh["png_url"])
            image_paths.append(mesh["id"] + ".png")
            gltfs.append(mesh["gltf_url"])
            prompts.append(mesh["mesh_prompt"])
        return image_paths, gltfs, prompts, paths, urls


def batch_requests(params):
    path, url = params
    image_response = requests.get(url)
    with open(path, "wb") as f:
        f.write(image_response.content)


def enum_previews_from_directory_items(self, context):
    """EnumProperty callback"""
    enum_items = []

    if context is None:
        return enum_items

    wm = context.window_manager
    directory = wm.my_previews_dir

    # Get the preview collection (defined in register func).
    pcoll = preview_collection["main"]

    if preview_collection["data"] == context.scene.public_private_toggle and preview_collection["page"] == context.scene.PromptProps.page_number and preview_collection["search"] == context.scene.PromptProps.search:
        return pcoll.my_previews

    preview_collection["page"] = context.scene.PromptProps.page_number
    preview_collection["data"] = context.scene.public_private_toggle
    preview_collection["search"] = context.scene.PromptProps.search

    if context.scene.public_private_toggle == PRIVATE:
        data = API.list_projects(
            context.scene.PromptProps.api_key,
            context.scene.PromptProps.auth_token,
        )
    else:
        data = API.list_public_projects()

    if not data or len(data) == 0:
        return preview_collection["default"]

    if context.scene.public_private_toggle == PUBLIC:
        image_paths, gltf, prompts, paths, urls = API.get_public_mesh_data(data)
    elif context.scene.public_private_toggle == PRIVATE:
        image_paths, gltf, prompts, paths, urls = API.get_private_mesh_data(data)
    else:
        raise ValueError

    with ThreadPoolExecutor() as p:
        p.map(batch_requests, zip(paths, urls))

    for i, path in enumerate(image_paths):
        # generates a thumbnail preview for a file.
        filepath = os.path.join(directory, path)
        icon = pcoll.get(gltf[i])
        print(gltf[i])
        if not icon:
            thumb = pcoll.load(gltf[i], filepath, "IMAGE")
        else:
            thumb = pcoll[gltf[i]]
        enum_items.append((gltf[i], prompts[i], "", thumb.icon_id, i))

    pcoll.my_previews = enum_items
    pcoll.my_previews_dir = directory
    return pcoll.my_previews

def enum_toggle(self, context):
    """EnumProperty callback"""
    enum_items = []
    if context.scene.PromptProps.api_key and context.scene.PromptProps.auth_token:
        enum_items = [(PUBLIC, "Public", "", 1), (PRIVATE, "Private", "", 2)]
    else:
        enum_items = [(PUBLIC, "Public", "", 1)]
    return enum_items

class PromptProps(PropertyGroup):
    new_prompt: bpy.props.StringProperty(default="")
    api_key: bpy.props.StringProperty(default="")
    auth_token: bpy.props.StringProperty(default="")
    search_query: bpy.props.StringProperty(default="")
    search: bpy.props.StringProperty(default="")
    page_number: bpy.props.IntProperty(default=1, min=1, max=5)

class CreateNewMirageProjectOp(Operator):
    bl_idname = "mesh.create_new_mirage_project"
    bl_label = "Create new Mirage project"
    bl_description ="Create new Mirage project"

    def execute(self, context):
        prompt = context.scene.PromptProps.new_prompt
        API.create_project(
            prompt,
            context.scene.PromptProps.api_key,
            context.scene.PromptProps.auth_token,
        )
        return {"FINISHED"}

class SearchMirageProjectOp(Operator):
    bl_idname = "mesh.search_projects"
    bl_label = "Search projects on app.mirageml.com"
    bl_description ="Search projects"

    def execute(self, context):
        context.scene.PromptProps.search = context.scene.PromptProps.search_query
        return {"FINISHED"}


class DownloadFromMirageOp(Operator):
    bl_idname = "mesh.download_from_mirage"
    bl_label = "Download from Mirage"
    bl_description ="Download from Mirage"

    def execute(self, context):
#        cached_glbs = None
#        if prompt in cached_glbs:
#            bpy.ops.import_scene.gltf(filepath=cached_glbs[prompt])
#        else:
        mesh_url = bpy.context.window_manager.my_previews
        with requests.get(mesh_url, stream=True) as r, NamedTemporaryFile(
            suffix=".glb"
        ) as t:
            for chunk in r.iter_content(chunk_size=8192):
                t.write(chunk)
            bpy.ops.import_scene.gltf(filepath=t.name)

        return {"FINISHED"}


class AddMiragePanel(Panel):
    bl_idname = "VIEW3D_PT_example_panel"
    bl_label = "MirageML"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = 'Mirage'
    bl_context = 'objectmode'

    def draw(self, context):
        props = bpy.context.scene.PromptProps

        self.layout.row().prop(props, "api_key", text="API Key")
        self.layout.row().prop(props, "auth_token", text="Authorization Key")

        self.layout.separator()

        if context.scene.public_private_toggle == PRIVATE:
            self.layout.row().prop(props, "new_prompt", text="Create Asset from Prompt")
            self.layout.row().operator(
                operator="mesh.create_new_mirage_project", text="Dreamfusion"
            )

            self.layout.separator()

        wm = context.window_manager

        row = self.layout.row()
        row.prop(context.scene, "public_private_toggle", expand=True, text="Show")

        self.layout.row().prop(props, "search_query", text="Search:")
        self.layout.row().operator(
            operator="mesh.search_projects", text="Search"
        )

        row = self.layout.row()
        row.template_icon_view(wm, "my_previews", show_labels=True)

        row = self.layout.row()
        row.prop(wm, "my_previews")

        # TODO: Fix the pagination
        # if context.scene.public_private_toggle == PUBLIC:
        #     row = self.layout.row()
        #     self.layout.row().prop(props, "page_number", text="Page Number")
        #     # row.prop(context.scene, "api_pages_toggle", expand=True, text="Results Page")

        self.layout.separator()

        row = self.layout.row()
        row.operator(operator="mesh.download_from_mirage", text="Add to Scene")



CLASSES = [
    CreateNewMirageProjectOp,
    DownloadFromMirageOp,
    AddMiragePanel,
    PromptProps,
    SearchMirageProjectOp
    # PublicPrivateProjectLibraryToggle,
]


def register():
    import bpy.utils.previews
    from bpy.props import EnumProperty, StringProperty
    from bpy.types import WindowManager

    WindowManager.my_previews_dir = StringProperty(
        name="Folder Path", subtype="DIR_PATH", default="/tmp/"
    )

    WindowManager.my_previews = EnumProperty(
        items=enum_previews_from_directory_items,
        name="",
        description="",
        default=None,
        options={"ANIMATABLE"},
        update=None,
        get=None,
        set=None,
    )


    pcoll = bpy.utils.previews.new()
    pcoll.my_previews_dir = ""
    pcoll.my_previews = ()

    preview_collection["main"] = pcoll
    preview_collection["data"] = None
    preview_collection["page"] = None
    preview_collection["search"] = None

    for class_ in CLASSES:
        bpy.utils.register_class(class_)
    bpy.types.Scene.PromptProps = bpy.props.PointerProperty(type=PromptProps)

    # Update public_private_toggle based on api key and auth token
    bpy.types.Scene.public_private_toggle = bpy.props.EnumProperty(
        items=enum_toggle,
        name="Public",
        description="Selected action center mode",
        default=None,
        options={"ANIMATABLE"},
        update=None,
        get=None,
        set=None,
    )


def unregister():
    for class_ in CLASSES:
        bpy.utils.unregister_class(class_)
    del bpy.types.Scene.PromptProps
    del bpy.types.Scene.public_private_toggle
    bpy.utils.previews.remove(preview_collection["main"])


if __name__ == "__main__":
    register()
