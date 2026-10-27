import unittest
import json
from app import app

class TestAppEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_feature_selection_page(self):
        """Root route '/' should render the dedicated Feature Selection Page (RoadSafe AI inspired)"""
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ForestWatch", response.data)
        self.assertIn(b"Dashboard", response.data)
        
        # Verify all 6 feature cards are present
        self.assertIn(b"Forest Location Explorer", response.data)
        self.assertIn(b"Vegetation Health", response.data)
        self.assertIn(b"Change Detection", response.data)
        self.assertIn(b"Historical Trends", response.data)
        self.assertIn(b"Reports & History", response.data)
        self.assertIn(b"Monitoring Overview", response.data)
        
        # Verify card links point to /dashboard?view=...
        self.assertIn(b"view=explorer", response.data)
        self.assertIn(b"view=vegetation", response.data)
        self.assertIn(b"view=change", response.data)
        self.assertIn(b"view=historical", response.data)
        self.assertIn(b"view=reports", response.data)
        self.assertIn(b"view=overview", response.data)

        # Internal navbar should NOT be present on feature selection page
        self.assertNotIn(b'class="navbar"', response.data)
        self.assertNotIn(b'ws-overview', response.data)

    def test_dashboard_internal_workspaces(self):
        """Dashboard route '/dashboard' should render the internal workspace app with navigation"""
        response = self.app.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ForestWatch", response.data)
        self.assertIn(b"ws-overview", response.data)
        self.assertIn(b"ws-explorer", response.data)
        self.assertIn(b"ws-vegetation", response.data)
        self.assertIn(b"ws-change", response.data)
        self.assertIn(b"ws-historical", response.data)
        self.assertIn(b"ws-reports", response.data)
        self.assertIn(b"ws-settings", response.data)
        
        # Verify Return to Feature Selection button is present
        self.assertIn(b"btn-hub-return", response.data)
        self.assertIn(b"Feature Selection", response.data)

    def test_direct_route_redirects(self):
        """Convenience direct links should redirect to dashboard with proper view parameter"""
        res_exp = self.app.get('/explorer')
        self.assertEqual(res_exp.status_code, 302)
        self.assertIn('/dashboard?view=explorer', res_exp.headers['Location'])

        res_chg = self.app.get('/change')
        self.assertEqual(res_chg.status_code, 302)
        self.assertIn('/dashboard?view=change', res_chg.headers['Location'])

    def test_api_locations(self):
        response = self.app.get('/api/locations')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("locations", data)
        self.assertGreater(len(data["locations"]), 0)

    def test_api_geocode(self):
        response = self.app.get('/api/geocode?q=Western')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("results", data)
        self.assertGreater(len(data["results"]), 0)

    def test_analyses_list(self):
        response = self.app.get('/analyses')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("analyses", data)

    def test_status_endpoint(self):
        response = self.app.get('/status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("status", data)

if __name__ == '__main__':
    unittest.main()
