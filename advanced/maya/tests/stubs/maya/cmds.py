"""
Minimal maya.cmds stub for running the Maya front-end's tests without
Maya installed. Simulates only what's needed: shape/shading-engine/
assigned-material lookups (for _get_assigned_material_name and the
match_objects_to_textures wrapper), and records the scene-writing calls
(nodes created, connections made, attributes set, warnings) so the wiring
can be checked without a real Maya. The real network is also verified
inside Maya by tests/run_in_mayapy.py.
"""

_shape_connections = {}
_sg_surface_shader = {}

# Recorded scene writes.
created = {}        # node name -> node type
connections = []    # (source plug, destination plug)
set_attrs = {}      # plug -> value
warnings = []       # messages passed to cmds.warning

# Attributes attributeQuery should report as missing, as (node type, attr).
missing_attrs = set()


def reset():
    _shape_connections.clear()
    _sg_surface_shader.clear()
    created.clear()
    del connections[:]
    set_attrs.clear()
    del warnings[:]
    missing_attrs.clear()


def warning(msg):
    warnings.append(msg)
    print(f"[maya.cmds stub] WARNING: {msg}")


def attributeQuery(attr, node=None, exists=False, **kwargs):
    return (created.get(node, node), attr) not in missing_attrs


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


def shadingNode(node_type, asUtility=False, asTexture=False, asShader=False, name=None,
                **kwargs):
    node = name or (node_type + "1")
    created[node] = node_type
    return node


def setAttr(plug, *values, **kwargs):
    set_attrs[plug] = values[0] if len(values) == 1 else values


def connectAttr(source, destination, force=False, **kwargs):
    connections.append((source, destination))


def disconnectAttr(source, destination, **kwargs):
    if (source, destination) in connections:
        connections.remove((source, destination))


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
