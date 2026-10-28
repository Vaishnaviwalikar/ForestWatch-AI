import unittest
import json
import io
import os
from app import app
from notification_service import notification_service
from rbac import ROLE_ADMIN, ROLE_RANGE_OFFICER, ROLE_FIELD_OFFICER, ROLE_ANALYST

class TestPhase4Phase5Phase6(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    # =========================================================================
    # Phase 4: Notification Engine & Audit Trail Tests
    # =========================================================================

    def test_notification_test_mode_enabled(self):
        """Verify TEST_MODE is active by default to protect against accidental SMS/email dispatch"""
        self.assertTrue(notification_service.test_mode)

    def test_notification_templates_and_dispatch(self):
        """Verify notification templating and test-mode simulation dispatch"""
        test_incident = {
            "id": "INC-TEST-001",
            "location_name": "Periyar Tiger Reserve",
            "priority": "High",
            "affected_ha": 42.5,
            "assigned_officer": "Range Officer Kumar"
        }
        res = notification_service.dispatch("new_alert", test_incident, user="Surveillance Pipeline", force=True)
        self.assertGreaterEqual(len(res), 1)
        first = res[0]
        self.assertIn("notification_id", first)
        self.assertEqual(first["status"], "simulated" if first["channel"] in ["email", "sms"] else "delivered")
        self.assertTrue(first["test_mode"])
        self.assertIn("Periyar Tiger Reserve", first["subject"])

    def test_notification_deduplication(self):
        """Verify duplicate notifications within deduplication window are safely suppressed"""
        import uuid
        test_incident = {
            "id": f"INC-DEDUP-{uuid.uuid4().hex[:6]}",
            "location_name": "Silent Valley",
            "priority": "Critical",
            "affected_ha": 70.0
        }
        # First dispatch
        res1 = notification_service.dispatch("new_alert", test_incident, force=False)
        self.assertGreaterEqual(len(res1), 1)

        # Immediate second dispatch for identical incident and event type should be suppressed
        res2 = notification_service.dispatch("new_alert", test_incident, force=False)
        self.assertEqual(len(res2), 0)

    def test_api_notifications_endpoints(self):
        """Verify notification audit log API and test-mode trigger endpoint"""
        # GET audit log
        res = self.app.get('/api/notifications')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('notifications', data)
        self.assertTrue(data['test_mode'])

        # POST safe test notification (as Admin)
        res_test = self.app.post('/api/notifications/test',
                                 headers={'X-User-Role': ROLE_ADMIN},
                                 data=json.dumps({}),
                                 content_type='application/json')
        self.assertEqual(res_test.status_code, 200)
        data_test = json.loads(res_test.data)
        self.assertEqual(data_test['status'], 'success')
        self.assertTrue(data_test['test_mode'])

    # =========================================================================
    # Phase 6: Server-Side Role-Based Access Control (RBAC) Tests
    # =========================================================================

    def test_rbac_admin_allowed_to_assign(self):
        """Department Admin must be permitted to assign officers"""
        inc_res = self.app.get('/api/incidents')
        inc_id = json.loads(inc_res.data)['incidents'][0]['id']

        res = self.app.post(f'/api/incidents/{inc_id}/assign',
                            headers={'X-User-Role': ROLE_ADMIN},
                            data=json.dumps({'officer': 'Range Officer Kumar', 'range': 'North Beat'}),
                            content_type='application/json')
        self.assertEqual(res.status_code, 200)

    def test_rbac_field_officer_denied_assign(self):
        """Field Officer must be denied permission to reassign officers (403 Forbidden)"""
        inc_res = self.app.get('/api/incidents')
        inc_id = json.loads(inc_res.data)['incidents'][0]['id']

        res = self.app.post(f'/api/incidents/{inc_id}/assign',
                            headers={'X-User-Role': ROLE_FIELD_OFFICER},
                            data=json.dumps({'officer': 'Someone Else', 'range': 'North Beat'}),
                            content_type='application/json')
        self.assertEqual(res.status_code, 403)
        data = json.loads(res.data)
        self.assertIn('Access Denied', data['error'])

    def test_rbac_analyst_denied_status_update(self):
        """Analyst must be denied permission to change incident lifecycle status (403 Forbidden)"""
        inc_res = self.app.get('/api/incidents')
        inc_id = json.loads(inc_res.data)['incidents'][0]['id']

        res = self.app.post(f'/api/incidents/{inc_id}/status',
                            headers={'X-User-Role': ROLE_ANALYST},
                            data=json.dumps({'status': 'Resolved'}),
                            content_type='application/json')
        self.assertEqual(res.status_code, 403)
        data = json.loads(res.data)
        self.assertIn('Access Denied', data['error'])

    def test_rbac_role_switching(self):
        """Verify role switching API updates current user context"""
        res = self.app.post('/api/auth/switch-role',
                            data=json.dumps({'role': ROLE_FIELD_OFFICER}),
                            content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data['current_user']['role'], ROLE_FIELD_OFFICER)

    # =========================================================================
    # Phase 5: Field Investigation Photo Upload Tests
    # =========================================================================

    def test_field_photo_upload_success(self):
        """Verify field officer can upload genuine ground-truthing photographic evidence"""
        inc_res = self.app.get('/api/incidents')
        inc_id = json.loads(inc_res.data)['incidents'][0]['id']

        # Create dummy image data
        fake_image = (io.BytesIO(b"fake-image-bytes-jpeg"), "tree_stump_evidence.jpg")

        res = self.app.post(
            f'/api/incidents/{inc_id}/upload-photo',
            headers={'X-User-Role': ROLE_FIELD_OFFICER},
            data={
                'photo': fake_image,
                'caption': 'Fresh illegal logging stumps identified at 15.01N, 75.02E',
                'author': 'Beat Guard S. Patil'
            },
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data['status_action'], 'photo_uploaded')
        self.assertIn('/static/uploads/evidence/', data['photo_url'])
        
        # Verify note is present in incident
        notes = data['incident']['field_notes']
        self.assertTrue(any('Fresh illegal logging' in n['text'] for n in notes))
        self.assertTrue(any(n.get('photo_url') == data['photo_url'] for n in notes))

    def test_field_photo_upload_invalid_extension_rejected(self):
        """Verify disallowed file extensions (.sh, .exe, .txt) are rejected"""
        inc_res = self.app.get('/api/incidents')
        inc_id = json.loads(inc_res.data)['incidents'][0]['id']

        fake_script = (io.BytesIO(b"malicious script"), "exploit.sh")

        res = self.app.post(
            f'/api/incidents/{inc_id}/upload-photo',
            headers={'X-User-Role': ROLE_FIELD_OFFICER},
            data={'photo': fake_script},
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertIn('Invalid image format', data['error'])

if __name__ == '__main__':
    unittest.main()
