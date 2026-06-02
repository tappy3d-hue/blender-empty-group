"""
Empty Group Addon for Blender
==============================
選択したメッシュオブジェクトのバウンディングボックス中心にエンプティを作成し、
ペアレント化してグループ管理します。

ショートカット:
  Ctrl+Shift+G  グループ化（完了後、自動でサイズ変更モードへ移行）
  Ctrl+Shift+E  選択エンプティのサイズをインタラクティブに変更
  Ctrl+Shift+R  選択エンプティの名前変更
  Ctrl+Shift+U  グループ解除

サイズ変更モードの操作:
  マウス左右移動  サイズ調整
  数値キー        数値を直接入力
  Enter / LMB    確定
  Esc / RMB      キャンセル（サイズを元に戻す）
"""

bl_info = {
    "name": "Empty Group",
    "author": "Custom",
    "version": (3, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Empty Group  /  Ctrl+Shift+G",
    "description": "選択オブジェクトの中点にエンプティを作成し、ペアレント化してグループ管理します",
    "category": "Object",
}

import bpy
from bpy.props import (
    StringProperty, BoolProperty, EnumProperty,
    FloatProperty, PointerProperty,
)
from mathutils import Vector


# ─────────────────────────────────────────────
# シーンごとの設定（PropertyGroup）
# ─────────────────────────────────────────────

class EmptyGroupSettings(bpy.types.PropertyGroup):
    default_size: FloatProperty(
        name="デフォルトサイズ",
        description="グループ化時に作成するエンプティのデフォルト表示サイズ",
        default=1.0,
        min=0.001,
        soft_max=20.0,
        step=10,
        precision=3,
    )
    default_empty_type: EnumProperty(
        name="デフォルト種類",
        items=[
            ('PLAIN_AXES',   "Plain Axes",   "十字軸"),
            ('ARROWS',       "Arrows",       "矢印"),
            ('SINGLE_ARROW', "Single Arrow", "単矢印"),
            ('CIRCLE',       "Circle",       "円"),
            ('CUBE',         "Cube",         "立方体"),
            ('SPHERE',       "Sphere",       "球"),
        ],
        default='PLAIN_AXES',
    )


# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────

def calc_midpoint(objects):
    """バウンディングボックスのワールド中心を返す（編集モード相当）"""
    if not objects:
        return Vector((0, 0, 0))
    INF = float('inf')
    mn = Vector(( INF,  INF,  INF))
    mx = Vector((-INF, -INF, -INF))
    for obj in objects:
        for corner in obj.bound_box:
            wc = obj.matrix_world @ Vector(corner)
            mn.x = min(mn.x, wc.x); mx.x = max(mx.x, wc.x)
            mn.y = min(mn.y, wc.y); mx.y = max(mx.y, wc.y)
            mn.z = min(mn.z, wc.z); mx.z = max(mx.z, wc.z)
    return (mn + mx) / 2


def make_unique_name(base):
    if base not in bpy.data.objects:
        return base
    i = 1
    while f"{base}.{i:03d}" in bpy.data.objects:
        i += 1
    return f"{base}.{i:03d}"


def get_targets(context):
    return [
        obj for obj in context.selected_objects
        if obj.type in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'GPENCIL', 'ARMATURE'}
    ]


def digit_char(event):
    """キーイベントから数値文字（0-9 / .）を返す。対象外は None"""
    if event.value != 'PRESS':
        return None
    tbl = {
        'ZERO':'0','ONE':'1','TWO':'2','THREE':'3','FOUR':'4',
        'FIVE':'5','SIX':'6','SEVEN':'7','EIGHT':'8','NINE':'9',
        'NUMPAD_0':'0','NUMPAD_1':'1','NUMPAD_2':'2','NUMPAD_3':'3',
        'NUMPAD_4':'4','NUMPAD_5':'5','NUMPAD_6':'6','NUMPAD_7':'7',
        'NUMPAD_8':'8','NUMPAD_9':'9',
        'PERIOD':'.','NUMPAD_PERIOD':'.',
    }
    return tbl.get(event.type)


# ─────────────────────────────────────────────
# モーダル：エンプティサイズ変更
# ─────────────────────────────────────────────

class OBJECT_OT_empty_group_resize_modal(bpy.types.Operator):
    """エンプティ表示サイズをインタラクティブに変更 (Ctrl+Shift+E)
    マウス左右移動で調整 / 数値を直接入力 / Enter確定 / Escキャンセル"""
    bl_idname  = "object.empty_group_resize_modal"
    bl_label   = "Empty 表示サイズ変更"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'EMPTY'

    def invoke(self, context, event):
        obj = context.active_object
        if obj is None or obj.type != 'EMPTY':
            return {'CANCELLED'}

        self._empty        = obj
        self._init_size    = obj.empty_display_size
        self._current_size = obj.empty_display_size
        self._init_x       = event.mouse_x
        self._input        = ""          # 数値直接入力バッファ

        self._refresh_header(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):

        # ── Backspace ─────────────────────────────────
        if event.type == 'BACK_SPACE' and event.value == 'PRESS':
            self._input = self._input[:-1]
            if self._input:
                self._apply_input()
            else:
                self._apply_mouse(event)    # 入力消去→マウスベースに戻す
            self._refresh_header(context)
            return {'RUNNING_MODAL'}

        # ── 数値キー ───────────────────────────────────
        ch = digit_char(event)
        if ch is not None:
            # '.' が既にあれば重複を防ぐ
            if ch == '.' and '.' in self._input:
                return {'RUNNING_MODAL'}
            self._input += ch
            self._apply_input()
            self._refresh_header(context)
            return {'RUNNING_MODAL'}

        # ── マウス移動 ─────────────────────────────────
        if event.type == 'MOUSEMOVE':
            if not self._input:
                self._apply_mouse(event)
                self._refresh_header(context)

        # ── 確定（Enter / LMB）────────────────────────
        elif event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if self._input:
                self._apply_input(clamp=True)
            context.area.header_text_set(None)
            return {'FINISHED'}

        # ── キャンセル（Esc / RMB）────────────────────
        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._empty.empty_display_size = self._init_size
            context.area.header_text_set(None)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    # ── 内部ヘルパー ───────────────────────────────────

    def _apply_mouse(self, event):
        """マウスの横移動量から新しいサイズを計算・適用する"""
        delta = event.mouse_x - self._init_x
        # 150px で初期サイズの 2 倍になる感度
        factor = max(0.0001 / max(self._init_size, 1e-6), 1.0 + delta / 150.0)
        self._current_size = max(0.001, self._init_size * factor)
        self._empty.empty_display_size = self._current_size

    def _apply_input(self, clamp=False):
        """数値入力バッファの値を適用する"""
        try:
            v = float(self._input)
            if v > 0:
                self._current_size = v
                self._empty.empty_display_size = v
        except ValueError:
            pass

    def _refresh_header(self, context):
        size = self._empty.empty_display_size
        if self._input:
            msg = (f"表示サイズ: {self._input}█"
                   f"  |  Enter / LMB: 確定   Esc / RMB: キャンセル")
        else:
            msg = (f"表示サイズ: {size:.4f}"
                   f"  |  マウス左右で調整 / 数値直接入力可"
                   f"  |  Enter・LMB: 確定   Esc・RMB: キャンセル（元に戻す）")
        context.area.header_text_set(msg)


# ─────────────────────────────────────────────
# メインオペレータ：グループ化
# ─────────────────────────────────────────────

class OBJECT_OT_empty_group(bpy.types.Operator):
    """選択オブジェクトをエンプティでグループ化 (Ctrl+Shift+G)"""
    bl_idname = "object.empty_group"
    bl_label  = "Empty Group"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty(
        name="グループ名", default="Group", maxlen=63,
    )
    display_size: FloatProperty(
        name="表示サイズ", default=1.0, min=0.001, soft_max=20.0, step=10, precision=3,
    )
    empty_type: EnumProperty(
        name="エンプティの種類",
        items=[
            ('PLAIN_AXES',   "Plain Axes",   "十字軸"),
            ('ARROWS',       "Arrows",       "矢印"),
            ('SINGLE_ARROW', "Single Arrow", "単矢印"),
            ('CIRCLE',       "Circle",       "円"),
            ('CUBE',         "Cube",         "立方体"),
            ('SPHERE',       "Sphere",       "球"),
        ],
        default='PLAIN_AXES',
    )
    parent_objects: BoolProperty(
        name="ペアレント化", default=True,
    )
    keep_transform: BoolProperty(
        name="トランスフォームを維持", default=True,
    )

    def invoke(self, context, event):
        if not get_targets(context):
            self.report({'WARNING'}, "メッシュオブジェクトが選択されていません")
            return {'CANCELLED'}
        s = context.scene.empty_group_settings
        self.display_size = s.default_size
        self.empty_type   = s.default_empty_type
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.label(text=f"選択オブジェクト数: {len(get_targets(context))}", icon='OBJECT_DATA')
        layout.separator(factor=0.5)

        col = layout.column(align=True)
        col.prop(self, "group_name")
        col.prop(self, "empty_type")
        col.prop(self, "display_size")
        layout.separator(factor=0.5)

        col = layout.column(align=True)
        col.prop(self, "parent_objects")
        sub = col.column()
        sub.enabled = self.parent_objects
        sub.prop(self, "keep_transform")

        layout.separator(factor=0.5)
        layout.label(
            text="OK 後、サイズ変更モードに入ります",
            icon='INFO',
        )

    def execute(self, context):
        targets = get_targets(context)
        if not targets:
            self.report({'WARNING'}, "メッシュオブジェクトが選択されていません")
            return {'CANCELLED'}

        col_obj   = context.collection
        mid       = calc_midpoint(targets)
        uname     = make_unique_name(self.group_name)

        # ── エンプティ作成 ─────────────────────────────
        empty = bpy.data.objects.new(uname, None)
        empty.empty_display_type = self.empty_type
        empty.empty_display_size = self.display_size
        empty.location           = mid
        col_obj.objects.link(empty)

        context.view_layer.update()   # matrix_world を確定

        # ── ペアレント化 ───────────────────────────────
        if self.parent_objects:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in targets:
                obj.select_set(True)
            context.view_layer.objects.active = empty
            bpy.ops.object.parent_set(
                type='OBJECT',
                keep_transform=self.keep_transform,
            )

        # ── エンプティを選択・アクティブに ─────────────
        bpy.ops.object.select_all(action='DESELECT')
        empty.select_set(True)
        context.view_layer.objects.active = empty

        self.report({'INFO'}, f"グループ '{uname}' を作成しました（{len(targets)} オブジェクト）")

        # ── サイズ変更モーダルを即時起動 ───────────────
        bpy.ops.object.empty_group_resize_modal('INVOKE_DEFAULT')

        return {'FINISHED'}


# ─────────────────────────────────────────────
# グループ解除オペレータ
# ─────────────────────────────────────────────

class OBJECT_OT_empty_group_unlink(bpy.types.Operator):
    """選択エンプティのグループを解除し、子を独立させる"""
    bl_idname  = "object.empty_group_unlink"
    bl_label   = "Empty Group を解除"
    bl_options = {'REGISTER', 'UNDO'}

    remove_empty: BoolProperty(
        name="エンプティを削除",
        description="解除後にエンプティ自体を削除します",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'EMPTY' and len(obj.children) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        layout.label(text=f"エンプティ: {obj.name}",    icon='EMPTY_AXIS')
        layout.label(text=f"子オブジェクト数: {len(obj.children)}")
        layout.separator(factor=0.5)
        layout.prop(self, "remove_empty")

    def execute(self, context):
        empty    = context.active_object
        children = list(empty.children)

        bpy.ops.object.select_all(action='DESELECT')
        for child in children:
            child.select_set(True)
        context.view_layer.objects.active = children[0]
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

        if self.remove_empty:
            bpy.data.objects.remove(empty, do_unlink=True)

        self.report({'INFO'}, f"{len(children)} オブジェクトのグループ化を解除しました")
        return {'FINISHED'}


# ─────────────────────────────────────────────
# 名前変更オペレータ
# ─────────────────────────────────────────────

class OBJECT_OT_empty_group_rename(bpy.types.Operator):
    """選択エンプティの名前を変更する"""
    bl_idname  = "object.empty_group_rename"
    bl_label   = "Empty Group 名前変更"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(name="新しい名前", default="", maxlen=63)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'EMPTY'

    def invoke(self, context, event):
        self.new_name = context.active_object.name
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "new_name")

    def execute(self, context):
        obj    = context.active_object
        unique = make_unique_name(self.new_name) if self.new_name != obj.name else self.new_name
        obj.name = unique
        self.report({'INFO'}, f"名前を '{unique}' に変更しました")
        return {'FINISHED'}


# ─────────────────────────────────────────────
# サイドバーパネル
# ─────────────────────────────────────────────

class VIEW3D_PT_empty_group(bpy.types.Panel):
    bl_label      = "Empty Group"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category   = "Empty Group"

    def draw(self, context):
        layout   = self.layout
        settings = context.scene.empty_group_settings
        active   = context.active_object

        # ── デフォルト設定 ─────────────────────────────
        box = layout.box()
        box.label(text="デフォルト設定", icon='SETTINGS')
        col = box.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(settings, "default_size")
        col.prop(settings, "default_empty_type")

        layout.separator()

        # ── グループ化ボタン ───────────────────────────
        targets = get_targets(context)
        row = layout.row()
        row.scale_y = 1.4
        sub = row.row()
        sub.enabled = len(targets) > 0
        sub.operator(
            OBJECT_OT_empty_group.bl_idname,
            text=f"グループ化  ({len(targets)} 個選択中)",
            icon='EMPTY_AXIS',
        )

        layout.separator()

        # ── 選択エンプティの操作 ───────────────────────
        if active and active.type == 'EMPTY':
            box = layout.box()
            box.label(text=f"  {active.name}", icon='EMPTY_AXIS')

            col = box.column(align=True)
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(active, "empty_display_size", text="表示サイズ")
            col.prop(active, "empty_display_type", text="種類")

            col = box.column(align=True)
            col.operator(
                OBJECT_OT_empty_group_resize_modal.bl_idname,
                text="インタラクティブにサイズ変更  (Ctrl+Shift+E)",
                icon='FULLSCREEN_ENTER',
            )
            col.operator(
                OBJECT_OT_empty_group_rename.bl_idname,
                text="名前変更  (Ctrl+Shift+R)",
                icon='FONT_DATA',
            )
            if active.children:
                col.separator()
                col.operator(
                    OBJECT_OT_empty_group_unlink.bl_idname,
                    text="グループ解除  (Ctrl+Shift+U)",
                    icon='UNLINKED',
                )
        else:
            layout.label(text="エンプティを選択すると操作できます", icon='INFO')


# ─────────────────────────────────────────────
# Object メニュー
# ─────────────────────────────────────────────

def menu_func(self, context):
    self.layout.separator()
    self.layout.operator(
        OBJECT_OT_empty_group.bl_idname,
        text="Empty Group でグループ化",
        icon='EMPTY_AXIS',
    )
    active = context.active_object
    if active and active.type == 'EMPTY':
        self.layout.operator(
            OBJECT_OT_empty_group_resize_modal.bl_idname,
            text="Empty Group サイズ変更",
            icon='FULLSCREEN_ENTER',
        )
        self.layout.operator(
            OBJECT_OT_empty_group_rename.bl_idname,
            text="Empty Group 名前変更",
            icon='FONT_DATA',
        )
        if active.children:
            self.layout.operator(
                OBJECT_OT_empty_group_unlink.bl_idname,
                text="Empty Group を解除",
                icon='UNLINKED',
            )


# ─────────────────────────────────────────────
# キーマップ
# ─────────────────────────────────────────────

addon_keymaps = []

def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.new(name='Object Mode', space_type='EMPTY')

    for idname, key in [
        (OBJECT_OT_empty_group.bl_idname,              'G'),  # Ctrl+Shift+G
        (OBJECT_OT_empty_group_resize_modal.bl_idname, 'E'),  # Ctrl+Shift+E
        (OBJECT_OT_empty_group_rename.bl_idname,       'R'),  # Ctrl+Shift+R
        (OBJECT_OT_empty_group_unlink.bl_idname,       'U'),  # Ctrl+Shift+U
    ]:
        kmi = km.keymap_items.new(
            idname, type=key, value='PRESS', ctrl=True, shift=True,
        )
        addon_keymaps.append((km, kmi))

def unregister_keymaps():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


# ─────────────────────────────────────────────
# 登録 / 解除
# ─────────────────────────────────────────────

CLASSES = [
    EmptyGroupSettings,
    OBJECT_OT_empty_group_resize_modal,
    OBJECT_OT_empty_group,
    OBJECT_OT_empty_group_rename,
    OBJECT_OT_empty_group_unlink,
    VIEW3D_PT_empty_group,
]

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.empty_group_settings = PointerProperty(type=EmptyGroupSettings)
    bpy.types.VIEW3D_MT_object.append(menu_func)
    register_keymaps()

def unregister():
    unregister_keymaps()
    bpy.types.VIEW3D_MT_object.remove(menu_func)
    del bpy.types.Scene.empty_group_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
