#!/usr/bin/env python

'''
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''
import ConfigParser
import os

import pprint

from unittest import TestCase
import threading
import tempfile
import time
from threading import Thread


import StringIO
import sys, logging, pprint
from ambari_agent import AgentException
from resource_management.libraries.script import Script
from resource_management.core.environment import Environment
from mock.mock import MagicMock, patch

class TestScript(TestCase):

  def setUp(self):
    # disable stdout
    out = StringIO.StringIO()
    sys.stdout = out



  @patch("resource_management.core.providers.package.PackageProvider")
  def test_install_packages(self, package_provider_mock):
    no_packages_config = {
      'hostLevelParams' : {
        'repo_info' : "[{\"baseUrl\":\"http://public-repo-1.hortonworks.com/HDP/centos6/2.x/updates/2.0.6.0\",\"osType\":\"centos6\",\"repoId\":\"HDP-2.0._\",\"repoName\":\"HDP\",\"defaultBaseUrl\":\"http://public-repo-1.hortonworks.com/HDP/centos6/2.x/updates/2.0.6.0\"}]"
      }
    }
    empty_config = {
      'hostLevelParams' : {
        'package_list' : '',
        'repo_info' : "[{\"baseUrl\":\"http://public-repo-1.hortonworks.com/HDP/centos6/2.x/updates/2.0.6.0\",\"osType\":\"centos6\",\"repoId\":\"HDP-2.0._\",\"repoName\":\"HDP\",\"defaultBaseUrl\":\"http://public-repo-1.hortonworks.com/HDP/centos6/2.x/updates/2.0.6.0\"}]"
      }
    }
    dummy_config = {
      'hostLevelParams' : {
        'package_list' : "[{\"type\":\"rpm\",\"name\":\"hbase\"},"
                         "{\"type\":\"rpm\",\"name\":\"yet-another-package\"}]",
        'repo_info' : "[{\"baseUrl\":\"http://public-repo-1.hortonworks.com/HDP/centos6/2.x/updates/2.0.6.0\",\"osType\":\"centos6\",\"repoId\":\"HDP-2.0._\",\"repoName\":\"HDP\",\"defaultBaseUrl\":\"http://public-repo-1.hortonworks.com/HDP/centos6/2.x/updates/2.0.6.0\"}]",
        'service_repo_info' : "[{\"mirrorsList\":\"abc\",\"osType\":\"centos6\",\"repoId\":\"HDP-2.0._\",\"repoName\":\"HDP\",\"defaultBaseUrl\":\"http://public-repo-1.hortonworks.com/HDP/centos6/2.x/updates/2.0.6.0\"}]"
      }
    }

    # Testing config without any keys
    with Environment(".", test_mode=True) as env:
      script = Script()
      Script.config = no_packages_config
      script.install_packages(env)
    resource_dump = pprint.pformat(env.resource_list)
    self.assertEquals(resource_dump, "[]")

    # Testing empty package list
    with Environment(".", test_mode=True) as env:
      script = Script()
      Script.config = empty_config
      script.install_packages(env)
    resource_dump = pprint.pformat(env.resource_list)
    self.assertEquals(resource_dump, "[]")

    # Testing installing of a list of packages
    with Environment(".", test_mode=True) as env:
      script = Script()
      Script.config = dummy_config
      script.install_packages("env")
    resource_dump = pprint.pformat(env.resource_list)
    self.assertEqual(resource_dump, '[u"Package[\'hbase\']", u"Package[\'yet-another-package\']"]')

  @patch("__builtin__.open")
  def test_structured_out(self, open_mock):
    script = Script()
    script.stroutfile = ''
    self.assertEqual(Script.structuredOut, {})

    script.put_structured_out({"1": "1"})
    self.assertEqual(Script.structuredOut, {"1": "1"})
    self.assertTrue(open_mock.called)

    script.put_structured_out({"2": "2"})
    self.assertEqual(open_mock.call_count, 2)
    self.assertEqual(Script.structuredOut, {"1": "1", "2": "2"})

    #Overriding
    script.put_structured_out({"1": "3"})
    self.assertEqual(open_mock.call_count, 3)
    self.assertEqual(Script.structuredOut, {"1": "3", "2": "2"})


  @patch.object(Script, 'get_stack_to_component')
  def test_set_version(self, get_stack_to_component_mock):
    good_config = {
      'hostLevelParams': {
        'stack_name': "HDP",
        'stack_version': "2.2"
      },
      'commandParams': {
        'version': "2.2.0.0-2041"
      }
    }
    get_stack_to_component_mock.return_value = {"HDP": "kafka-broker"}

    # Testing default workflow
    with Environment(".", test_mode=True) as env:
      script = Script()
      Script.config = good_config
      script.set_version()
    resource_dump = pprint.pformat(env.resource_list)
    self.assertEquals(resource_dump, '[u"Execute[\'/usr/bin/hdp-select set kafka-broker 2.2.0.0-2041\']"]')

    # Component does not provide mapping
    get_stack_to_component_mock.return_value = {}

    with Environment(".", test_mode=True) as env:
      script = Script()
      Script.config = good_config
      script.set_version()
    resource_dump = pprint.pformat(env.resource_list)
    self.assertEquals(resource_dump, '[]')

    # Component provided mapping, but configuration is not complete (testing fallback)
    get_stack_to_component_mock.return_value = {"HDP": "kafka-broker"}
    bad_config = {}

    with Environment(".", test_mode=True) as env:
      script = Script()
      Script.config = bad_config
      script.set_version()
    resource_dump = pprint.pformat(env.resource_list)
    self.assertEquals(resource_dump, '[]')


  def tearDown(self):
    # enable stdout
    sys.stdout = sys.__stdout__
