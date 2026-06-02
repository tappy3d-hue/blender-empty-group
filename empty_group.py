"""
Empty Group Addon for Blender  v4.0.0
==============================
Ctrl+Shift+G:
  通常オブジェクト選択時 → グループ化ダイアログ
  エンプティ選択時      → エンプティオプションパネル（形状・サイズ・依存関係編集）

その他のショートカット（エンプティ選択時）:
  Ctrl+Shift+E  サイズ変更モード
  Ctrl+Shift+R  名前変更
  Ctrl+Shift+U  グループ解除
"""

bl_info = {
    "name": "Empty Group",
    "author": "Custom",
    "version": (4, 0, 0),
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
# シーンごとの設定
# ─────────────────────────────────────────────

class EmptyGroupSettings(bpy.types.PropertyGroup):
    default_size: FloatProperty(
        name="デフォルトサイズ", default=1.0,
        min=0.001, soft_max=20.0, step=10, precision=3,
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

_OBJ_ICONS = {
    'MESH':     'OUTLINER_OB_MESH',
    'CURVE':    'OUTLINER_OB_CURVE',
    'SURFACE':  'OUTLINER_OB_SURFACE',
    'META':     'OUTLINER_OB_META',
    'FONT':     'OUTLINER_OB_FONT',
    'ARMATURE': 'OUTLINER_OB_ARMATURE',
    'EMPTY':    'OUTLINER_OB_EMPTY',
    'CAMERA':   'OUTLINER_OB_CAMERA',
    'LIGHT':    'OUTLINER_OB_LIGHT',
    'GPENCIL':  'OUTLINER_OB_GREASEPENCIL',
}

def obj_icon(obj):
    return _OBJ_ICONS.get(obj.type, 'OBJECT_DATA')

def get_all_descendants(obj):
    """obj の子孫オブジェクトをすべてリストで返す"""
    result = []
    for child in obj.children:
        result.append(child)
        result.extend(get_all_descendants(child))
    return result

def calc_midpoint(objects):
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
        if obj.type in {'MESH','CURVE','SURFACE','META','FONT','GPENCIL','ARMATURE'}
    ]

def digit_char(event):
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

def _available_empties_items(self, context):
    active = context.active_object
    items = [
        (obj.name, obj.name, f"エンプティ: {obj.name}")
        for obj in sorted(bpy.data.objects, key=lambda o: o.name)
        if obj.type == 'EMPTY' and obj != active
    ]
    return items or [("__NONE__", "（利用可能なエンプティなし）", "")]


# ─────────────────────────────────────────────
# 共通 UI パーツ：階層セクション描画
# ─────────────────────────────────────────────

def draw_hierarchy_section(layout, empty, context):
    """親子関係の表示と編集 UI。ポップアップとサイドバーで共用する。"""

    # ── 親オブジェクト ─────────────────────────────
    parent_box = layout.box()
    header = parent_box.row(align=True)
    header.label(text="親オブジェクト", icon='DECORATE_LINKED')

    if empty.parent:
        row = parent_box.row(align=True)
        row.label(text=empty.parent.name, icon=obj_icon(empty.parent))
        op = row.operator(
            OBJECT_OT_eg_select_object.bl_idname,
            text="選択", icon='RESTRICT_SELECT_OFF',
        )
        op.object_name = empty.parent.name
    else:
        parent_box.label(text="なし（ルートオブジェクト）", icon='DOT')

    # ── 子オブジェクト ─────────────────────────────
    child_box = layout.box()
    h = child_box.row(align=True)
    h.label(
        text=f"子オブジェクト  （{len(empty.children)} 個）",
        icon='OUTLINER',
    )
    h.operator(
        OBJECT_OT_eg_add_selected.bl_idname,
        text="選択中を追加", icon='ADD',
    )

    if empty.children:
        _draw_children_recursive(child_box, empty, depth=0)
    else:
        col = child_box.column()
        col.label(text="子オブジェクトなし", icon='DOT')
        col.label(text="「選択中を追加」でオブジェクトを追加できます", icon='INFO')

    # ── 階層選択ボタン ─────────────────────────────
    sel_row = layout.row(align=True)
    sel_row.operator(
        OBJECT_OT_eg_select_hierarchy.bl_idname,
        text="エンプティ含む全選択", icon='OUTLINER',
    )
    sel_row.operator(
        OBJECT_OT_eg_select_children_only.bl_idname,
        text="子のみ選択", icon='OUTLINER_OB_MESH',
    )


def _draw_children_recursive(layout, parent_obj, depth):
    """子・孫を再帰的に描画する（最大 3 階層）"""
    MAX_DEPTH = 3
    for child in parent_obj.children:
        row = layout.row(align=True)

        # インデント
        for _ in range(depth):
            row.separator(factor=2.0)

        # 階層アイコン
        row.label(
            text=("└─ " if depth > 0 else "• ") + child.name,
            icon=obj_icon(child),
        )

        # 選択ボタン
        op = row.operator(OBJECT_OT_eg_select_object.bl_idname, text="", icon='RESTRICT_SELECT_OFF')
        op.object_name = child.name

        # グループ移動ボタン（エンプティ以外）
        if child.type != 'EMPTY':
            op = row.operator(OBJECT_OT_eg_move_child.bl_idname, text="", icon='ARROW_LEFTRIGHT')
            op.child_name = child.name

        # 削除ボタン
        op = row.operator(OBJECT_OT_eg_remove_child.bl_idname, text="", icon='X')
        op.child_name = child.name

        # 孫を再帰表示
        if child.children and depth < MAX_DEPTH:
            _draw_children_recursive(layout, child, depth + 1)
        elif child.children and depth >= MAX_DEPTH:
            row2 = layout.row()
            for _ in range(depth + 1):
                row2.separator(factor=2.0)
            row2.label(text=f"  … さらに {len(child.children)} 個", icon='DOT')


# ─────────────────────────────────────────────
# モーダル：エンプティサイズ変更
# ─────────────────────────────────────────────

class OBJECT_OT_empty_group_resize_modal(bpy.types.Operator):
    """エンプティ表示サイズをインタラクティブに変更 (Ctrl+Shift+E)"""
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
        self._empty     = obj
        self._init_size = obj.empty_display_size
        self._init_x    = event.mouse_x
        self._input     = ""
        self._refresh_header(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'BACK_SPACE' and event.value == 'PRESS':
            self._input = self._input[:-1]
            self._apply_input() if self._input else self._apply_mouse(event)
            self._refresh_header(context)
            return {'RUNNING_MODAL'}
        ch = digit_char(event)
        if ch is not None:
            if ch == '.' and '.' in self._input:
                return {'RUNNING_MODAL'}
            self._input += ch
            self._apply_input()
            self._refresh_header(context)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            if not self._input:
                self._apply_mouse(event)
                self._refresh_header(context)
        elif event.type in {'LEFTMOUSE','RET','NUMPAD_ENTER'} and event.value == 'PRESS':
            if self._input:
                self._apply_input(clamp=True)
            context.area.header_text_set(None)
            return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE','ESC'} and event.value == 'PRESS':
            self._empty.empty_display_size = self._init_size
            context.area.header_text_set(None)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _apply_mouse(self, event):
        delta  = event.mouse_x - self._init_x
        factor = max(0.0001 / max(self._init_size, 1e-6), 1.0 + delta / 150.0)
        self._empty.empty_display_size = max(0.001, self._init_size * factor)

    def _apply_input(self, clamp=False):
        try:
            v = float(self._input)
            if v > 0:
                self._empty.empty_display_size = v
        except ValueError:
            pass

    def _refresh_header(self, context):
        size = self._empty.empty_display_size
        if self._input:
            msg = f"表示サイズ: {self._input}█  |  Enter・LMB: 確定   Esc・RMB: キャンセル"
        else:
            msg = (f"表示サイズ: {size:.4f}"
                   f"  |  マウス左右で調整 / 数値直接入力"
                   f"  |  Enter・LMB: 確定   Esc・RMB: キャンセル（元に戻す）")
        context.area.header_text_set(msg)


# ─────────────────────────────────────────────
# エンプティオプション ポップアップ
# ─────────────────────────────────────────────

class OBJECT_OT_empty_group_popup(bpy.types.Operator):
    """エンプティのオプション・依存関係パネルを表示 (Ctrl+Shift+G / エンプティ選択時)"""
    bl_idname  = "object.empty_group_popup"
    bl_label   = "Empty Group オプション"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'EMPTY'

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=380)

    def draw(self, context):
        layout = self.layout
        empty  = context.active_object
        if empty is None or empty.type != 'EMPTY':
            layout.label(text="エンプティを選択してください", icon='ERROR')
            return

        # ── ヘッダー：名前 + 名前変更ボタン ────────────
        header = layout.row(align=True)
        header.label(text=empty.name, icon='EMPTY_AXIS')
        header.operator(
            OBJECT_OT_empty_group_rename.bl_idname,
            text="名前変更", icon='FONT_DATA',
        )

        layout.separator(factor=0.8)

        # ── 表示設定 ───────────────────────────────────
        disp_box = layout.box()
        disp_box.label(text="表示設定", icon='SETTINGS')
        col = disp_box.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(empty, "empty_display_type", text="形状")
        col.prop(empty, "empty_display_size", text="サイズ")
        disp_box.operator(
            OBJECT_OT_empty_group_resize_modal.bl_idname,
            text="インタラクティブにサイズ変更  (Ctrl+Shift+E)",
            icon='FULLSCREEN_ENTER',
        )

        layout.separator(factor=0.8)

        # ── 階層 / 依存関係 ────────────────────────────
        layout.label(text="階層 / 依存関係", icon='OUTLINER')
        draw_hierarchy_section(layout, empty, context)

        layout.separator(factor=0.8)

        # ── グループ解除 ───────────────────────────────
        if empty.children:
            layout.operator(
                OBJECT_OT_empty_group_unlink.bl_idname,
                text="グループ解除", icon='UNLINKED',
            )

    def execute(self, context):
        return {'FINISHED'}


# ─────────────────────────────────────────────
# 子の追加 / 削除 / 移動
# ─────────────────────────────────────────────

class OBJECT_OT_eg_add_selected(bpy.types.Operator):
    """選択中のオブジェクトをアクティブなエンプティのグループに追加する"""
    bl_idname  = "object.eg_add_selected"
    bl_label   = "選択中をグループに追加"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'EMPTY'

    def execute(self, context):
        empty   = context.active_object
        targets = [o for o in context.selected_objects if o != empty]
        if not targets:
            self.report({'WARNING'}, "追加するオブジェクトが選択されていません（エンプティをアクティブにして他を選択）")
            return {'CANCELLED'}
        bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
        self.report({'INFO'}, f"{len(targets)} 個をグループ '{empty.name}' に追加しました")
        return {'FINISHED'}


class OBJECT_OT_eg_remove_child(bpy.types.Operator):
    """指定した子オブジェクトをグループから外す（ペアレント解除）"""
    bl_idname  = "object.eg_remove_child"
    bl_label   = "グループから外す"
    bl_options = {'REGISTER', 'UNDO'}

    child_name: StringProperty(name="子オブジェクト名")

    def execute(self, context):
        child = bpy.data.objects.get(self.child_name)
        if not child:
            self.report({'WARNING'}, f"'{self.child_name}' が見つかりません")
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        child.select_set(True)
        context.view_layer.objects.active = child
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        # アクティブをエンプティに戻す（ポップアップ表示のため）
        for obj in context.scene.objects:
            if obj.type == 'EMPTY' and self.child_name in [c.name for c in obj.children]:
                # 見つからないので元のアクティブに戻すだけ
                break
        self.report({'INFO'}, f"'{self.child_name}' をグループから外しました")
        return {'FINISHED'}


class OBJECT_OT_eg_move_child(bpy.types.Operator):
    """子オブジェクトを別のエンプティグループに移動する"""
    bl_idname  = "object.eg_move_child"
    bl_label   = "別グループに移動"
    bl_options = {'REGISTER', 'UNDO'}

    child_name:   StringProperty(name="子オブジェクト名")
    target_empty: EnumProperty(name="移動先グループ", items=_available_empties_items)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.label(text=f"移動: {self.child_name}", icon='OBJECT_DATA')
        layout.separator(factor=0.5)
        layout.prop(self, "target_empty")

    def execute(self, context):
        if self.target_empty == "__NONE__":
            self.report({'WARNING'}, "移動先のエンプティがありません")
            return {'CANCELLED'}
        child  = bpy.data.objects.get(self.child_name)
        target = bpy.data.objects.get(self.target_empty)
        if not child or not target:
            self.report({'WARNING'}, "オブジェクトが見つかりません")
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        child.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
        self.report({'INFO'}, f"'{self.child_name}' を '{self.target_empty}' に移動しました")
        return {'FINISHED'}


# ─────────────────────────────────────────────
# 階層選択
# ─────────────────────────────────────────────

class OBJECT_OT_eg_select_object(bpy.types.Operator):
    """指定したオブジェクトを選択・アクティブにする"""
    bl_idname  = "object.eg_select_object"
    bl_label   = "オブジェクトを選択"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.object_name)
        if not obj:
            self.report({'WARNING'}, f"'{self.object_name}' が見つかりません")
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class OBJECT_OT_eg_select_hierarchy(bpy.types.Operator):
    """アクティブなエンプティとその全子孫を選択する"""
    bl_idname  = "object.eg_select_hierarchy"
    bl_label   = "エンプティ含む全選択"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'EMPTY'

    def execute(self, context):
        empty = context.active_object
        targets = [empty] + get_all_descendants(empty)
        bpy.ops.object.select_all(action='DESELECT')
        for obj in targets:
            obj.select_set(True)
        context.view_layer.objects.active = empty
        self.report({'INFO'}, f"{len(targets)} 個を選択しました（エンプティ含む）")
        return {'FINISHED'}


class OBJECT_OT_eg_select_children_only(bpy.types.Operator):
    """アクティブなエンプティの子孫のみを選択する（エンプティは選択しない）"""
    bl_idname  = "object.eg_select_children_only"
    bl_label   = "子のみ選択"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'EMPTY' and len(obj.children) > 0

    def execute(self, context):
        empty    = context.active_object
        children = get_all_descendants(empty)
        if not children:
            self.report({'WARNING'}, "子オブジェクトがありません")
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        for obj in children:
            obj.select_set(True)
        # アクティブはエンプティのまま維持
        context.view_layer.objects.active = empty
        self.report({'INFO'}, f"{len(children)} 個の子オブジェクトを選択しました")
        return {'FINISHED'}


# ─────────────────────────────────────────────
# グループ化（メイン）
# ─────────────────────────────────────────────

class OBJECT_OT_empty_group(bpy.types.Operator):
    """グループ化 / エンプティ選択時はオプションパネルを開く (Ctrl+Shift+G)"""
    bl_idname  = "object.empty_group"
    bl_label   = "Empty Group"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty(name="グループ名", default="Group", maxlen=63)
    display_size: FloatProperty(name="表示サイズ", default=1.0, min=0.001, soft_max=20.0, step=10, precision=3)
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
    parent_objects: BoolProperty(name="ペアレント化", default=True)
    keep_transform: BoolProperty(name="トランスフォームを維持", default=True)

    def invoke(self, context, event):
        active = context.active_object
        # ─ エンプティ選択時 → ポップアップパネルへ分岐 ──
        if active and active.type == 'EMPTY':
            return bpy.ops.object.empty_group_popup('INVOKE_DEFAULT')

        # ─ 通常のグループ化 ───────────────────────────
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
        layout.label(text="OK 後、サイズ変更モードに入ります", icon='INFO')

    def execute(self, context):
        targets = get_targets(context)
        if not targets:
            self.report({'WARNING'}, "メッシュオブジェクトが選択されていません")
            return {'CANCELLED'}

        col_obj = context.collection
        mid     = calc_midpoint(targets)
        uname   = make_unique_name(self.group_name)

        empty = bpy.data.objects.new(uname, None)
        empty.empty_display_type = self.empty_type
        empty.empty_display_size = self.display_size
        empty.location           = mid
        col_obj.objects.link(empty)
        context.view_layer.update()

        if self.parent_objects:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in targets:
                obj.select_set(True)
            context.view_layer.objects.active = empty
            bpy.ops.object.parent_set(type='OBJECT', keep_transform=self.keep_transform)

        bpy.ops.object.select_all(action='DESELECT')
        empty.select_set(True)
        context.view_layer.objects.active = empty

        self.report({'INFO'}, f"グループ '{uname}' を作成しました（{len(targets)} オブジェクト）")
        bpy.ops.object.empty_group_resize_modal('INVOKE_DEFAULT')
        return {'FINISHED'}


# ─────────────────────────────────────────────
# グループ解除
# ─────────────────────────────────────────────

class OBJECT_OT_empty_group_unlink(bpy.types.Operator):
    """選択エンプティのグループを解除し、子を独立させる"""
    bl_idname  = "object.empty_group_unlink"
    bl_label   = "Empty Group を解除"
    bl_options = {'REGISTER', 'UNDO'}

    remove_empty: BoolProperty(name="エンプティを削除", default=True)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'EMPTY' and len(obj.children) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        obj = context.active_object
        self.layout.label(text=f"エンプティ: {obj.name}", icon='EMPTY_AXIS')
        self.layout.label(text=f"子オブジェクト数: {len(obj.children)}")
        self.layout.separator(factor=0.5)
        self.layout.prop(self, "remove_empty")

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
# 名前変更
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
        self.layout.use_property_split = True
        self.layout.prop(self, "new_name")

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
    bl_label       = "Empty Group"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Empty Group"

    def draw(self, context):
        layout  = self.layout
        settings = context.scene.empty_group_settings
        active  = context.active_object

        # ── デフォルト設定 ─────────────────────────────
        box = layout.box()
        box.label(text="デフォルト設定", icon='SETTINGS')
        col = box.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(settings, "default_size")
        col.prop(settings, "default_empty_type")

        layout.separator()

        # ── グループ化 ─────────────────────────────────
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

            # 表示設定
            disp_box = layout.box()
            name_row = disp_box.row(align=True)
            name_row.label(text=active.name, icon='EMPTY_AXIS')
            name_row.operator(OBJECT_OT_empty_group_rename.bl_idname, text="", icon='FONT_DATA')

            col = disp_box.column(align=True)
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(active, "empty_display_size", text="表示サイズ")
            col.prop(active, "empty_display_type", text="形状")
            disp_box.operator(
                OBJECT_OT_empty_group_resize_modal.bl_idname,
                text="インタラクティブにサイズ変更  (Ctrl+Shift+E)",
                icon='FULLSCREEN_ENTER',
            )

            layout.separator()

            # 階層 / 依存関係
            layout.label(text="階層 / 依存関係", icon='OUTLINER')
            draw_hierarchy_section(layout, active, context)

            layout.separator()

            # グループ解除
            if active.children:
                layout.operator(
                    OBJECT_OT_empty_group_unlink.bl_idname,
                    text="グループ解除  (Ctrl+Shift+U)",
                    icon='UNLINKED',
                )

            # オプションポップアップ
            layout.operator(
                OBJECT_OT_empty_group_popup.bl_idname,
                text="オプションパネルを開く",
                icon='WINDOW',
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
            OBJECT_OT_empty_group_popup.bl_idname,
            text="Empty Group オプション",
            icon='WINDOW',
        )
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
        self.layout.operator(
            OBJECT_OT_eg_select_hierarchy.bl_idname,
            text="Empty Group 階層全選択",
            icon='OUTLINER',
        )
        self.layout.operator(
            OBJECT_OT_eg_select_children_only.bl_idname,
            text="Empty Group 子のみ選択",
            icon='OUTLINER_OB_MESH',
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
        kmi = km.keymap_items.new(idname, type=key, value='PRESS', ctrl=True, shift=True)
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
    OBJECT_OT_empty_group_popup,
    OBJECT_OT_empty_group,
    OBJECT_OT_empty_group_unlink,
    OBJECT_OT_empty_group_rename,
    OBJECT_OT_eg_add_selected,
    OBJECT_OT_eg_remove_child,
    OBJECT_OT_eg_move_child,
    OBJECT_OT_eg_select_object,
    OBJECT_OT_eg_select_hierarchy,
    OBJECT_OT_eg_select_children_only,
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
