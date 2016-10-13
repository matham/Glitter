#!/usr/bin/env python

from distutils.core import setup
import glitter

setup(name='Glitter',
      version=str(glitter.__version__),
      description=glitter.__description__,
      author='Matthew Einhorn',
      author_email='me263@cornell.edu',
      url='https://cpl.cornell.edu/',
      license='LGPL3',
      packages=['glitter'])