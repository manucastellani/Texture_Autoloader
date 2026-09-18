"""
Minimal maya.cmds stub for running the Maya front-end's tests without
Maya installed. Simulates only what's needed: shape/shading-engine/
assigned-material lookups (for _get_assigned_material_name and the
match_objects_to_textures wrapper) and scene-writing calls as safe
no-ops.
"""

_shape_connections = {}
_sg_surface_shader = {}


def reset():
    _shape_connections.clear()
    _sg_surface_shader.clear()


def warning(msg):
    print(f"[maya.cmds stub] WARNING: {msg}")


def ls(selection=False, sl=False, **kwargs):
    return []


def listRelatives(obj, shapes=False, fullPath=False, **kwargs):
    return _shape_connections.get(obj, {}).get("shapes", [obj + "Shape"])


def nodeType(node):
    return _shape_connections.get(node, {}).get("type", "mesh")


def listConnections(plug, type=None, **kwargs):
    if isinstance(plug, str) and "." in plug:
        node, attr = plug.split(".", 1)
    else:
        node, attr = plug, None

    if type == "shadingEngine":
        return _shape_connections.get(node, {}).get("shadingEngines", [])
    if attr == "surfaceShader":
        return [_sg_surface_shader[node]] if node in _sg_surface_shader else []
    return []


def shadingNode(node_type, asUtility=False, asTexture=False, asShader=False, name=None):
    return name or (node_type + "1")


def setAttr(*args, **kwargs):
    pass


def connectAttr(*args, **kwargs):
    pass


def disconnectAttr(*args, **kwargs):
    pass


def sets(*args, **kwargs):
    return kwargs.get("name", "set1")


def objExists(node):
    return False


def delete(node):
    pass


def listHistory(node, pruneDagObjects=False):
    return []


def fileDialog2(**kwargs):
    return None


def internalVar(userAppDir=False):
    return "/tmp/mayauserdir/"


def undoInfo(openChunk=False, closeChunk=False):
    pass
