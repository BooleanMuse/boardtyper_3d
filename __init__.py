bl_info = {
    "name":        "Boardtyper 3D",
    "author":      "Skarmuse",
    "version":     (1, 0, 0),
    "blender":     (4, 2, 0),
    "location":    "View3D > Sidebar > Boardtyper 3D",
    "description": "Export Blender models to Tabletop Simulator JSON with full TTS support",
    "category":    "Import-Export",
}

import bpy
import json
import os
import random
import string
import shutil
import base64
import urllib.request
import urllib.error

from bpy.props import (
    StringProperty, EnumProperty, PointerProperty,
    IntProperty, FloatProperty, FloatVectorProperty,
    BoolProperty, CollectionProperty,
)
from bpy.types import Panel, Operator, PropertyGroup, UIList

# ──────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

TTS_TYPE_INDEX = {
    "Generic": 0, "Figurine": 1, "Dice": 2, "Coin": 3,
    "Board": 4,   "Chip": 5,    "Bag": 6,  "Infinite": 7,
}
TTS_MATERIAL_INDEX = {
    "Plastic": 0, "Wood": 1, "Metal": 2, "Cardboard": 3, "Glass": 4,
}

OBJECT_TYPES = [
    ("Generic",  "Generic",  "Standard game piece"),
    ("Coin",     "Coin",     "Coin / token"),
    ("Bag",      "Bag",      "Container bag"),
    ("Figurine", "Figurine", "Character figurine"),
    ("Board",    "Board",    "Game board"),
    ("Infinite", "Infinite", "Infinite bag"),
    ("Dice",     "Dice",     "Dice"),
    ("Chip",     "Chip",     "Poker-style chip"),
]

MATERIAL_TYPES = [
    ("Plastic",   "Plastic",   "Plastic material"),
    ("Wood",      "Wood",      "Wooden material"),
    ("Metal",     "Metal",     "Metal material"),
    ("Cardboard", "Cardboard", "Cardboard material"),
    ("Glass",     "Glass",     "Glass material"),
]

EXPORT_MODES = [
    ("LOCAL",  "Local",  "Uses file:/// paths. Only works on your machine."),
    ("GITHUB", "GitHub", "Uploads to GitHub. Works for everyone online."),
]

# ──────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def random_guid():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

def _safe_name(name):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)

def extract_material(obj, out_dir):
    color_diffuse = {"r": 1.0, "g": 1.0, "b": 1.0}
    diffuse_path  = None
    if not (obj.active_material and obj.active_material.use_nodes):
        return diffuse_path, color_diffuse
    nodes = obj.active_material.node_tree.nodes
    node  = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None) or \
            next((n for n in nodes if n.type == 'BSDF_DIFFUSE'), None)
    if not node:
        return diffuse_path, color_diffuse
    inp_name = 'Base Color' if node.type == 'BSDF_PRINCIPLED' else 'Color'
    inp = node.inputs[inp_name]
    if inp.is_linked:
        link = inp.links[0]
        if link.from_node.type == 'TEX_IMAGE' and link.from_node.image:
            src = bpy.path.abspath(link.from_node.image.filepath)
            if os.path.exists(src):
                ext = os.path.splitext(src)[1]
                dst = os.path.join(out_dir, f"{_safe_name(obj.name)}_diffuse{ext}")
                shutil.copy2(src, dst)
                diffuse_path = dst
    else:
        c = inp.default_value
        color_diffuse = {"r": round(c[0], 3), "g": round(c[1], 3), "b": round(c[2], 3)}
    return diffuse_path, color_diffuse

def get_row_position(index, origin_x=0.0, origin_y=1.5, origin_z=0.0, spacing=3.0, cols=5):
    col = index % cols
    row = index // cols
    return (
        round(origin_x + col * spacing, 3),
        round(origin_y, 3),
        round(origin_z + row * spacing, 3),
    )

def build_filter_lua(unbag_names):
    """Generates filterObjectEnter Lua that blocks objects whose name is in unbag_names."""
    if not unbag_names:
        return ""
    checks = " or ".join(f'n == "{name}"' for name in unbag_names)
    return (
        'function filterObjectEnter(obj)\n'
        '    local n = obj.getName() or ""\n'
        f'    if {checks} then return false end\n'
        '    return true\n'
        'end\n'
    )


# ──────────────────────────────────────────────────────────────────────────────
#  GITHUB API
# ──────────────────────────────────────────────────────────────────────────────

class GitHubAPI:
    BASE = "https://api.github.com"

    def __init__(self, token, username, repo):
        self.token    = token.strip()
        self.username = username.strip()
        self.repo     = repo.strip()
        self.headers  = {
            "Authorization": f"token {self.token}",
            "Accept":        "application/vnd.github.v3+json",
            "Content-Type":  "application/json",
            "User-Agent":    "Boardtyper3DAddon/1",
        }

    def _request(self, method, endpoint, data=None):
        url  = f"{self.BASE}{endpoint}"
        body = json.dumps(data).encode() if data else None
        req  = urllib.request.Request(url, data=body, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode()), r.status
        except urllib.error.HTTPError as e:
            err = json.loads(e.read().decode()) if e.fp else {}
            return err, e.code

    def validate_token(self):
        data, status = self._request("GET", "/user")
        if status == 200:
            return True, data.get("login", "?")
        return False, data.get("message", "Unknown error")

    def create_repo(self, description="Boardtyper 3D TTS Assets"):
        data, status = self._request("POST", "/user/repos", {
            "name": self.repo, "description": description,
            "private": False, "auto_init": True,
        })
        if status in (201, 422):
            return True, data.get("message", "")
        return False, data.get("message", "Unknown error")

    def _get_sha(self, path_in_repo):
        data, status = self._request("GET", f"/repos/{self.username}/{self.repo}/contents/{path_in_repo}")
        return data.get("sha") if status == 200 else None

    def upload_file(self, local_path, path_in_repo, commit_msg=None):
        with open(local_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()
        sha     = self._get_sha(path_in_repo)
        payload = {"message": commit_msg or f"Upload {os.path.basename(local_path)}", "content": content_b64}
        if sha:
            payload["sha"] = sha
        data, status = self._request("PUT", f"/repos/{self.username}/{self.repo}/contents/{path_in_repo}", payload)
        if status in (200, 201):
            return True, f"https://raw.githubusercontent.com/{self.username}/{self.repo}/main/{path_in_repo}"
        return False, data.get("message", "Unknown error")


# ──────────────────────────────────────────────────────────────────────────────
#  PROPERTY GROUPS
# ──────────────────────────────────────────────────────────────────────────────

class BagItem(PropertyGroup):
    target_name: StringProperty(name="Object Name", default="")
    quantity:    IntProperty(name="Quantity", default=1, min=1, max=999)

# Callback para sincronizar piece_name con obj.name
def on_piece_name_update(self, context):
    obj = self.id_data
    if obj and isinstance(obj, bpy.types.Object) and obj.type == 'MESH':
        new_name = self.piece_name.strip()
        if new_name and obj.name != new_name:
            obj.name = new_name
            if obj.name != self.piece_name:
                self["piece_name"] = obj.name


class BT3DObjectSettings(PropertyGroup):
    # Identity
    piece_name:    StringProperty(
        name="Piece Name", 
        default="",
        update=on_piece_name_update
    )
    object_type:   EnumProperty(name="Type",     items=OBJECT_TYPES,   default="Generic")
    material_type: EnumProperty(name="Material", items=MATERIAL_TYPES, default="Plastic")

    # World / bag visibility
    spawn_in_world: BoolProperty(
        name="Spawn in World",
        description="If OFF, this object will NOT appear as a standalone piece on the table. It can still be used as contents inside a Bag.",
        default=True,
    )
    show_in_bag_picker: BoolProperty(
        name="Show in Bag Picker",
        description="If OFF, this object will not appear in the dropdown when adding items to a Bag. Useful for pieces that only exist inside bags.",
        default=True,
    )

    # Bag filter
    can_be_bagged: BoolProperty(
        name="Can be stored in a Bag",
        description="If OFF, all Bag objects will auto-generate a filterObjectEnter that rejects this piece",
        default=True,
    )

    # Lua
    use_lua:    BoolProperty(name="Inject Lua Script", default=False)
    lua_file:   StringProperty(
        name="Lua File",
        description="Path to a .lua file to inject. Loaded fresh at export time.",
        subtype='FILE_PATH',
        default="",
    )
    lua_script: StringProperty(
        name="Lua Script",
        description="Paste Lua here, or use the file picker above.",
        default="",
    )

    # Set
    is_set:    BoolProperty(name="Is Set (multiple copies)", default=False)
    set_count: IntProperty(name="Count in Set", default=1, min=1, max=500)

    # Bag contents
    bag_items:       CollectionProperty(type=BagItem)
    bag_items_index: IntProperty(default=0)

    # Position
    use_custom_pos: BoolProperty(name="Override Position", default=False)
    custom_pos:     FloatVectorProperty(name="Position", size=3, default=(0.0, 1.5, 0.0))
    custom_rot_y:   FloatProperty(name="Rotation Y degrees", default=0.0)


class BT3DSceneSettings(PropertyGroup):
    output_dir:  StringProperty(name="Export Folder", subtype='DIR_PATH', default="//bt3d_export/")
    save_name:   StringProperty(name="Save Name", default="My Board Game")
    export_mode: EnumProperty(name="Mode", items=EXPORT_MODES, default="LOCAL")

    grid_spacing: FloatProperty(name="Grid Spacing", default=3.0, min=0.5, max=20.0)
    grid_cols:    IntProperty(name="Grid Columns",   default=5,   min=1,   max=20)
    grid_origin:  FloatVectorProperty(name="Grid Origin", size=3, default=(0.0, 1.5, 0.0))

    gh_token:          StringProperty(name="GitHub Token",    subtype='PASSWORD', default="")
    gh_username:       StringProperty(name="GitHub Username", default="")
    gh_repo:           StringProperty(name="Repository Name", default="boardtyper3d-assets")
    gh_subfolder:      StringProperty(name="Subfolder",       default="assets")
    gh_last_status:    StringProperty(default="—")
    gh_token_verified: BoolProperty(default=False)


# ──────────────────────────────────────────────────────────────────────────────
#  OPERATORS
# ──────────────────────────────────────────────────────────────────────────────

class BT3D_OT_RemoveObject(Operator):
    """Removes the object from the Boardtyper TTS export system by clearing its name."""
    bl_idname = "bt3d.remove_object"
    bl_label  = "Remove Object"
    bl_options = {'UNDO'}

    target_obj_name: StringProperty()

    def execute(self, context):
        obj = context.scene.objects.get(self.target_obj_name)
        if obj and hasattr(obj, "bt3d"):
            obj.bt3d.piece_name = ""
        return {'FINISHED'}


# ── Lua file picker ───────────────────────────────────────────────────────────

class BT3D_OT_LoadLua(Operator):
    """Open a file browser to load a .lua file into the active object."""
    bl_idname    = "bt3d.load_lua"
    bl_label     = "Load .lua File"
    bl_options   = {'REGISTER', 'UNDO'}

    filepath:    StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.lua", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "No active mesh object.")
            return {'CANCELLED'}
        path = bpy.path.abspath(self.filepath)
        if not os.path.isfile(path):
            self.report({'ERROR'}, f"File not found: {path}")
            return {'CANCELLED'}
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self.report({'ERROR'}, f"Could not read file: {e}")
            return {'CANCELLED'}
        obj.bt3d.lua_file   = self.filepath
        obj.bt3d.lua_script = content
        obj.bt3d.use_lua    = True
        self.report({'INFO'}, f"Loaded {os.path.basename(path)} ({len(content)} chars)")
        return {'FINISHED'}


# ── Bag item — scene picker (popup dialog with dropdown) ─────────────────────

def _scene_objects_enum(self, context):
    items = [("__NONE__", "— pick an object —", "")]
    for obj in context.scene.objects:
        if obj.type != 'MESH':
            continue
        s    = obj.bt3d
        name = s.piece_name.strip()
        if not name:
            continue
        if not s.show_in_bag_picker:
            continue
        label = f"{name}  [{s.object_type}]"
        items.append((name, label, ""))
    return items


class BT3D_OT_BagItemPick(Operator):
    """Pick a named scene object and add it to the bag contents list."""
    bl_idname  = "bt3d.bag_item_pick"
    bl_label   = "Add Object from Scene"
    bl_options = {'REGISTER', 'UNDO'}

    picked_name: EnumProperty(name="Object", items=_scene_objects_enum)
    quantity:    IntProperty(name="Quantity", default=1, min=1, max=999)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'MESH' and obj.bt3d.object_type in ("Bag", "Infinite"))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "picked_name", text="Object")
        layout.prop(self, "quantity",    text="Quantity")

    def execute(self, context):
        obj = context.active_object
        if not obj: return {'CANCELLED'}
        if self.picked_name == "__NONE__":
            self.report({'WARNING'}, "No object selected.")
            return {'CANCELLED'}
        item             = obj.bt3d.bag_items.add()
        item.target_name = self.picked_name
        item.quantity    = self.quantity
        return {'FINISHED'}


class BT3D_OT_BagItemRemove(Operator):
    bl_idname = "bt3d.bag_item_remove"
    bl_label  = "Remove Bag Item"

    def execute(self, context):
        obj = context.active_object
        if obj and obj.bt3d.bag_items:
            idx = obj.bt3d.bag_items_index
            obj.bt3d.bag_items.remove(idx)
            obj.bt3d.bag_items_index = max(0, idx - 1)
        return {'FINISHED'}


class BT3D_UL_BagItems(UIList):
    bl_idname = "BT3D_UL_bag_items"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop):
        row    = layout.row(align=True)
        exists = any(o.type == 'MESH' and o.bt3d.piece_name.strip() == item.target_name for o in context.scene.objects)
        ico = 'OBJECT_DATA' if exists else 'ERROR'
        row.label(text=item.target_name or "(empty)", icon=ico)
        row.prop(item, "quantity", text="x", emboss=True)


class BT3D_OT_GH_Verify(Operator):
    bl_idname = "bt3d.gh_verify"
    bl_label  = "Verify Token"

    def execute(self, context):
        s = context.scene.bt3d_scene
        if not s.gh_token or not s.gh_username:
            self.report({'ERROR'}, "Fill in Token and Username first.")
            return {'CANCELLED'}
        api = GitHubAPI(s.gh_token, s.gh_username, s.gh_repo)
        ok, info = api.validate_token()
        if ok:
            s.gh_token_verified = True
            s.gh_last_status    = f"✓ Connected as: {info}"
            self.report({'INFO'}, f"Token valid! Logged in as: {info}")
        else:
            s.gh_token_verified = False
            s.gh_last_status    = f"✗ Error: {info}"
            self.report({'ERROR'}, f"Token invalid: {info}")
        return {'FINISHED'}


class BT3D_OT_GH_CreateRepo(Operator):
    bl_idname = "bt3d.gh_create_repo"
    bl_label  = "Create / Verify Repository"

    def execute(self, context):
        s = context.scene.bt3d_scene
        if not s.gh_token_verified:
            self.report({'ERROR'}, "Verify your token first.")
            return {'CANCELLED'}
        api = GitHubAPI(s.gh_token, s.gh_username, s.gh_repo)
        ok, msg = api.create_repo()
        if ok:
            s.gh_last_status = f"✓ Repo '{s.gh_repo}' ready."
            self.report({'INFO'}, f"Repo '{s.gh_repo}' OK.")
        else:
            s.gh_last_status = f"✗ Repo error: {msg}"
            self.report({'ERROR'}, f"Could not create repo: {msg}")
        return {'FINISHED'}


class BT3D_OT_Export(Operator):
    bl_idname  = "bt3d.export"
    bl_label   = "Export to TTS"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        for obj in context.scene.objects:
            if obj.type == 'MESH' and obj.bt3d.piece_name.strip():
                return True
        return False

    def execute(self, context):
        s_scene    = context.scene.bt3d_scene
        out_dir    = bpy.path.abspath(s_scene.output_dir)
        use_github = (s_scene.export_mode == "GITHUB")
        os.makedirs(out_dir, exist_ok=True)

        api = None
        if use_github:
            if not s_scene.gh_token_verified:
                self.report({'ERROR'}, "Verify your GitHub token first.")
                return {'CANCELLED'}
            api = GitHubAPI(s_scene.gh_token, s_scene.gh_username, s_scene.gh_repo)
            api.create_repo()

        subfolder = s_scene.gh_subfolder.strip("/") if s_scene.gh_subfolder.strip() else ""

        unbag_names = [
            obj.bt3d.piece_name.strip()
            for obj in context.scene.objects
            if obj.type == 'MESH' and obj.bt3d.piece_name.strip() and not obj.bt3d.can_be_bagged
        ]

        object_states  = []
        errors         = []
        auto_index     = 0
        piece_json_map = {}

        # ── First pass ────────────────────────────────────────────────────
        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            s          = obj.bt3d
            piece_name = s.piece_name.strip()
            if not piece_name:
                continue

            is_bag   = s.object_type in ("Bag", "Infinite")
            type_idx = TTS_TYPE_INDEX.get(s.object_type, 0)
            mat_idx  = TTS_MATERIAL_INDEX.get(s.material_type, 0)
            count    = s.set_count if s.is_set else 1

            saved_loc = obj.location.copy()
            saved_rot = obj.rotation_euler.copy()
            obj.location       = (0, 0, 0)
            obj.rotation_euler = (0, 0, 0)
            context.view_layer.update()
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            obj_filename = f"{_safe_name(piece_name)}.obj"
            obj_path     = os.path.join(out_dir, obj_filename)
            bpy.ops.wm.obj_export(
                filepath=obj_path,
                export_selected_objects=True,
                export_uv=True, export_normals=True,
                export_materials=False, export_triangulated_mesh=True,
            )
            obj.location       = saved_loc
            obj.rotation_euler = saved_rot
            context.view_layer.update()

            diffuse_local, color_diffuse = extract_material(obj, out_dir)

            if use_github:
                safe         = _safe_name(piece_name)
                repo_mesh    = f"{subfolder}/{safe}.obj" if subfolder else f"{safe}.obj"
                ok, mesh_url = api.upload_file(obj_path, repo_mesh, f"Upload mesh: {piece_name}")
                if not ok:
                    errors.append(f"Mesh upload failed for '{piece_name}': {mesh_url}")
                    mesh_url = ""
                diffuse_url = ""
                if diffuse_local:
                    ext      = os.path.splitext(diffuse_local)[1]
                    repo_d   = f"{subfolder}/{safe}_diffuse{ext}" if subfolder else f"{safe}_diffuse{ext}"
                    ok2, diffuse_url = api.upload_file(diffuse_local, repo_d, f"Upload texture: {piece_name}")
                    if not ok2:
                        errors.append(f"Texture upload failed for '{piece_name}': {diffuse_url}")
                        diffuse_url = ""
            else:
                mesh_url    = f"file:///{obj_path}".replace("\\", "/")
                diffuse_url = f"file:///{diffuse_local}".replace("\\", "/") if diffuse_local else ""

            lua_content = ""
            if s.use_lua:
                if s.lua_file:
                    abs_lua = bpy.path.abspath(s.lua_file)
                    if os.path.isfile(abs_lua):
                        try:
                            with open(abs_lua, "r", encoding="utf-8") as lf:
                                lua_content = lf.read()
                        except Exception:
                            lua_content = s.lua_script
                    else:
                        lua_content = s.lua_script
                else:
                    lua_content = s.lua_script

            if is_bag and unbag_names:
                filter_lua = build_filter_lua(unbag_names)
                lua_content = (lua_content.rstrip() + "\n\n" + filter_lua) if lua_content else filter_lua

            _pn  = piece_name
            _bag = is_bag
            _ti  = type_idx
            _mi  = mat_idx
            _cd  = color_diffuse
            _mu  = mesh_url
            _du  = diffuse_url
            _lua = lua_content
            _sx, _sy, _sz = obj.scale.x, obj.scale.y, obj.scale.z

            def build_entry(px, py, pz, ry=0.0):
                e = {
                    "Name":     "Custom_Model_Bag" if _bag else "Custom_Model",
                    "Nickname": _pn,
                    "Transform": {
                        "posX": px, "posY": py, "posZ": pz,
                        "rotX": 0.0, "rotY": ry, "rotZ": 0.0,
                        "scaleX": round(_sx, 4),
                        "scaleY": round(_sz, 4),
                        "scaleZ": round(_sy, 4),
                    },
                    "ColorDiffuse": _cd,
                    "CustomMesh": {
                        "MeshURL":       _mu,
                        "DiffuseURL":    _du,
                        "ColliderURL":   "",
                        "Convex":        True,
                        "TypeIndex":     _ti,
                        "MaterialIndex": _mi,
                    },
                    "LuaScript": _lua,
                    "GUID":      random_guid(),
                    "Tags":      [],
                }
                if _bag: e["ContainedObjects"] = []
                return e

            entries = []
            for i in range(count):
                if s.use_custom_pos and count == 1:
                    px, py, pz = tuple(s.custom_pos)
                    ry = s.custom_rot_y
                elif s.use_custom_pos:
                    gx, gy, gz = tuple(s.custom_pos)
                    px, py, pz = get_row_position(i, gx, gy, gz, s_scene.grid_spacing, s_scene.grid_cols)
                    ry = s.custom_rot_y
                else:
                    px, py, pz = get_row_position(auto_index, *s_scene.grid_origin, s_scene.grid_spacing, s_scene.grid_cols)
                    ry = 0.0
                    auto_index += 1
                entries.append(build_entry(px, py, pz, ry))

            piece_json_map[piece_name] = entries

        # ── Second pass: fill bags ────────────────────────────────────────
        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            s          = obj.bt3d
            piece_name = s.piece_name.strip()
            if not piece_name or piece_name not in piece_json_map:
                continue
            if s.object_type not in ("Bag", "Infinite"):
                continue
            for bag_entry in piece_json_map[piece_name]:
                for bag_item in s.bag_items:
                    target = bag_item.target_name.strip()
                    qty    = bag_item.quantity
                    if not target:
                        continue
                    src = piece_json_map.get(target)
                    if not src:
                        errors.append(f"Bag '{piece_name}': target '{target}' not found.")
                        continue
                    for _ in range(qty):
                        clone = json.loads(json.dumps(src[0]))
                        clone["GUID"] = random_guid()
                        clone["Transform"].update({"posX": 0.0, "posY": 0.0, "posZ": 0.0})
                        bag_entry["ContainedObjects"].append(clone)

        # ── Flatten ────────────────────────────────────────────────────────
        spawn_names = {
            obj.bt3d.piece_name.strip()
            for obj in context.scene.objects
            if obj.type == 'MESH' and obj.bt3d.piece_name.strip() and obj.bt3d.spawn_in_world
        }
        for piece_name, entries in piece_json_map.items():
            if piece_name in spawn_names:
                object_states.extend(entries)

        # ── Write JSON ────────────────────────────────────────────────────
        tts_save = {
            "SaveName":     s_scene.save_name,
            "GameMode":     s_scene.save_name,
            "Table":        "TableOctagon",
            "ObjectStates": object_states,
        }
        json_filename = f"{_safe_name(s_scene.save_name)}_save.json"
        json_path     = os.path.join(out_dir, json_filename)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(tts_save, f, indent=2, ensure_ascii=False)

        if use_github:
            repo_json = f"{subfolder}/{json_filename}" if subfolder else json_filename
            api.upload_file(json_path, repo_json, "Upload TTS savefile")

        mode_label = "GITHUB ✓" if use_github else "LOCAL"
        s_scene.gh_last_status = (
            f"[{mode_label}] {len(object_states)} objects"
            + (f" | {len(errors)} errors" if errors else " | OK")
        )
        if errors:
            self.report({'WARNING'}, f"Done with {len(errors)} errors.")
        else:
            self.report({'INFO'}, f"[{mode_label}] Export complete — {len(object_states)} objects.")

        return {'FINISHED'}


# ──────────────────────────────────────────────────────────────────────────────
#  UI PANELS
# ──────────────────────────────────────────────────────────────────────────────

CATEGORY = "Boardtyper 3D"

class BT3D_PT_Object(Panel):
    bl_label       = "1. Object Settings"
    bl_idname      = "BT3D_PT_object"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = CATEGORY

    def draw(self, context):
        layout = self.layout
        obj    = context.active_object

        if not (obj and obj.type == 'MESH'):
            layout.label(text="Select a mesh object.", icon='ERROR')
            return

        s = obj.bt3d

        # Identity
        box = layout.box()
        box.label(text="Identity", icon='OBJECT_DATA')
        box.prop(s, "piece_name",    text="Name")
        box.prop(s, "object_type",   text="Type")
        box.prop(s, "material_type", text="Material")

        # Visibility / bag flags
        flag_box = layout.box()
        flag_box.label(text="Visibility & Bag Rules", icon='RESTRICT_VIEW_OFF')

        row = flag_box.row(align=True)
        icon = 'CHECKBOX_HLT' if s.spawn_in_world else 'CHECKBOX_DEHLT'
        row.prop(s, "spawn_in_world", icon=icon)
        if not s.spawn_in_world:
            flag_box.label(text="Won't appear on the table (bag-only piece).", icon='INFO')

        row2 = flag_box.row(align=True)
        icon2 = 'CHECKBOX_HLT' if s.show_in_bag_picker else 'CHECKBOX_DEHLT'
        row2.prop(s, "show_in_bag_picker", icon=icon2)
        if not s.show_in_bag_picker:
            flag_box.label(text="Hidden from the bag contents dropdown.", icon='INFO')

        row3 = flag_box.row(align=True)
        icon3 = 'CHECKBOX_HLT' if s.can_be_bagged else 'CHECKBOX_DEHLT'
        row3.prop(s, "can_be_bagged", icon=icon3)
        if not s.can_be_bagged:
            flag_box.label(text="All bags will auto-block this object.", icon='INFO')

        # Lua
        lua_box = layout.box()
        lua_box.prop(s, "use_lua", icon='SCRIPT')
        if s.use_lua:
            file_row = lua_box.row(align=True)
            file_row.prop(s, "lua_file", text="")
            file_row.operator("bt3d.load_lua", text="", icon='FILEBROWSER')

            if s.lua_file:
                fname  = os.path.basename(bpy.path.abspath(s.lua_file))
                exists = os.path.isfile(bpy.path.abspath(s.lua_file))
                ico    = 'CHECKMARK' if exists else 'ERROR'
                lua_box.label(text=f"{'Loaded' if exists else 'Not found'}: {fname}", icon=ico)
            else:
                lua_box.label(text="Or paste Lua directly:", icon='INFO')
                lua_box.prop(s, "lua_script", text="")

        # Set
        set_box = layout.box()
        set_box.prop(s, "is_set", icon='DUPLICATE')
        if s.is_set:
            set_box.prop(s, "set_count")

        # Bag contents
        if s.object_type in ("Bag", "Infinite"):
            bag_box = layout.box()
            bag_box.label(text="Bag Contents", icon='PACKAGE')
            row = bag_box.row()
            row.template_list(
                "BT3D_UL_bag_items", "",
                s, "bag_items",
                s, "bag_items_index",
                rows=4,
            )
            col = row.column(align=True)
            col.operator("bt3d.bag_item_pick",   icon='ADD',    text="")
            col.operator("bt3d.bag_item_remove", icon='REMOVE', text="")
            if s.bag_items:
                bag_box.label(text="Red icon = object not found in scene.", icon='INFO')

        # Position
        pos_box = layout.box()
        pos_box.label(text="Position", icon='ORIENTATION_GLOBAL')
        pos_box.prop(s, "use_custom_pos")
        if s.use_custom_pos:
            pos_box.prop(s, "custom_pos",   text="XYZ")
            pos_box.prop(s, "custom_rot_y", text="Rot Y°")
        else:
            pos_box.label(text="Auto-layout grid (configure in Scene tab)", icon='INFO')


class BT3D_PT_ObjectList(Panel):
    bl_label       = "2. Scene Objects"
    bl_idname      = "BT3D_PT_object_list"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = CATEGORY

    TYPE_ICONS = {
        "Generic":  'MESH_CUBE',      "Coin":     'MESH_CIRCLE',
        "Bag":      'PACKAGE',        "Figurine": 'ARMATURE_DATA',
        "Board":    'MESH_PLANE',     "Infinite": 'INFINITY',
        "Dice":     'MESH_ICOSPHERE', "Chip":     'MESH_CYLINDER',
    }

    def draw(self, context):
        layout  = self.layout
        box     = layout.box()
        has_any = False

        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            s    = obj.bt3d
            name = s.piece_name.strip()
            if not name:
                continue
            has_any = True
            
            row  = box.row(align=True)
            icon = self.TYPE_ICONS.get(s.object_type, 'OBJECT_DATA')
            
            # Left side (Name)
            row.label(text=name, icon=icon)
            
            # Middle/Right side (Status)
            row.label(text=s.object_type)
            if s.is_set:
                row.label(text=f"x{s.set_count}")
            if not s.spawn_in_world:
                row.label(text="", icon='RESTRICT_VIEW_ON')
            if not s.show_in_bag_picker:
                row.label(text="", icon='HIDE_ON')
            if not s.can_be_bagged:
                row.label(text="", icon='LOCKED')
            if s.use_lua:
                row.label(text="", icon='SCRIPT')
            
            # The X Button to remove from TTS system
            rem = row.operator("bt3d.remove_object", text="", icon='X')
            rem.target_obj_name = obj.name

        if not has_any:
            box.label(text="No named objects yet.", icon='INFO')
            box.label(text="Select a mesh → panel 1 → set Piece Name.")


class BT3D_PT_Scene(Panel):
    bl_label       = "3. Scene & Export"
    bl_idname      = "BT3D_PT_scene"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = CATEGORY

    def draw(self, context):
        layout = self.layout
        s      = context.scene.bt3d_scene

        meta = layout.box()
        meta.label(text="Save Info", icon='FILE_BLEND')
        meta.prop(s, "save_name",  text="Game Name")
        meta.prop(s, "output_dir", text="Export Folder")

        grid_box = layout.box()
        grid_box.label(text="Auto-Layout Grid", icon='GRID')
        grid_box.prop(s, "grid_origin",  text="Origin")
        grid_box.prop(s, "grid_spacing", text="Spacing")
        grid_box.prop(s, "grid_cols",    text="Columns")

        layout.separator()

        mode_box = layout.box()
        mode_box.label(text="Export Mode", icon='WORLD')
        mode_box.prop(s, "export_mode", expand=True)

        layout.separator()

        if s.export_mode == "LOCAL":
            info = layout.box()
            info.label(text="Assets will use local file:/// paths.", icon='INFO')
            info.label(text="Only works on your machine.")
        else:
            self._draw_github(layout, s)

        layout.separator()

        status = layout.box()
        status.label(text=f"Status: {s.gh_last_status}", icon='INFO')

        ready = BT3D_OT_Export.poll(context)
        gh_ok = (s.export_mode == "LOCAL") or s.gh_token_verified
        big   = layout.row()
        big.scale_y = 2.0
        big.enabled = ready and gh_ok
        icon  = 'WORLD' if s.export_mode == "GITHUB" else 'EXPORT'
        label = f"Export  [{s.export_mode}]" if (ready and gh_ok) else "Name at least one object first"
        big.operator("bt3d.export", icon=icon, text=label)

    def _draw_github(self, layout, s):
        step1 = layout.box()
        step1.label(text="GitHub Credentials", icon='LOCKED')
        col = step1.column(align=True)
        col.prop(s, "gh_username", text="Username")
        col.prop(s, "gh_token",    text="Token")
        row = step1.row(align=True)
        row.operator("bt3d.gh_verify", icon='CHECKMARK', text="Verify Token")
        if s.gh_token_verified:
            row.label(text="✓ OK", icon='CHECKBOX_HLT')
        else:
            row.label(text="Not verified", icon='CHECKBOX_DEHLT')

        step2 = layout.box()
        step2.label(text="Repository", icon='FILE_FOLDER')
        col2 = step2.column(align=True)
        col2.enabled = s.gh_token_verified
        col2.prop(s, "gh_repo",      text="Repo Name")
        col2.prop(s, "gh_subfolder", text="Subfolder")
        step2.operator("bt3d.gh_create_repo", icon='NEWFOLDER', text="Create / Verify Repository")


# ──────────────────────────────────────────────────────────────────────────────
#  REGISTRATION
# ──────────────────────────────────────────────────────────────────────────────

classes = [
    BagItem,
    BT3DObjectSettings,
    BT3DSceneSettings,
    BT3D_UL_BagItems,
    BT3D_OT_LoadLua,
    BT3D_OT_BagItemPick,
    BT3D_OT_BagItemRemove,
    BT3D_OT_RemoveObject,
    BT3D_OT_GH_Verify,
    BT3D_OT_GH_CreateRepo,
    BT3D_OT_Export,
    BT3D_PT_Object,
    BT3D_PT_ObjectList,
    BT3D_PT_Scene,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.bt3d      = PointerProperty(type=BT3DObjectSettings)
    bpy.types.Scene.bt3d_scene = PointerProperty(type=BT3DSceneSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Object.bt3d
    del bpy.types.Scene.bt3d_scene

if __name__ == "__main__":
    register()