#!/bin/bash


export EVENTLOG_HOST="172.17.0.1"
export EVENTLOG_PORT="5001"
export EVENTLOG_DB="/tmp/eventqueue.db"
export EVENTLOG_SITE="local"
export EVENTLOG_CLUSTER="local"

#echo Logging sample events to console
# the first one doesn't actually send to logstash
# just writes json events to stderr
#python consoletest.py

echo Sending sample events to logstash
# send events to logstash
python stash.py
