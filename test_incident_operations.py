import unittest
import json
import os
from incident_service import incident_service
from app import app

class TestIncidentOperations(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_operations_summary(self):
        response = self.app.get('/api/operations/summary')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('total_incidents', data)
        self.assertIn('unresolved_alerts', data)
        self.assertIn('priority_cases', data)
        self.assertIn('ongoing_investigations', data)
        self.assertIn('monitored_reserves', data)
        self.assertGreaterEqual(data['total_incidents'], 1)

    def test_get_incidents_list(self):
        response = self.app.get('/api/incidents')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('incidents', data)
        self.assertGreaterEqual(len(data['incidents']), 1)
        first = data['incidents'][0]
        self.assertIn('id', first)
        self.assertIn('title', first)
        self.assertIn('priority', first)
        self.assertIn('status', first)
        self.assertIn('affected_ha', first)

    def test_incident_filtering(self):
        # Filter by priority
        res_pri = self.app.get('/api/incidents?priority=Critical')
        self.assertEqual(res_pri.status_code, 200)
        data_pri = json.loads(res_pri.data)
        for inc in data_pri['incidents']:
            self.assertEqual(inc['priority'], 'Critical')

        # Filter by search
        res_search = self.app.get('/api/incidents?search=Western')
        self.assertEqual(res_search.status_code, 200)
        data_search = json.loads(res_search.data)
        self.assertGreaterEqual(len(data_search['incidents']), 1)
        self.assertTrue(any('Western' in inc['location_name'] or 'Western' in inc['title'] for inc in data_search['incidents']))

    def test_incident_status_transition_and_audit(self):
        incidents = incident_service.get_incidents()
        self.assertGreaterEqual(len(incidents), 1)
        target_id = incidents[0]['id']

        # Transition status to 'Assigned'
        res = self.app.post(f'/api/incidents/{target_id}/status',
                            data=json.dumps({'status': 'Assigned', 'note': 'Assigned for ground-truthing', 'user': 'Test DFO'}),
                            content_type='application/json')
        self.assertEqual(res.status_code, 200)
        updated = json.loads(res.data)
        self.assertEqual(updated['status'], 'Assigned')
        
        # Verify in activity log
        logs = updated['activity_log']
        self.assertTrue(any(l['action'] == 'Status Transition' and 'Assigned' in l['details'] for l in logs))

    def test_incident_officer_assignment(self):
        incidents = incident_service.get_incidents()
        target_id = incidents[0]['id']

        res = self.app.post(f'/api/incidents/{target_id}/assign',
                            data=json.dumps({'officer': 'Range Officer Kumar', 'range': 'Southern Sector', 'user': 'Admin'}),
                            content_type='application/json')
        self.assertEqual(res.status_code, 200)
        updated = json.loads(res.data)
        self.assertEqual(updated['assigned_officer'], 'Range Officer Kumar')
        self.assertEqual(updated['range_division'], 'Southern Sector')

    def test_incident_field_notes(self):
        incidents = incident_service.get_incidents()
        target_id = incidents[0]['id']

        res = self.app.post(f'/api/incidents/{target_id}/notes',
                            data=json.dumps({'author': 'Beat Guard S. Patel', 'text': 'Canopy loss verified; recent selective thinning observed.'}),
                            content_type='application/json')
        self.assertEqual(res.status_code, 200)
        updated = json.loads(res.data)
        notes = updated['field_notes']
        self.assertGreaterEqual(len(notes), 1)
        self.assertEqual(notes[-1]['author'], 'Beat Guard S. Patel')
        self.assertIn('selective thinning', notes[-1]['text'])

if __name__ == '__main__':
    unittest.main()
