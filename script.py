import os
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool
from tempfile import NamedTemporaryFile

import bpy
import requests
from bpy.types import Operator, Panel, PropertyGroup

MIRAGE_API = "https://api.mirageml.com"
DEFAULT_PROMPT = "a photo of a wooden house, minecraft, computer graphics"
PINEAPPLE_PROMPT = "a high quality photo of a pineapple"
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
        resp = requests.get(
            f"{MIRAGE_API}/texture-mesh/projects",
            headers=headers(api_key, auth_key),
        )
        return resp.json()["data"]

    @staticmethod
    def list_public_projects(page):
        resp = requests.get(
            f"{MIRAGE_API}/texture-mesh/public-projects", params={"page": str(page)}
        )
        return resp.json()["data"]

    @staticmethod
    def get_mesh_url_for_prompt(prompt, api_key, auth_key):
        (project,) = [
            proj
            for proj in API.list_projects(api_key, auth_key)
            if proj["node"]["prompt"] == prompt
        ]
        return project["meshGLBUrl"]

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
        glbs = []
        prompts = []
        paths = []
        urls = []
        for i, node in enumerate(data):
            mesh = node["node"]
            path = "/tmp/" + mesh["id"] + ".png"
            if not os.path.exists(path):
                paths.append(path)
                urls.append(mesh["meshPNGUrl"])
            image_paths.append(mesh["id"] + ".png")
            glbs.append(mesh["meshGLBUrl"])
            prompts.append(mesh["prompt"])
        return image_paths, glbs, prompts, paths, urls

    @staticmethod
    def get_public_mesh_data(data):
        image_paths = []
        glbs = []
        prompts = []
        paths = []
        urls = []
        for i, mesh in enumerate(data):
            path = "/tmp/" + mesh["id"] + ".png"
            if not os.path.exists(path):
                paths.append(path)
                urls.append(mesh["png_url"])
            image_paths.append(mesh["id"] + ".png")
            glbs.append(mesh["glb_url"])
            prompts.append(mesh["mesh_prompt"])
        return image_paths, glbs, prompts, paths, urls


def batch_requests(params):
    path, url = params
    image_response = requests.get(url)
    with open(path, "wb") as f:
        f.write(image_response.content)


def get_api_pages_enum(self, context):
    if context.scene.public_private_toggle == PUBLIC:
        n_pages = 5
    elif context.scene.public_private_toggle == PRIVATE:
        n_pages = 5
    else:
        raise ValueError

    return [(f"page-{i}", f"page-{i}", "", i) for i in range(1, n_pages + 1)]


def enum_previews_from_directory_items(self, context):
    """EnumProperty callback"""
    enum_items = []

    if context is None:
        return enum_items

    wm = context.window_manager
    directory = wm.my_previews_dir

    # Get the preview collection (defined in register func).
    pcoll = preview_collection["main"]

    if preview_collection["data"] == context.scene.public_private_toggle and preview_collection["page"] == context.scene.api_pages_toggle:
        return pcoll.my_previews

    preview_collection["page"] = context.scene.api_pages_toggle
    preview_collection["data"] = context.scene.public_private_toggle

    # if directory == pcoll.my_previews_dir or len(pcoll.my_previews) != 0:
    #     return pcoll.my_previews

    try:
        _, page = context.scene.api_pages_toggle.split("-")
    except:
        page = 1

    if context.scene.public_private_toggle == PUBLIC:
        data = API.list_public_projects(page=page)
    elif context.scene.public_private_toggle == PRIVATE:
        data = API.list_projects(
            bpy.context.scene.PromptProps.api_key,
            bpy.context.scene.PromptProps.auth_token,
        )
    else:
        raise ValueError

    if not data or len(data) == 0:
        return preview_collection["default"]

    # if "thumbnails" in preview_collection:
    #     return preview_collection["thumbnails"]

    print("RUNNING")

    if context.scene.public_private_toggle == PUBLIC:
        image_paths, glbs, prompts, paths, urls = API.get_public_mesh_data(data)
    elif context.scene.public_private_toggle == PRIVATE:
        image_paths, glbs, prompts, paths, urls = API.get_private_mesh_data(data)
    else:
        raise ValueError

    with ThreadPoolExecutor() as p:
        p.map(batch_requests, zip(paths, urls))

    for i, path in enumerate(image_paths):
        # generates a thumbnail preview for a file.
        filepath = os.path.join(directory, path)
        icon = pcoll.get(glbs[i])
        if not icon:
            thumb = pcoll.load(glbs[i], filepath, "IMAGE")
        else:
            thumb = pcoll[glbs[i]]
        enum_items.append((glbs[i], prompts[i], "", thumb.icon_id, i))

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
    existing_prompt: bpy.props.StringProperty(default=DEFAULT_PROMPT)
    api_key: bpy.props.StringProperty(default="")
    auth_token: bpy.props.StringProperty(default="")


class CreateNewMirageProjectOp(Operator):
    bl_idname = "mesh.create_new_mirage_project"
    bl_label = "Create new mirage project"

    def execute(self, context):
        prompt = bpy.context.scene.PromptProps.new_prompt
        API.create_project(
            prompt,
            bpy.context.scene.PromptProps.api_key,
            bpy.context.scene.PromptProps.auth_token,
        )
        return {"FINISHED"}


class DownloadFromMirageOp(Operator):
    bl_idname = "mesh.download_from_mirage"
    bl_label = "Download from mirage"

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

    def draw(self, context):
        props = bpy.context.scene.PromptProps

        self.layout.row().prop(props, "api_key", text="API Key")
        self.layout.row().prop(props, "auth_token", text="Authorization Key")

        self.layout.separator()

        self.layout.row().prop(props, "new_prompt", text="New Prompt")
        self.layout.row().operator(
            operator="mesh.create_new_mirage_project", text="Dreamfusion"
        )

        self.layout.separator()

        wm = context.window_manager
        #        row = self.layout.row()
        #        row.prop(wm, "my_previews_dir")

        row = self.layout.row()
        row.prop(context.scene, "public_private_toggle", expand=True, text="Show")

        row = self.layout.row()
        row.template_icon_view(wm, "my_previews", show_labels=True)

        row = self.layout.row()
        row.prop(wm, "my_previews")

        row = self.layout.row()
        row.prop(context.scene, "api_pages_toggle", expand=True, text="Results Page")

        self.layout.separator()

        row = self.layout.row()
        row.operator(operator="mesh.download_from_mirage", text="Add to Scene")


# here be boilerplate


CLASSES = [
    CreateNewMirageProjectOp,
    DownloadFromMirageOp,
    AddMiragePanel,
    PromptProps,
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

    bpy.types.Scene.api_pages_toggle = EnumProperty(
        items=get_api_pages_enum,
        name="Page",
        description="Select the projects page",
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
    del bpy.types.Scene.api_pages_toggle
    bpy.utils.previews.remove(preview_collection["main"])


if __name__ == "__main__":
    register()
