Asynchronous Event logging
==========================

Library for gathering events and logs and forwarding them to a
remote log server or log forwarder. Events are generated either by
construction of an Event object, or though the python logging handler
(which wraps log messages in an Event); then serialized with
a pluggable formatter (json, msgpack/fluent, capnproto);
then forwarded to a remote logging handler. The python-log-async library
performs bufering and forwarding to a TCP or UDP based log server.

To minimize the delay to the main application thread, events are added to
a local queue, and control is returned to the main thread immediately.
There are some provisions to improve reliability in the event of
server and network failures: graceful shutdown,
retries for dropped connections, internal queuing,
and prometheus monitoring; however, this library
does not provide Guaranteed Message Delivery. The strategy
for minimizing risk of message loss is to get the events and logs
off the production server as quickly as posisble and persisted
in an upstream reliable storage such as a Kafka cluster or Google PubSub.

This packages builds upon python-log-async,
a fork of logstash-async, which provides the local persistent queue (sqlite),
worker thread, and asynchronous sending to logstash.

This package includes the following capabilities:
* a standardized but flexible Event object schema designed
  to be interoperable with
  logstash, fluentd, and other logging protocols. The Event library
  also includes simple Counters and Gauges
* Configurable message serialization formats (json, msgpack (for fluentd),
  and capnp for Clickhouse) and configurable network protocols (logstash,
  fluentd, http post, and generic tcp/udp)
* A logging handler compatible with python logging,
  so application logs can be integrated with event logs
  (log messages are wrapped with an Event object)
* support for the django-eventlog middleware
  for logging http events and associating application Events
  with the current user session and http request
* If [CapnProto](https://capnproto.org/) is installed,
  events are converted to a compact binary format before transmitting.
  This reduces storage overhead and improves network bandwidth.


## Installation

Tested with python 2.7+ and 3.6+.
```
    pip install eventlog-<version>.tar.gz
```

Set the following environment variables. If you are using django, you can define these in site/settings.py
```
    # logstash server connection
    EVENTLOG_HOST = '172.17.0.1'
    EVENTLOG_PORT = 5001
    EVENTLOG_DB   = 'eventlog.db'

    # optional format: 'json', 'capnp'
    # if not specified, json is used
    EVENTLOG_FORMAT = 'json'

    # optional hostname identification for logging
    EVENTLOG_SITE = 'local'
    EVENTLOG_CLUSTER = 'local'
```

## Usage

This library may be used as a traditional logging handler.
When used in this way, log() messages are converted to Event objects and sent asynchronously
to a remote log forwarder (e.g., logstash, fluentd, or google pubsub)

```
    from eventlog import asyncEventLogger
    import logging

    logger = logging.getLogger('my-app')
    logger.addHandler(asyncEventLogger)

    logger.info("some message")
```

or by creating an event object:

```
    from eventlog import Event, logEvent
    event = Event('click', 'my-button', 'ui')
    logEvent(event)
```

## Event Fields

### Mandatory fields

**name**
    :  The event name - any string. A typical format might be
        <module><action><target> such as "app_open_document"
        This is likely to be a primary key in the event database so
        it should be meaningful for analytics purposes.

        A note on name design: it is usually
        preferable to keep dimensions in separate
        fields or tags (see below), rather than parts of the name string,
        so that you don't end up querying the database for name by
        substring or regex patterns.


### Optional fields

**message**
    : a string message or comment about the message. For http posts with the django-eventlog
middleware, the 'message' field is used to store the POST body. For pythong logging messages (where asyncEventLogger is used as a log handler), the message field contains the log message.

**tags**
    : an array of strings. You can add any number of strings associated with the event.
If you want to store numeric values such as counters and gauges, use the 'metrics' field.

f**fields**
    : a list of tuples (key,value). Keys are converted to string. Values can be integer, float, or string (and are stored in type-specific columns for efficient searching and aggregation operations). For http posts, several fields are automatically added to store query parameters,
important http header values (user agent, remote-address, etc.), the response status code, and the duration of the call (server processing time).

### Automatically-generated fields
The following fields are automatically added to each event. If required, they can be overridden by application code before the event is logged.

**tstamp**
    : current timestamp in milliseconds (always UTC)

**session**
    : current session (set by http middleware)

**user**
    : the current user (set by http middleware)

**site**, **cluster**
    :   the site (organization) name, and cluster. These are configured with the environment variables EVENTLOG_SITE and EVENTLOG_CLUSTER

**host**
    : the host that created the event (usually the hostname)

**codeFile**, **codeLine**, **codeFunc**
    : if the logCode parameter of the event constructor is True, these fields are added to record the file name, line number, and function name where the event object was created.

### Selecting good Action names for efficient queries and analysis
A well-designed ontology of action names can be very powerful for analysis and reporting. If the action term is a dotted path, going from general to specific, as in "account.admin.create", it is easy and efficient to aggregate events by different levels of this hierarchy. Since action is part of the primary key, events are sorted on disk by this key. Using the hierarchy, it would be possible to aggregate all account-related events by searching for action "account.*". All events related to administrative accounts would have action "account.admin.*".
Using the example 'account.admin.create', you could query all the account-related actions by searching keys 'account.*', and administrator account actions with 'accoutn.admin.*'.

The effictive primary key of the primary event table is (day, tgType, action, target, user). All metrics are grouped by the calendar day. Within each day, the events are sorted by the type of object, action, target, and user. Of course this is not the only way to query events, and a real-world analytics database likely contains many other tables and indexes, but good design of actions verbs can dramatically improve performance with the default setup.


## How logging parameters map to event fields
When asyncEventLogger (or any other instance of EventLogger) is used as a logging handler, log messages are translated to fields of the event object.
```
    log.info("my message")
    log.info("my message", tags=[ "thing-one", "thing-two" ],
           metrics={ "value":3.14159, choice="banana", "durationMs":34.2 })
```

| Field | Value |
| --- | --- |
| **message** | contains "my message".|
| **action** | is "log.info" |
| **codeFile** | name of source code file containing log call |
| **codeLine** | line number of log call |
| **codeFunc** | function name containing log call |
| **tags** | if the optional **tags=** parameter is provided (either a single string or array of strings, the strings are added to the event's *tags* property. |
| **metrics** | if the optional **extra=** parameter is provided (as a dictionary of key=value pairs), the keys and values are added to the event's metrics map|
| **exc_info** | If an exception was recorded with the log **exc_info=** parameter, a metric is added with key "exc_info" and value is a json-stringified object containining the exception type, value, and stack trace.
