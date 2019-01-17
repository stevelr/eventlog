import inspect
import os
import sys

_getUserContext = None


# initMiddleWare is called during initialization of event-middleware.
# avoids circular package dependencies with django-eventlog
# and also allows this to be used in contexts other than an http server
# where there might still be a concept of a user and session
# If _getUserContext isn't set, the event will not be populated automatically
# with these fields: reqid, user, session
def initMiddleware(getUserContext):
    if (inspect.isfunction(getUserContext)):
        global _getUserContext
        _getUserContext = getUserContext


# returns current django request object if available
# def getRequest():
#    return _getRequest and _getRequest() or None


# get configuration from environment variable
#  or, if in django, from django.settings
#  If defined in both, environment takes precedence
#  If defined in neither, a warning is printed and None is returned
def getConfigSetting(key):
    val = os.environ.get(key, None)
    if val is None and os.environ.get('DJANGO_SETTINGS_MODULE', None):
        try:
            from django.conf import settings
            val = getattr(settings, key, None)
        except ImportError:
            pass
    if val is None:
        sys.stderr.write("Warning: %s not defined\n" % key)
    return val
