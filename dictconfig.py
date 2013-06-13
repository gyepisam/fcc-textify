#!/bin/env python

"""
configdict reads an ini configuration file into a dict

section and option names are joined with a '.' separator

[main]
encoding-type: huffman

is returned as:

  {'main.encoding-type': 'huffman'}

usage:

  import configdict

  # use config.ini in application directory
  config = configdict.parse()

  # be more explicit
  config = configdict.parsepath("..../config.ini")

"""

import io
from ConfigParser import ConfigParser
import os.path as path
import sys
import os

def parseconfig(source, kind):
  """Parse config from source, of type kind, and return dict"""
  config = ConfigParser()

  if kind == "path":
    config.read(source)
  elif kind == "string":
    config = config.readfp(io.BytesIO(source))

  data = {}

  for section in config.sections():
    for option in config.options(section):
      data["%s.%s" % (section, option)] = config.get(section, option)

  return data

def parse():
  """guesses the location of config.ini and parses it"""
  return parsepath(path.join(path.dirname(sys.argv[0]), 'config/%s.ini' % (os.getenv('RAILS_ENV', 'development'),)))

def parsepath(configpath):
  """parsepath parses the file located at configpath into a dict"""
  return parseconfig(configpath, 'path')

def parsestr(configstr):
  """parse parses a string into a dict"""
  return parseconfig(configstr, 'string')

if __name__ == "__main__":
  import sys
  print parsepath(sys.argv[1])
