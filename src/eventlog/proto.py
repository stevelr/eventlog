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
def format_json(evDict):
    if six.PY2:
        return json.dumps(evDict) + '\n'
    else:
        # serialize to json string, then encode(utf8) to byte array
        return bytes(json.dumps(evDict, 'utf-8')) + b'\n'


# format_capnp serialize event as binary capnp proto
def format_capnp(evDict):
    if HAVE_CAPNP:
        return event_capnp.Event.new_message(**evDict)
    else:
        return format_json(evDict)


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


# Filter function that converts tstamp
# from time as seconds (floating point) to integer milliseconds
def formatTstampAsMillis(evDict):
    evDict['tstamp'] = int(evDict['tstamp'] * 1e3)
    return evDict


# Filter function that converts tstamp
# from time as seconds (floating point) to integer nanoseconds
def formatTstampAsNanos(evDict):
    evDict['tstamp'] = int(evDict['tstamp'] * 1e9)
    return evDict
