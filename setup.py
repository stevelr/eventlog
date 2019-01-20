#!/usr/bin/env python
#
from os import path
from setuptools import setup

NAME = "eventlog"
VERSION = "0.9.101"  # keep in sync with src/eventlog/__init__.py
requires = []

try:
    from pypandoc import convert_text
    format_md = lambda f: convert_text(f, 'rst', format='md')
except (OSError, ImportError):
    print("warning: pypandoc module not found, could not convert Markdown to RST")
    format_md = lambda f: f


here = path.abspath(path.dirname(__file__))
with open(path.join(here, 'README.rst'), "rb") as fobj:
    long_description = format_md(fobj.read().decode('utf-8'))


setup(
    name=NAME,
    version=VERSION,
    description="Asynchronous event logging",
    long_description=long_description,
    author="",
    author_email="email@example.com",
    url="http://example.com",
    license="MIT",
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Database',
        'Topic :: Internet :: Log Analysis',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Logging',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 3',
    ],
    keywords="eventlog logging asynchronous analytics metrics logstash fluent pubsub",
    packages=["eventlog"],
    package_dir={"": "src"},
    requires=requires
)
