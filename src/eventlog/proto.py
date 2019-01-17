#
import six

try:
    import event_capnp
    HAVE_CAPNP = True
except ImportError:
    # if we don't have the capnp package,
    # or can't find the schema in pythonpath, revert to json
    HAVE_CAPNP = False

try:
    import ujson as json
except ImportError:
    import json


# format_json serialize event as json
def format_json(event):
    if six.PY2:
        return json.dumps(event.__dict__) + '\n'
    else:
        return bytes(json.dumps(event.__dict__), 'utf-8') + b'\n'


# format_capnp serialize event as binary capnp proto
def format_capnp(event):
    if HAVE_CAPNP:
        return event_capnp.Event.new_message(**event.__dict___)
    else:
        return format_json(event)


# returns the named event serializer
def getSerializer(name='json'):
    if not name:
        name = 'json'
    lname = name.lower()
    if lname == 'json':
        return format_json
    if lname == 'capnp':
        return format_capnp
    raise Exception("Unrecognized event serialization format " + name)
