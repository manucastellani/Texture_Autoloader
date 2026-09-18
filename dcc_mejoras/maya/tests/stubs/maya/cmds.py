"""
Minimal maya.cmds stub for running the Maya front-end's tests without
Maya installed. Simulates only what's needed: shape/shading-engine/
assigned-material lookups (for _get_assigned_material_name and the
match_objects_to_textures wrapper), and records scene-writing calls
(nodes created, connections, attributes set) so the render engine
templates can be checked without the renderers installed.
"""

_shape_connections = {}
_sg_surface_shader = {}

# Recorded scene writes.
_created = {}          # node name -> node type
_connections = []      # (source plug, destination plug)
_set_attrs = {}        # plug -> value (or tuple of values)

# Knobs for tests.
_missing_attrs = set()  # (node type, attr) pairs attributeQuery reports as missing
_loaded_plugins = None  # None = every plugin counts as loaded


def reset():
    global _loaded_plugins
    _shape_connections.clear()
    _sg_surface_shader.clear()
    _created.clear()
    del _connections[:]
    _set_attrs.clear()
    _missing_attrs.clear()
    _loaded_plugins = None


def warning(msg):
    print(f"[maya.cmds stub] WARNING: {msg}")


def ls(selection=False, sl=False, **kwargs):
    return []


def listRelatives(obj, shapes=False, fullPath=False, **kwargs):
    return _shape_connections.get(obj, {}).get("shapes", [obj + "Shape"])


def nodeType(node):
    if node in _created:
        return _created[node]
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


def shadingNode(node_type, asUtility=False, asTexture=False, asShader=False, name=None, **kwargs):
    node = name or (node_type + "1")
    _created[node] = node_type
    return node


def setAttr(plug, *values, **kwargs):
    _set_attrs[plug] = values[0] if len(values) == 1 else values


def connectAttr(source, destination, force=False, **kwargs):
    _connections.append((source, destination))


def disconnectAttr(source, destination, **kwargs):
    if (source, destination) in _connections:
        _connections.remove((source, destination))


def attributeQuery(attr, node=None, exists=False, **kwargs):
    return (_created.get(node, node), attr) not in _missing_attrs


def pluginInfo(plugin, query=False, loaded=False, **kwargs):
    return _loaded_plugins is None or plugin in _loaded_plugins


def loadPlugin(plugin, quiet=False, **kwargs):
    if _loaded_plugins is not None:
        _loaded_plugins.add(plugin)


def sets(*args, **kwargs):
    return kwargs.get("name", "set1")


def objExists(node):
    return False


def delete(node):
    _created.pop(node, None)


def listHistory(node, pruneDagObjects=False):
    return []


def fileDialog2(**kwargs):
    return None


def internalVar(userAppDir=False):
    return "/tmp/mayauserdir/"


def undoInfo(openChunk=False, closeChunk=False):
    pass
