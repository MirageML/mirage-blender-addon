import os

import bpy
import requests
from bpy.types import Operator, Panel, PropertyGroup
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor

MIRAGE_API = "https://api.mirageml.com"
DEFAULT_PROMPT = "a photo of a wooden house, minecraft, computer graphics"
PINEAPPLE_PROMPT = "a high quality photo of a pineapple"

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
    def get_mesh_url_for_prompt(prompt, api_key, auth_key):
        (project,) = [
            proj for proj in API.list_projects(api_key, auth_key) if proj["node"]["prompt"] == prompt
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

def batch_requests(params):
    path, url = params
    image_response = requests.get(url)
    with open(path, "wb") as f:
        f.write(image_response.content)


def enum_previews_from_directory_items(self, context):
    """EnumProperty callback"""
    enum_items = []

    if context is None: return enum_items

    wm = context.window_manager
    directory = wm.my_previews_dir

    # Get the preview collection (defined in register func).
    pcoll = preview_collection["main"]

    if directory == pcoll.my_previews_dir or len(pcoll.my_previews) != 0:
        return pcoll.my_previews

    data = API.list_projects(bpy.context.scene.PromptProps.api_key, bpy.context.scene.PromptProps.auth_token)

    if not data or len(data) == 0:
        return preview_collection["default"]

    if "thumbnails" in preview_collection:
        return preview_collection["thumbnails"]

    print("RUNNING")

    image_paths = []
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
        prompts.append(mesh["prompt"])

    p = ThreadPoolExecutor()
    p.map(batch_requests, zip(paths, urls))
    # Close the pool and wait for the work to finish
    p.shutdown(wait=True)

    for i, name in enumerate(image_paths):
        # generates a thumbnail preview for a file.
        filepath = os.path.join(directory, name)
        icon = pcoll.get(name)
        if not icon:
            thumb = pcoll.load(name, filepath, "IMAGE")
        else:
            thumb = pcoll[name]
        enum_items.append((name, prompts[i], "", thumb.icon_id, i))

    pcoll.my_previews = enum_items
    pcoll.my_previews_dir = directory
    return pcoll.my_previews


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
        API.create_project(prompt, bpy.context.scene.PromptProps.api_key, bpy.context.scene.PromptProps.auth_token)
        return {"FINISHED"}


class DownloadFromMirageOp(Operator):
    bl_idname = "mesh.download_from_mirage"
    bl_label = "Download from mirage"

    def execute(self, context):
        prompt = bpy.context.scene.PromptProps.existing_prompt

        cached_glbs = {
            DEFAULT_PROMPT: "/Users/jeremyfisher/Downloads/mesh.glb",
            PINEAPPLE_PROMPT: "/Users/jeremyfisher/Downloads/pineapple.glb",
        }

        bpy.ops.import_scene.gltf(
            filepath="/Users/amankishore/Downloads/hamburger.glb"
        )

        # if prompt in cached_glbs:
        #     bpy.ops.import_scene.gltf(filepath=cached_glbs[prompt])
        # else:
        #     # example_mesh_url = API.list_projects()[0]["node"]["meshGLBUrl"]
        #     mesh_url = API.get_mesh_url_for_prompt(prompt)
        #     with requests.get(mesh_url, stream=True) as r, NamedTemporaryFile(
        #         suffix=".glb"
        #     ) as t:
        #         for chunk in r.iter_content(chunk_size=8192):
        #             t.write(chunk)
        #         bpy.ops.import_scene.gltf(filepath=t.name)

        return {"FINISHED"}


class AddMiragePanel(Panel):
    bl_idname = "VIEW3D_PT_example_panel"
    bl_label = "TextTo3D"
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
        row.template_icon_view(wm, "my_previews", show_labels=True)

        row = self.layout.row()
        row.prop(wm, "my_previews")

        row = self.layout.row()
        row.operator(operator="mesh.download_from_mirage", text="Add to Scene")


# here be boilerplate


CLASSES = [
    CreateNewMirageProjectOp,
    DownloadFromMirageOp,
    AddMiragePanel,
    PromptProps,
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
        name="", description="", default=None,
        options={'ANIMATABLE'}, update=None, get=None, set=None
    )

    pcoll = bpy.utils.previews.new()
    pcoll.my_previews_dir = ""
    pcoll.my_previews = ()

    preview_collection["main"] = pcoll

    for class_ in CLASSES:
        bpy.utils.register_class(class_)
    bpy.types.Scene.PromptProps = bpy.props.PointerProperty(type=PromptProps)


def unregister():
    for class_ in CLASSES:
        bpy.utils.unregister_class(class_)
    del bpy.types.Scene.PromptProps
    bpy.utils.previews.remove(preview_collection["main"])


if __name__ == "__main__":
    register()
