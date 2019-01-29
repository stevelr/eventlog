# proto_msgpack.py

import msgpack
import six

MSG_HEADER_MAGIC = [ 3, 23 ]

# buffer length that can be expressed  in 2 bytes (65535)
# if we need to support longer messages,
# the schema version should be increased
MAX_MSG_LEN = 0xffff


def write_sval(buf, s):
    buf.write(msgpack.packb(s))
def write_ival(buf, iv):
    buf.write(msgpack.packb(int(iv)))
def write_fval(buf, fv):
    buf.write(msgpack.packb(float(sv)))
def write_bval(buf, bv):
    buf.write(msgpack.packb(bv))

# write nullable string
def write_nstr(buf, d, v):
    if v not in d or d[v] is None:
        write_bval(buf, False)
    else:
        write_bval(buf, True)
        write_sval(buf, d[v])

# write nullable int
def write_nint(buf, d, v):
    if v not in d or d[v] is None:
        write_bval(buf, False)
    else:
        write_bval(buf, True)
        write_ival(buf, d[v])

def pop_write_str(buf, d, v):
    val = d.pop(v, "")
    write_sval(buf, val)

def fieldType(v):
    if isinstance(v,six.string_types):
        return 0
    elif isinstance(v, six.integer_types):
        return 1
    elif isinstance(v, float):
        return 2
    else:
        raise ("Invalid field type")

def write_fields(buf, fields):
    write_ival(buf, len(fields))
    buf.write(msgpack.packb(fields))

# write dictionary in msgpack format
# changes to this should bump the schema version number
def format_msgpack(evDict):
    buf = BytesIO()
    d = evDict

    # first write schema version
    (vmajor,vminor) = d['version']
    write_ival(buf, vmajor)
    write_ival(buf, vminor)

    # non-nullable values
    write_ival(buf, d['tstamp'] * 1000)
    write_sval(buf, d['name'])   # not nullable
    write_fval(buf, d['value'])
    write_fval(buf, d['duration'])
    write_ival(buf, d['pid'])
    write_ival(buf, d['level'])

    # nullable
    write_nstr(buf, d, 'target')
    write_nstr(buf, d, 'host')
    write_nstr(buf, d, 'site')
    write_nstr(buf, d, 'cluster')
    write_nstr(buf, d, 'message')
    write_nstr(buf, d, 'reqId')
    write_nstr(buf, d, 'user')
    write_nstr(buf, d, 'session')
    write_nstr(buf, d, 'codeFile')
    write_nstr(buf, d, 'codeFunc')
    write_nint(buf, d, 'codeLine')

    fields = d.get('fields', {})

    # http extension. Special-casing this flattens fields into columns
    # for one of the most common event types, greatly simplifying
    # the final db, and decreasing size of http event msg by >100 bytes
    if d['name'] == 'http_request':
        write_bval(buf, True)
        write_ival(buf, fields.pop('status', 0))
        write_sval(buf, fields.pop('method', ''))
        write_sval(buf, fields.pop('path', ''))
        write_sval(buf, fields.pop('query', ''))
        write_sval(buf, fields.pop('remoteHost', ''))
        write_sval(buf, fields.pop('remoteAddr', ''))
        write_sval(buf, fields.pop('referer', ''))
        write_sval(buf, fields.pop('userAgent', ''))
        write_sval(buf, fields.pop('body', ''))
        write_sval(buf, fields.pop('forwardedProto', ''))
        write_sval(buf, fields.pop('forwardedFor', ''))
    else:
        write_bval(buf, False)

    # if there are any fields left, write the # fields
    # and then the values
    write_fields(buf, fields)

    msgdata = buf.getvalue()
    length = len(msgdata)
    if length > MAX_MSG_LEN:
        raise Exception("Packed event (len=%d) too large. Max %d bytes" %\
                        (length, MAX_MSG_LEN))

    ret = BytesIO()
    ret.write(bytes(MSG_HEADER_MAGIC))
    ret.write(bytes([length//256, length & 0xff]))
    ret.write(msgdata)
    return ret.getvalue()
