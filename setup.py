#!/usr/bin/env python
# -*- coding: utf-8 -*-


import shlex
from subprocess import check_output

from setuptools import setup


GIT_HEAD_REV = check_output(shlex.split('git rev-parse --short HEAD')).strip()


with open('requirements.txt') as f:
    required = f.read().splitlines()

VERSION = '1.1.0'


setup(name='gateway-utils',
      version=VERSION,
      description='Utility Python scripts to help manage SNAP gateway bridge nodes',
      author='Synapse Wireless, Inc.',
      author_email='support@synapse-wireless.com',
      url='http://synapse-wireless.com',
      packages=['gateway_utils'],
      install_requires=required,
      entry_points={'console_scripts': ['spy_uploader = gateway_utils.spy_uploader:main',
                                        'flash_bridge = gateway_utils.FlashBridge:main']},
      options={'egg_info': {'tag_build': "dev_" + GIT_HEAD_REV}},
      )
