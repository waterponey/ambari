/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import Ember from 'ember';
import { moduleFor, test } from 'ember-qunit';

moduleFor('controller:queries', 'QueriesController', {
  needs: [ 'controller:history' ]
});

test('controller is initialized', function() {
  expect(1);

  var component = this.subject();

  equal(component.get('columns.length'), 4, 'Columns are initialized correctly');
});

test('Should hide new queries', function() {
  expect(1);

  var queries = [
    { isNew: true },
    { isNew: false}
  ];

  var controller = this.subject({
    queries: queries
  });

  equal(controller.get('model.length'), 1, 'Hide new queries from the list');
});
